"""HTTP-API, WebSocket und Auslieferung der Weboberflaeche."""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import logging
import struct
from pathlib import Path

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket, WebSocketDisconnect

from http.cookies import SimpleCookie

from . import audio
from .auth import COOKIE, MAX_AGE, check_password, hash_password
from .config import VERSION, WEB_DIR
from .core import Core
from .mpd import MPDError

log = logging.getLogger("klangstation.api")
core: Core = None  # type: ignore[assignment]

ART_CACHE = {"Cache-Control": "public, max-age=86400"}


def ok(data=None) -> JSONResponse:
    return JSONResponse({"ok": True} if data is None else data)


async def body(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        raise HTTPException(400, "JSON erwartet")
    if not isinstance(data, dict):
        raise HTTPException(400, "JSON-Objekt erwartet")
    return data


def _sniff(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:3] == b"GIF":
        return "image/gif"
    return "application/octet-stream"


# ---------------------------------------------------------------- Zustand
async def get_state(request):
    return ok(await core.state())


async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    queue = core.subscribe()
    try:
        await ws.send_json({"type": "state", "data": await core.state()})

        async def pump():
            while True:
                await ws.send_json(await queue.get())

        async def drain():
            while True:
                await ws.receive_text()  # Pings des Browsers, sonst nichts

        tasks = [asyncio.create_task(pump()), asyncio.create_task(drain())]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for t in pending:
            t.cancel()
        for t in done:
            t.exception()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        core.unsubscribe(queue)


# ---------------------------------------------------------------- Player
async def player_action(request):
    await core.player(request.path_params["action"])
    return ok()


async def player_seek(request):
    data = await body(request)
    await core.seek(float(data.get("position", 0)))
    return ok()


async def player_volume(request):
    data = await body(request)
    await core.set_volume(int(data.get("volume", 0)))
    return ok()


async def player_mode(request):
    data = await body(request)
    for key in ("random", "repeat", "single"):
        if key in data:
            await core.mpd.run(key, "1" if data[key] else "0")
    return ok()


# ---------------------------------------------------------------- Warteschlange
async def queue_get(request):
    return ok(await core.queue())


async def queue_add(request):
    data = await body(request)
    uris = [u for u in data.get("uris", []) if isinstance(u, str)]
    if not uris:
        raise HTTPException(400, "uris fehlt")
    await core.queue_add(uris, "play" if data.get("mode") == "play" else "append")
    return ok()


async def queue_play(request):
    data = await body(request)
    await core.take_over("mpd")
    await core.mpd.run("playid", int(data["id"]))
    return ok()


async def queue_remove(request):
    data = await body(request)
    await core.mpd.run("deleteid", int(data["id"]))
    return ok()


async def queue_move(request):
    data = await body(request)
    await core.mpd.run("moveid", int(data["id"]), int(data["to"]))
    return ok()


async def queue_clear(request):
    await core.mpd.run("clear")
    return ok()


# ---------------------------------------------------------------- Bibliothek
async def library_browse(request):
    return ok(await core.browse(request.query_params.get("path", "")))


async def library_albums(request):
    return ok(await core.albums())


async def library_album(request):
    q = request.query_params
    return ok(await core.album_tracks(q.get("album", ""), q.get("artist", "")))


async def library_search(request):
    q = request.query_params.get("q", "").strip()
    return ok(await core.search(q) if len(q) >= 2 else [])


async def library_update(request):
    await core.mpd.run("update")
    return ok()


async def media_list(request):
    return ok(core.media)


# ---------------------------------------------------------------- Cover
async def art(request):
    q = request.query_params
    try:
        if q.get("uri"):
            result = await core.art_for_file(q["uri"])
        elif q.get("album"):
            result = await core.art_for_album(q["album"], q.get("artist", ""))
        else:
            result = None
    except MPDError:
        result = None
    if isinstance(result, bytes):
        return Response(result, media_type=_sniff(result), headers=ART_CACHE)
    if isinstance(result, Path):
        return FileResponse(str(result), media_type="image/jpeg", headers=ART_CACHE)
    return Response(status_code=404)


_SILENCE_RATE = 8000  # 8 bit mono: 8 KB je Sekunde


def _silence_header(size: int) -> bytes:
    return (b"RIFF" + struct.pack("<I", 36 + size) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 1, _SILENCE_RATE, _SILENCE_RATE, 1, 8) + b"data" + struct.pack("<I", size))


