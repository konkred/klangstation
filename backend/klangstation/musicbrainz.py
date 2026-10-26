"""MusicBrainz- und Cover-Art-Archive-Client, der sich an die Nutzungsregeln haelt.

Regeln von musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting:
  * hoechstens 1 Anfrage pro Sekunde und IP (hier: 1,1 s Abstand, global serialisiert)
  * aussagekraeftiger User-Agent mit Kontaktadresse
  * bei 503 zurueckhalten (Retry-After beachten, exponentielles Backoff)
Dazu kommen ein persistenter Cache, auch fuer Fehlschlaege, und das Buendeln
gleichzeitiger identischer Anfragen, damit dieselbe Frage nur einmal gestellt wird.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from .cache import Cache
from .config import VERSION, Settings

log = logging.getLogger("klangstation.musicbrainz")

MB_BASE = "https://musicbrainz.org/ws/2"
CAA_BASE = "https://coverartarchive.org"
MIN_INTERVAL = 1.1
DAY = 86400


def _lucene(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


_EDITION_WORDS = (r"edition|deluxe|expanded|remaster(?:ed)?|anniversary|bonus|special|version|"
                  r"collector'?s|explicit|reissue|super\s+deluxe")
_EDITION = re.compile(
    rf"\s*(?:[\(\[][^\)\]]*\b(?:{_EDITION_WORDS})\b[^\)\]]*[\)\]]"   # "(Deluxe Edition)", "[Remastered 2011]"
    rf"|\s+-\s+[^-]*\b(?:{_EDITION_WORDS})\b[^-]*)$",                 # " - 2011 Remaster"
    re.I)


def strip_edition(album: str) -> str:
    """'M!ssundaztood (Expanded Edition)' -> 'M!ssundaztood'; mehrere Zusaetze nacheinander."""
    previous = None
    while album and album != previous:
        previous, album = album, _EDITION.sub("", album).strip()
    return album or previous or ""


class Unavailable(Exception):
    """Vorubergehend keine Antwort (Netz, Drosselung, Serverfehler) - nicht als 'nicht gefunden' cachen."""


def _lengths_match(tracks, durations: List[float], tolerance: float = 3.0) -> bool:
    if not durations or len(tracks) != len(durations):
        return False
    for track, seconds in zip(tracks, durations):
        length = track.get("length") or (track.get("recording") or {}).get("length")
        if not length or abs(length / 1000.0 - seconds) > tolerance:
            return False
    return True


def _artist_credit(credits) -> str:
    return "".join(c.get("name", "") + c.get("joinphrase", "") for c in credits or [])


class MusicBrainz:
    def __init__(self, settings: Settings, cache: Cache, cover_dir: Path):
        self.settings = settings
        self.cache = cache
        self.cover_dir = cover_dir
        cover_dir.mkdir(parents=True, exist_ok=True)
        self.http = httpx.AsyncClient(timeout=20, follow_redirects=True)
        self._lock = asyncio.Lock()
        self._next_at = 0.0
        self._blocked_until = 0.0
        self._inflight: Dict[str, "asyncio.Future[Any]"] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.settings.get("metadata_online"))

    def user_agent(self) -> str:
        contact = self.settings.get("musicbrainz_contact") or "self-hosted; no contact configured"
        return f"Klangstation/{VERSION} ( {contact} )"

    async def close(self) -> None:
        await self.http.aclose()

    async def _dedupe(self, key: str, factory):
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])
        fut = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            result = await factory()
            fut.set_result(result)
            return result
        except Exception as exc:
            fut.set_exception(exc)
            fut.exception()  # als abgerufen markieren
            raise
        finally:
            self._inflight.pop(key, None)

    async def _get(self, path: str, params: Dict[str, str], ttl: float = 30 * DAY) -> Optional[dict]:
        key = "mb:" + path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        found, value = self.cache.lookup(key)
        if found:
            return value
        if not self.enabled:
            return None
        if time.time() < self._blocked_until:
            raise Unavailable("MusicBrainz pausiert nach wiederholter Drosselung")
        return await self._dedupe(key, lambda: self._fetch(key, path, params, ttl))

    async def _fetch(self, key: str, path: str, params: Dict[str, str], ttl: float) -> Optional[dict]:
        loop = asyncio.get_running_loop()
        async with self._lock:
            for attempt in range(4):
                delay = self._next_at - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                log.info("MusicBrainz-Anfrage: %s %s", path, params.get("query", ""))
                try:
                    resp = await self.http.get(MB_BASE + path, params=dict(params, fmt="json"),
                                               headers={"User-Agent": self.user_agent(),
                                                        "Accept": "application/json"})
                except httpx.HTTPError as exc:
                    self._next_at = loop.time() + MIN_INTERVAL * 5
                    raise Unavailable(f"MusicBrainz nicht erreichbar: {exc}")
                self._next_at = loop.time() + MIN_INTERVAL
                if resp.status_code in (429, 503):
                    # Retry-After kann 0 sein; trotzdem nie sofort erneut fragen
                    backoff = 2.0 * (2 ** attempt)
                    try:
                        wait = max(backoff, float(resp.headers.get("Retry-After", "")))
                    except ValueError:
                        wait = backoff
                    log.warning("MusicBrainz drosselt (HTTP %s), warte %.0fs", resp.status_code, wait)
                    self._next_at = loop.time() + wait
                    continue
                if resp.status_code in (400, 404):
                    self.cache.set(key, None, DAY)
                    return None
                if resp.status_code >= 400:
                    raise Unavailable(f"MusicBrainz antwortet mit HTTP {resp.status_code}")
                data = resp.json()
                self.cache.set(key, data, ttl)
                return data
            # Wiederholt gedrosselt: fuer eine Weile ganz pausieren
            self._blocked_until = time.time() + 300
            raise Unavailable("MusicBrainz drosselt wiederholt, Pause fuer 5 Minuten")

    # ---------------------------------------------------------------- Alben
    async def find_release(self, artist: str, album: str) -> Optional[Dict[str, str]]:
        # Streamingdienste haengen oft "(Deluxe Edition)" o. Ae. an, MusicBrainz fuehrt das
        # meist nicht im Titel. Erst das Grundalbum suchen, dann den vollen Titel.
        base = strip_edition(album)
        for title in dict.fromkeys(t for t in (base, album) if t):
            query = f'release:"{_lucene(title)}"'
            if artist:
                query += f' AND artist:"{_lucene(artist)}"'
            data = await self._get("/release", {"query": query, "limit": "5"})
            for rel in (data or {}).get("releases", []):
                if int(rel.get("score", 0)) >= 90:
                    return {"id": rel["id"], "group": (rel.get("release-group") or {}).get("id", "")}
        return None

    # ---------------------------------------------------------------- CDs
    async def lookup_disc(self, disc_id: str, toc: str, durations: List[float]) -> Optional[Dict[str, Any]]:
        """Exakter Treffer ueber die Disc-ID, sonst nur ein unscharfer Treffer mit passenden Titellaengen.

        Ist die Disc-ID unbekannt, liefert MusicBrainz ueber den TOC aehnliche Releases.
        Darunter sind oft fremde Alben mit gleicher Titelzahl, daher die Laengenpruefung.
        """
        data = await self._get(f"/discid/{disc_id}", {"inc": "recordings artist-credits", "toc": toc})
        releases = (data or {}).get("releases") or []
        candidates = []
        for rel in releases:
            for medium in rel.get("media", []):
                ids = {d.get("id") for d in medium.get("discs", [])}
                if disc_id in ids:
                    candidates.insert(0, (rel, medium))
                elif _lengths_match(medium.get("tracks", []), durations):
                    candidates.append((rel, medium))
        if not candidates:
            return None
        rel, medium = candidates[0]
        return {
            "mbid": rel["id"],
            "group": (rel.get("release-group") or {}).get("id", ""),
            "album": rel.get("title", ""),
            "artist": _artist_credit(rel.get("artist-credit")),
            "date": rel.get("date", ""),
            "tracks": [{
                "number": int(t.get("position", i + 1)),
                "title": t.get("title", ""),
                "artist": _artist_credit(t.get("artist-credit")) or _artist_credit(rel.get("artist-credit")),
            } for i, t in enumerate(medium.get("tracks", []))],
        }

    # ---------------------------------------------------------------- Cover
    def _cover_path(self, key: str) -> Path:
        return self.cover_dir / (hashlib.sha1(key.encode()).hexdigest() + ".jpg")

    async def cover(self, *, artist: str = "", album: str = "", mbid: str = "", group: str = "") -> Optional[Path]:
        key = mbid or f"{artist.lower()}|{album.lower()}"
        path = self._cover_path(key)
        if path.exists():
            return path
        if self.cache.has("nocover:" + key) or not self.enabled:
            return None
        if not mbid:
            try:
                found = await self.find_release(artist, album)
            except Unavailable as exc:
                log.info("Kein Cover fuer %s - %s: %s", artist, album, exc)
                return None  # spaeter erneut versuchen, nichts cachen
            if not found:
                self.cache.set("nocover:" + key, True, 7 * DAY)
                return None
            mbid, group = found["id"], found["group"]
        return await self._dedupe("cover:" + key, lambda: self._download(key, path, mbid, group))

    async def _download(self, key: str, path: Path, mbid: str, group: str) -> Optional[Path]:
        urls = [f"{CAA_BASE}/release/{mbid}/front-500"]
        if group:
            urls.append(f"{CAA_BASE}/release-group/{group}/front-500")
        for url in urls:
            try:
                resp = await self.http.get(url, headers={"User-Agent": self.user_agent()})
            except httpx.HTTPError:
                return None
            if resp.status_code == 200 and resp.content:
                tmp = path.with_suffix(".tmp")
                tmp.write_bytes(resp.content)
                tmp.replace(path)
                return path
            if resp.status_code >= 500 or resp.status_code == 429:
                return None  # voruebergehend, nicht als "kein Cover" merken
            await asyncio.sleep(0.5)
        self.cache.set("nocover:" + key, True, 7 * DAY)
        return None