async def silence(request):
    """Stille in Laenge des Titels fuer die Sperrbildschirm-Steuerung am Handy.

    iOS nimmt die Zeitanzeige dort von der Tonspur, die die Seite abspielt - sie muss so lang sein wie der
    Titel und an derselben Stelle laufen. Erzeugt wird nur der angefragte Ausschnitt (Safari fragt in Teilen).
    """
    try:
        seconds = min(max(int(request.query_params.get("s", "5")), 1), 4 * 3600)
    except ValueError:
        return Response(status_code=400)
    size = seconds * _SILENCE_RATE
    total = 44 + size
    start, end = 0, total - 1
    rng = request.headers.get("range", "")
    if rng.startswith("bytes="):
        a, _, b = rng[6:].split(",")[0].partition("-")
        try:
            if a:
                start, end = int(a), min(int(b), total - 1) if b else total - 1
            elif b:
                start = max(total - int(b), 0)
        except ValueError:
            pass
        if start > end or start >= total:
            return Response(status_code=416, headers={"Content-Range": f"bytes */{total}"})
    header = _silence_header(size)

    async def chunks():
        pos = start
        while pos <= end:
            n = min(65536, end - pos + 1)
            if pos < 44:
                part = (header + b"\x80" * 65536)[pos:pos + n]
            else:
                part = b"\x80" * n
            yield part
            pos += len(part)

    headers = {"Accept-Ranges": "bytes", "Content-Length": str(end - start + 1), "Cache-Control": "public, max-age=86400"}
    if rng:
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
    return StreamingResponse(chunks(), status_code=206 if rng else 200, media_type="audio/wav", headers=headers)


async def art_cd(request):
    path = core.cd.get("art_path")
    if not path:
        return Response(status_code=404)
    return FileResponse(path, media_type="image/jpeg", headers=ART_CACHE)


async def art_airplay(request):
    data = core.airplay.cover
    if not data:
        return Response(status_code=404)
    return Response(data, media_type=_sniff(data), headers=ART_CACHE)


async def lyrics(request):
    q = request.query_params
    try:
        duration = float(q.get("duration") or 0)
    except ValueError:
        duration = 0.0
    result = await core.lyrics.find(artist=q.get("artist", ""), title=q.get("title", ""), album=q.get("album", ""),
                                    duration=duration, uri=q.get("uri", ""))
    if not result:
        return Response(status_code=404)
    return JSONResponse(result)


# ---------------------------------------------------------------- Radio
async def radio_search(request):
    q = request.query_params
    try:
        limit = max(1, min(200, int(q.get("limit", "60"))))
        offset = max(0, int(q.get("offset", "0")))
    except ValueError:
        raise HTTPException(400, "limit/offset muessen Zahlen sein")
    return ok(await core.radio.search(q.get("q", ""), q.get("country", ""), q.get("tag", ""), limit, offset))


async def radio_countries(request):
    return ok(await core.radio.countries())


async def radio_tags(request):
    return ok(await core.radio.tags())


async def radio_play(request):
    await core.play_station(await body(request))
    return ok()


async def radio_favorites(request):
    if request.method == "GET":
        return ok(core.settings.get("radio_favorites"))
    data = await body(request)
    favs = [f for f in core.settings.get("radio_favorites") if f.get("uuid") != data.get("uuid")]
    if data.get("favorite", True):
        favs.append({k: data.get(k, "") for k in ("uuid", "name", "url", "favicon", "country", "codec", "bitrate")})
    core.settings.update({"radio_favorites": favs})
    core.broadcast({"type": "settings"})
    return ok(favs)


# ---------------------------------------------------------------- CD
async def cd_get(request):
    return ok(core.cd_public())


async def cd_play(request):
    data = await body(request) if await request.body() else {}
    await core.cd_play(int(data.get("track", 1)))
    return ok()


async def cd_eject(request):
    await core.cd_eject()
    return ok()


async def cd_rip(request):
    if request.method == "POST":
        data = await body(request)
        await core.rip_start(str(data.get("target", "local")), bool(data.get("eject", True)))
    return ok(core.rip_info())


async def cd_rip_cancel(request):
    await core.rip_cancel()
    return ok(core.rip_info())


# ---------------------------------------------------------------- Einstellungen
async def settings_endpoint(request):
    if request.method == "POST":
        await core.update_settings(await body(request))
    return ok({"settings": core.settings.public(), "outputs": audio.list_outputs(),
               "active_output": core.output, "services": core.services(), "cec": core.cec.public(),
               "shares": core.shares_public(), "version": VERSION})


# ---------------------------------------------------------------- Zugangsschutz
def _client(request) -> str:
    return request.client.host if request.client else ""


async def auth_status(request):
    a = core.auth
    local = _client(request) in ("127.0.0.1", "::1")
    return ok({"enabled": a.enabled, "scope": a.scope, "local": local,
               "logged_in": (not a.enabled) or local or a.cookie_valid(request.cookies.get(COOKIE))})


def _with_session(response: Response) -> Response:
    response.set_cookie(COOKIE, core.auth.make_cookie(), max_age=MAX_AGE, httponly=True, samesite="lax")
    return response


async def auth_login(request):
    a, ip = core.auth, _client(request)
    wait = a.wait_seconds(ip)
    if wait:
        raise HTTPException(429, f"Zu viele Fehlversuche, bitte {wait} s warten")
    password = str((await body(request)).get("password", ""))
    if not a.enabled:
        return ok()
    if not await asyncio.to_thread(check_password, password, core.settings.get("auth_hash")):
        a.failed(ip)
        raise HTTPException(401, "Falsches Passwort")
    a.succeeded(ip)
    return _with_session(ok())


async def auth_logout(request):
    response = ok()
    response.delete_cookie(COOKIE)
    return response


async def auth_password(request):
    """Passwort setzen/aendern/entfernen. Bei aktivem Schutz nur angemeldet (prueft die Middleware)."""
    data = await body(request)
    password = str(data.get("password", ""))
    # Nach dem Entfernen wieder die harmlosere Voreinstellung, falls nichts anderes gewuenscht ist
    scope = data.get("scope", "settings" if data.get("remove") else core.auth.scope)
    if scope not in ("all", "settings"):
        raise HTTPException(400, "Ungültiger Schutzumfang")
    if password and len(password) < 6:
        raise HTTPException(400, "Das Passwort muss mindestens 6 Zeichen haben")
    changes = {"auth_scope": scope}
    if password:
        changes["auth_hash"] = await asyncio.to_thread(hash_password, password)
    elif data.get("remove"):
        changes["auth_hash"] = ""
    core.settings.update(changes)
    if password or data.get("remove"):
        core.auth.rotate_secret()  # alle anderen Sitzungen abmelden
    core.broadcast({"type": "settings"})
    return _with_session(ok({"enabled": core.auth.enabled, "scope": core.auth.scope}))


class AuthMiddleware:
    """Prueft vor jeder Anfrage (auch WebSocket), ob eine Anmeldung noetig ist."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket") or core is None:
            return await self.app(scope, receive, send)
        cookie = None
        for name, value in scope.get("headers", []):
            if name == b"cookie":
                jar = SimpleCookie()
                jar.load(value.decode("latin-1"))
                if COOKIE in jar:
                    cookie = jar[COOKIE].value
        client = (scope.get("client") or ("", 0))[0]
        if core.auth.needs_login(scope["path"], scope.get("method", "GET"), client, cookie):
            if scope["type"] == "websocket":
                # Erst annehmen, dann schliessen: vor dem Accept wird daraus ein HTTP 403 und der Browser
                # sieht nur 1006 statt 4401 - die Seite wuesste dann nicht, dass sie sich anmelden muss
                if (await receive())["type"] == "websocket.connect":
                    await send({"type": "websocket.accept"})
                    await send({"type": "websocket.close", "code": 4401})
                return
            response = JSONResponse({"ok": False, "error": "Anmeldung erforderlich", "auth": True}, status_code=401)
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)


# ---------------------------------------------------------------- Netzwerkfreigaben
async def shares_get(request):
    return ok(core.shares_public())


async def shares_action(request):
    return ok(await core.share_action(request.path_params["action"], await body(request)))


# ---------------------------------------------------------------- Wiedergabelisten
async def playlists_get(request):
    return ok(await core.playlists())


async def playlist_get(request):
    return ok(await core.playlist_tracks(request.query_params.get("name", "")))


async def playlist_action(request):
    await core.playlist_action(request.path_params["action"], await body(request))
    return ok()


# ---------------------------------------------------------------- Fernseh-Bildschirm
async def tv_page(request):
    return FileResponse(str(WEB_DIR / "tv.html"), headers={"Cache-Control": "no-cache"})


async def tv_status(request):
    return ok(core.tv_status())


async def tv_show(request):
    return ok(core.tv_show())


# ---------------------------------------------------------------- Schlummer-Timer und Wecker
async def alarms_get(request):
    return ok({"alarms": core.timers.alarms(), **core.timers.public()})


async def alarms_action(request):
    core.timers.alarm_action(request.path_params["action"], await body(request))
    return ok({"alarms": core.timers.alarms(), **core.timers.public()})


async def sleep_timer(request):
    await core.timers.set_sleep((await body(request)).get("minutes"))
    return ok(core.timers.public())


async def services(request):
    return ok(core.services())


async def bluetooth_get(request):
    return ok(core.bt.public())


async def bluetooth_action(request):
    data = await body(request)
    await core.bt_action(request.path_params["action"], str(data.get("path", "")))
    return ok(core.bt.public())


async def internal_hook(request):
    if request.client is None or request.client.host not in ("127.0.0.1", "::1"):
        raise HTTPException(403)
    token = request.headers.get("X-Klangstation-Token", "")
    if not hmac.compare_digest(token, core.hook_token):
        raise HTTPException(403)
    await core.hook(await body(request))
    return ok()


# ---------------------------------------------------------------- Fehler
async def http_error(request, exc: HTTPException):
    return JSONResponse({"ok": False, "error": exc.detail}, status_code=exc.status_code)


async def value_error(request, exc: ValueError):
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


async def mpd_error(request, exc: MPDError):
    return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


async def offline_error(request, exc: Exception):
    return JSONResponse({"ok": False, "error": str(exc) or "Dienst nicht erreichbar"}, status_code=503)


class RevalidatedStatic(StaticFiles):
    """Oberflaechen-Dateien jedes Mal nachfragen lassen (bei Gleichstand nur 304). Ohne Vorgabe nimmt der
    Browser sie nach einem Update ungefragt aus dem Cache - auch der Kiosk nach dem Neuladen."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


async def index(request):
    return FileResponse(str(WEB_DIR / "index.html"), headers={"Cache-Control": "no-cache"})


@contextlib.asynccontextmanager
async def lifespan(app):
    global core
    core = Core()
    await core.start()
    try:
        yield
    finally:
        await core.stop()


routes = [
    Route("/", index),
    Route("/api/state", get_state),
    WebSocketRoute("/ws", ws_endpoint),
    Route("/api/player/seek", player_seek, methods=["POST"]),
    Route("/api/player/volume", player_volume, methods=["POST"]),
    Route("/api/player/mode", player_mode, methods=["POST"]),
    Route("/api/player/{action}", player_action, methods=["POST"]),
    Route("/api/queue", queue_get),
    Route("/api/queue/add", queue_add, methods=["POST"]),
    Route("/api/queue/play", queue_play, methods=["POST"]),
    Route("/api/queue/remove", queue_remove, methods=["POST"]),
    Route("/api/queue/move", queue_move, methods=["POST"]),
    Route("/api/queue/clear", queue_clear, methods=["POST"]),
    Route("/api/library/browse", library_browse),
    Route("/api/library/albums", library_albums),
    Route("/api/library/album", library_album),
    Route("/api/library/search", library_search),
    Route("/api/library/update", library_update, methods=["POST"]),
    Route("/api/media", media_list),
    Route("/api/art", art),
    Route("/api/silence.wav", silence),
    Route("/api/art/cd", art_cd),
    Route("/api/art/airplay", art_airplay),
    Route("/api/lyrics", lyrics),
    Route("/api/radio/search", radio_search),
    Route("/api/radio/countries", radio_countries),
    Route("/api/radio/tags", radio_tags),
    Route("/api/radio/play", radio_play, methods=["POST"]),
    Route("/api/radio/favorites", radio_favorites, methods=["GET", "POST"]),
    Route("/api/cd", cd_get),
    Route("/api/cd/play", cd_play, methods=["POST"]),
    Route("/api/cd/eject", cd_eject, methods=["POST"]),
    Route("/api/cd/rip", cd_rip, methods=["GET", "POST"]),
    Route("/api/cd/rip/cancel", cd_rip_cancel, methods=["POST"]),
    Route("/api/settings", settings_endpoint, methods=["GET", "POST"]),
    Route("/api/services", services),
    Route("/api/bluetooth", bluetooth_get),
    Route("/api/bluetooth/{action}", bluetooth_action, methods=["POST"]),
    Route("/api/auth/status", auth_status),
    Route("/api/auth/login", auth_login, methods=["POST"]),
    Route("/api/auth/logout", auth_logout, methods=["POST"]),
    Route("/api/auth/password", auth_password, methods=["POST"]),
    Route("/api/shares", shares_get),
    Route("/api/shares/{action}", shares_action, methods=["POST"]),
    Route("/api/playlists", playlists_get),
    Route("/api/playlist", playlist_get),
    Route("/api/playlist/{action}", playlist_action, methods=["POST"]),
    Route("/tv", tv_page),
    Route("/api/tv", tv_status),
    Route("/api/tv/show", tv_show, methods=["POST"]),
    Route("/api/alarms", alarms_get),
    Route("/api/alarms/{action}", alarms_action, methods=["POST"]),
    Route("/api/sleep", sleep_timer, methods=["POST"]),
    Route("/api/internal/hook", internal_hook, methods=["POST"]),
    Mount("/", RevalidatedStatic(directory=str(WEB_DIR)), name="web"),
]

app = Starlette(
    routes=routes,
    lifespan=lifespan,
    middleware=[Middleware(AuthMiddleware)],
    exception_handlers={HTTPException: http_error, ValueError: value_error, MPDError: mpd_error,
                        ConnectionError: offline_error, OSError: offline_error},
)
