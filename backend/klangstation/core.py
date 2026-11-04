"""Zentrale Steuerung: Quellen-Umschaltung, Zustand, Bibliothek, CD, Einstellungen."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import quote as urlquote

from . import audio, cdrom, ripper as ripper_mod, shares as shares_mod
from .airplay import MetadataReader
from .auth import Auth
from .bluetooth import Bluetooth
from .cache import Cache
from .cec import Cec
from .config import (BIN_BLUEALSA_APLAY, BIN_GMEDIARENDER, BIN_LIBRESPOT, BIN_MPD, BIN_SHAIRPORT, CD_DEVICE,
                     COVER_DIR, DATA_DIR, HOOK_PATH, MEDIA_ROOT, MPD_HOST, MPD_PORT, PORT, RUN_DIR, SPOTIFY_SINK,
                     SPOTIFY_ZEROCONF_PORT, WEB_BUILD, Settings)
from .daemons import Daemon
from .lyrics import Lyrics
from .mpd import MPD, MPDError, build, to_objects
from .network import Network
from .musicbrainz import MusicBrainz, Unavailable
from .radio import RadioBrowser
from .timers import Timers
from .upnp import PORT as UPNP_PORT
from .upnp import UpnpRenderer
from .weather import Weather

log = logging.getLogger("klangstation.core")

SPOTIFY_EVENTS_START = {"loading", "playing"}
# Dateisysteme, auf die ks-netmount gerippte CDs schreiben kann (fuseblk = NTFS ueber ntfs-3g)
WRITABLE_FS = {"vfat", "exfat", "ext2", "ext3", "ext4", "ntfs3", "fuseblk", "btrfs", "xfs", "f2fs"}


def _media_kind(uri: str) -> Optional[str]:
    if not uri:
        return None
    if uri.startswith(("http://", "https://")):
        return "radio"
    if uri.startswith("cdda://"):
        return "cd"
    return "file"


class Core:
    def __init__(self) -> None:
        for d in (DATA_DIR, RUN_DIR, COVER_DIR, DATA_DIR / "playlists", DATA_DIR / "librespot"):
            d.mkdir(parents=True, exist_ok=True)
        self.settings = Settings(DATA_DIR / "settings.json")
        self.auth = Auth(self.settings, DATA_DIR)
        self.cec = Cec()
        self.cec.on_key = lambda action: self._spawn(self._remote_key(action))
        self.cec.on_tv_standby = lambda: self._spawn(self._tv_turned_off())
        self.tv_launch = 1   # erhoeht sich, wenn der Fernseh-Bildschirm (neu) angezeigt werden soll
        self.cache = Cache(DATA_DIR / "cache.sqlite")
        self.mb = MusicBrainz(self.settings, self.cache, COVER_DIR)
        self.lyrics = Lyrics(self.settings, self.cache, MEDIA_ROOT)
        self.weather = Weather(self.settings, self.cache)
        self.timers = Timers(self)
        # Zuletzt gehoert (fuer den Ruhebildschirm): je Album bzw. Sender ein Eintrag, neueste zuerst
        self.history: List[Dict[str, Any]] = self._load_history()
        self.radio = RadioBrowser()
        self.mpd = MPD(MPD_HOST, MPD_PORT)
        self.shares = shares_mod.Shares(self.mpd)
        self.shares.on_scan = self._on_share_scan
        self._scan_seen: Set[str] = set()
        self.ripper = ripper_mod.Ripper()
        self.ripper.on_change = self.push
        self.upnp = UpnpRenderer()
        self.bt = Bluetooth()
        self.net = Network()
        self.daemons = {
            "mpd": Daemon("mpd", BIN_MPD, on_line=self.shares.on_mpd_line),
            "airplay": Daemon("airplay", BIN_SHAIRPORT),
            "spotify": Daemon("spotify", BIN_LIBRESPOT, on_line=self._spotify_line),
            "upnp": Daemon("upnp", BIN_GMEDIARENDER, on_line=self.upnp.on_line),
            "bluetooth": Daemon("bluetooth", BIN_BLUEALSA_APLAY, on_line=self._bt_line),
            "cec": Daemon("cec", "cec-ctl", on_line=self.cec.on_line),
        }
        self.upnp.on_busy = lambda: self._claim("upnp")
        self._claiming: Set[str] = set()
        if not self.settings.get("upnp_uuid"):
            self.settings.update({"upnp_uuid": str(uuid.uuid4())})
        self.hook_token = secrets.token_urlsafe(24)
        self.clients: Set["asyncio.Queue[dict]"] = set()
        self.source = "idle"
        self.output: Dict[str, str] = {}
        self.surround = 2
        self.spotify: Dict[str, Any] = {}
        self.airplay_active = False
        self.airplay = MetadataReader(RUN_DIR / "shairport-metadata", self._on_airplay_meta)
        self.cd: Dict[str, Any] = {"available": False, "status": "none", "present": False}
        self.stations: Dict[str, Dict[str, Any]] = {}
        self.media: List[Dict[str, str]] = []
        self._tasks: List[asyncio.Task] = []
        # asyncio haelt Aufgaben nur schwach - ohne Referenz raeumt der Garbage Collector sie mittendrin weg
        self._bg: Set[asyncio.Task] = set()
        self._push_pending = False
        self._takeover_lock = asyncio.Lock()
        self._last_mpd: "tuple[Dict[str, str], Dict[str, str]]" = ({}, {})
        # Webradio nach Verbindungsabbruch: {"uri", "until", "next"} solange neu verbunden wird
        self._stream_retry: Optional[Dict[str, Any]] = None
        # Titel von einer Freigabe wegen Serverausfall angehalten: {"uri", "share"}
        self._share_hold: Optional[Dict[str, Any]] = None
        # Ausgabe von anderem Programm belegt (MPD konnte nicht starten): Zeitpunkt, bis zu dem neu versucht wird
        self._output_busy: Optional[float] = None

    # ------------------------------------------------------------ Lebenszyklus
    async def start(self) -> None:
        await self.apply_audio()
        self._spawn(self._apply_player_level())
        self._tasks = [
            asyncio.create_task(self.mpd.idle_loop(self._on_mpd_change)),
            asyncio.create_task(self._guarded("CD-Ueberwachung", self._cd_loop)),
            asyncio.create_task(self._guarded("Datentraeger-Ueberwachung", self._mount_loop)),
            asyncio.create_task(self._guarded("UPnP-Ueberwachung", self._upnp_loop)),
            asyncio.create_task(self._guarded("Bluetooth-Ueberwachung", self._bt_loop)),
            asyncio.create_task(self._guarded("CEC-Steuerung", self._cec_loop)),
            asyncio.create_task(self._guarded("Webradio-Waechter", self._stream_loop)),
            asyncio.create_task(self._guarded("Freigabe-Waechter", self._share_loop)),
            asyncio.create_task(self._guarded("Ausgabe-Waechter", self._busy_loop)),
            asyncio.create_task(self._guarded("Regler-Waechter", self._mixer_loop)),
            asyncio.create_task(self._guarded("Schlummer-Timer und Wecker", self.timers.loop)),
            asyncio.create_task(self._guarded("Wetter", self._weather_loop)),
            asyncio.create_task(self._guarded("Netzwerk-Ueberwachung", self._net_loop)),
        ]
        if self.daemons["airplay"].available:
            self._tasks.append(asyncio.create_task(self._guarded("AirPlay-Metadaten", self.airplay.run)))

    @staticmethod
    async def _guarded(name: str, loop_fn) -> None:
        """Haelt eine Ueberwachungsschleife am Leben; Fehler landen im Log statt die Aufgabe still zu beenden."""
        while True:
            try:
                await loop_fn()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("%s abgestuerzt, starte neu", name)
                await asyncio.sleep(2)

    async def stop(self) -> None:
        await self.ripper.cancel()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        for d in self.daemons.values():
            await d.stop()
        await self.mb.close()
        await self.lyrics.close()
        await self.weather.close()
        await self.radio.close()
        await self.upnp.close()

    def _hook_env(self) -> Dict[str, str]:
        return {"KS_HOOK_URL": f"http://127.0.0.1:{PORT}/api/internal/hook", "KS_HOOK_TOKEN": self.hook_token}

    def _spawn(self, coro) -> None:
        task = asyncio.get_running_loop().create_task(coro)
        self._bg.add(task)
        task.add_done_callback(self._bg.discard)

    async def apply_audio(self, which=("mpd", "airplay", "spotify", "upnp", "bluetooth", "cec")) -> None:
        s = self.settings
        self.output = audio.resolve(s.get("output"))
        dev = self.output["id"]
        name = s.get("device_name")
        self.surround = await asyncio.to_thread(audio.configure_surround, dev, s.get("speakers"), s.get("bitperfect"))
        log.info("Ausgabe: %s (%s)%s", self.output["label"], dev,
                 f", hochgemischt auf {self.surround} Kanaele" if self.surround > 2 else "")
        fixed = await asyncio.to_thread(audio.prepare_mixer, dev)
        if fixed:
            log.info("Mixer: %s", ", ".join(fixed))
        if "mpd" in which:
            conf = DATA_DIR / "mpd.conf"
            conf.write_text(audio.mpd_config(data_dir=DATA_DIR, media_root=MEDIA_ROOT, port=MPD_PORT,
                                             device=dev, bitperfect=s.get("bitperfect"),
                                             normalize=s.get("loudness") == "dynamic"), encoding="utf-8")
            await self.daemons["mpd"].start(["--no-daemon", "--stderr", str(conf)])
            self._spawn(self._apply_playback())
        if "airplay" in which:
            if s.get("airplay_enabled"):
                conf = DATA_DIR / "shairport-sync.conf"
                conf.write_text(audio.shairport_config(name=name, device=dev, hook=HOOK_PATH,
                                                       pipe=self.airplay.pipe), encoding="utf-8")
                await self.daemons["airplay"].start(["-c", str(conf)], self._hook_env())
            else:
                await self.daemons["airplay"].stop()
            self.airplay_active = False
            self.airplay.reset()
        if "spotify" in which:
            if s.get("spotify_enabled"):
                args = audio.librespot_args(name=name, device=dev, bitrate=s.get("spotify_bitrate"),
                                            hook=HOOK_PATH, sink=SPOTIFY_SINK, cache=DATA_DIR / "librespot",
                                            port=SPOTIFY_ZEROCONF_PORT)
                await self.daemons["spotify"].start(args, self._hook_env())
            else:
                await self.daemons["spotify"].stop()
            self.spotify = {}
        if "upnp" in which:
            self.upnp.reset()
            if s.get("upnp_enabled"):
                args = audio.gmediarender_args(name=name, device=dev, uuid=s.get("upnp_uuid"), port=UPNP_PORT)
                await self.daemons["upnp"].start(args)
            else:
                await self.daemons["upnp"].stop()
        if "bluetooth" in which:
            if s.get("bluetooth_enabled"):
                await self.bt.start(name)
                if self.bt.available:
                    await self.daemons["bluetooth"].start(audio.bluealsa_aplay_args(device=dev))
            else:
                await self.daemons["bluetooth"].stop()
        if "cec" in which:
            await self.daemons["cec"].stop()
            if s.get("cec_enabled"):
                # CEC haengt am HDMI-Ausgang: bei Ausgabe-Wechsel auf HDMI 1 auch /dev/cec1 nutzen
                await self.cec.setup(name, dev)
                if self.cec.available:
                    await self.daemons["cec"].start(self.cec.monitor_args())
        if self.source in ("airplay", "spotify", "upnp", "bluetooth"):
            self.source = "idle"

    # ------------------------------------------------------------ Quellen
    async def take_over(self, new: str) -> None:
        """Gibt das Audiogeraet fuer die neue Quelle frei (ALSA hw ist exklusiv)."""
        async with self._takeover_lock:
            if new != "mpd":
                try:
                    status = await self.mpd.dict("status")
                    if status.get("state") == "play":
                        await self.mpd.run("stop")
                except (ConnectionError, MPDError):
                    pass
            if new != "airplay" and self.airplay_active:
                self.airplay_active = False
                self.airplay.reset()
                await self.daemons["airplay"].restart()
            if new != "spotify" and self.spotify.get("active"):
                self.spotify = {}
                await self.daemons["spotify"].restart()
            if new != "upnp" and self.upnp.playing:
                try:
                    await self.upnp.action("Stop")
                except (ConnectionError, ValueError):
                    await self.daemons["upnp"].restart()
                    self.upnp.reset()
            if new != "bluetooth" and self.bt.streaming:
                try:
                    await self.bt.control("Pause")  # Handy pausiert, statt ins Leere zu streamen
                except Exception:  # noqa: BLE001
                    pass
                await self.daemons["bluetooth"].restart()  # Geraet sofort freigeben
            self.source = new
        self.push()

    async def hook(self, payload: Dict[str, Any]) -> None:
        src, event = payload.get("source"), payload.get("event", "")
        env = payload.get("env") or {}
        if src == "airplay":
            if event == "start":
                self.airplay_active = True
                await self.take_over("airplay")
            elif event == "stop":
                self.airplay_active = False
                self.airplay.reset()
                if self.source == "airplay":
                    self.source = "idle"
        elif src == "spotify":
            if event.startswith("session_"):
                log.info("Spotify: %s %s", event, {k: v for k, v in env.items() if k.startswith("CLIENT_")})
            sp = self.spotify
            if event in SPOTIFY_EVENTS_START:
                sp["active"] = True
                if self.source != "spotify":
                    await self.take_over("spotify")
                    sp = self.spotify = dict(sp, active=True)
                if event == "playing":
                    sp["state"] = "play"
            elif event == "paused":
                sp["state"] = "pause"
            elif event == "stopped":
                sp["state"] = "stop"
            elif event == "session_disconnected":
                self.spotify = sp = {}
                if self.source == "spotify":
                    self.source = "idle"
            elif event == "session_client_changed":
                # Name des steuernden Geraets (z. B. "iPhone von Anna"), nicht die Konto-ID
                sp["client"] = env.get("CLIENT_NAME") or " ".join(
                    x for x in (env.get("CLIENT_BRAND_NAME"), env.get("CLIENT_MODEL_NAME")) if x)
            elif event == "track_changed":
                covers = (env.get("COVERS") or "").split()
                sp.update({
                    "title": env.get("NAME", ""),
                    "artist": ", ".join(a for a in (env.get("ARTISTS") or "").splitlines() if a),
                    "album": env.get("ALBUM", ""),
                    "art": covers[0] if covers else None,
                    "duration": int(env.get("DURATION_MS") or 0) / 1000.0,
                })
            elif event == "volume_changed" and env.get("VOLUME", "").isdigit():
                sp["volume"] = round(int(env["VOLUME"]) / 65535 * 100)
            if "POSITION_MS" in env:
                sp["elapsed"] = int(env["POSITION_MS"] or 0) / 1000.0
                sp["at"] = time.time()
        self.push()

    async def _on_airplay_meta(self, meta: Dict[str, Any]) -> None:
        self.push()

    def _bt_line(self, line: str) -> None:
        if "busy" in line.lower():
            self._claim("bluetooth")

    def _spotify_line(self, line: str) -> None:
        # librespot oeffnet das Geraet erst beim Abspielen; haelt es dann noch AirPlay o. a., meldet es
        # "... May be Invalid, Busy, or Already in Use" und beendet sich - vorher freigeben, sonst klappt
        # erst ein spaeterer Neustart und die Uebernahme dauert spuerbar
        if "busy" in line.lower() and "sink" in line.lower():
            self._claim("spotify")

    def _claim(self, source: str) -> None:
        """Eine Quelle wollte starten, das ALSA-Geraet war aber noch belegt: freigeben und erneut starten."""
        if source in self._claiming:
            return
        self._claiming.add(source)

        async def run() -> None:
            try:
                log.info("%s: Audiogeraet belegt, gebe es frei und starte erneut", source)
                await self.take_over(source)
                await asyncio.sleep(0.3)
                if source == "upnp":
                    await self.upnp.action("Play")
                elif source == "bluetooth":
                    await self.daemons["bluetooth"].restart()  # verbindet sich neu mit dem laufenden Stream
            except Exception as exc:  # noqa: BLE001
                log.info("%s liess sich nicht neu starten: %s", source, exc)
            finally:
                await asyncio.sleep(2)  # nicht in eine Schleife geraten, falls das Geraet belegt bleibt
                self._claiming.discard(source)
        self._spawn(run())

    async def _upnp_loop(self) -> None:
        """gmediarender hat keine Hooks: Zustand jede Sekunde per SOAP abfragen."""
        last = None
        while True:
            await asyncio.sleep(1)
            if not self.upnp.base:
                continue
            try:
                info = await self.upnp.poll()
            except Exception as exc:  # noqa: BLE001 - Renderer startet gerade neu o. Ae.
                log.debug("UPnP-Abfrage fehlgeschlagen: %s", exc)
                continue
            if self.upnp.playing and self.source != "upnp":
                await self.take_over("upnp")
                # War das Geraet beim Start noch belegt, bricht GStreamer ab: dann erneut starten
                await asyncio.sleep(1)
                try:
                    if (await self.upnp.poll()).get("transport") == "STOPPED":
                        await self.upnp.action("Play")
                except Exception:  # noqa: BLE001
                    pass
            key = (info.get("transport"), info.get("title"), info.get("volume"), int(info.get("elapsed", 0)) // 10)
            if key != last and self.source == "upnp":
                self.push()
            last = key

    async def _bt_loop(self) -> None:
        last = None
        retry_at = 0.0
        running_for = 0  # Sekunden, die eine Bluetooth-PCM ununterbrochen laeuft
        while True:
            await asyncio.sleep(1)
            if not self.settings.get("bluetooth_enabled"):
                continue
            if self.bt.adapter_removed():
                await self.daemons["bluetooth"].stop()
                if self.source == "bluetooth":
                    self.source = "idle"
                self.push()
            if not self.bt.available:
                # USB-Stick nachtraeglich eingesteckt bzw. bluetoothd spaeter gestartet: ohne Neustart uebernehmen
                if time.monotonic() >= retry_at:
                    retry_at = time.monotonic() + 10
                    await self.bt.start(self.settings.get("device_name"))
                    if self.bt.available:
                        await self.daemons["bluetooth"].start(audio.bluealsa_aplay_args(device=self.output["id"]))
                        self.push()
                continue
            try:
                await self.bt.ensure_registered()
                await self.bt.poll()
            except Exception as exc:  # noqa: BLE001 - z. B. bluetoothd startet neu
                log.debug("Bluetooth-Abfrage fehlgeschlagen: %s", exc)
                continue
            p = self.bt.player
            # Nach jedem Neustart von bluealsa-aplay (Ausgabewechsel) ist die PCM des verbundenen, aber
            # pausierten iPhones kurz "Running" und wuerde sonst Radio & Co. stoppen. Darum: nie bei AVRCP
            # "paused"; meldet das Handy "playing", sofort; ohne brauchbaren AVRCP-Status (Laptops, Browser
            # melden "stopped") erst, wenn die PCM 3 s am Stueck laeuft.
            running_for = running_for + 1 if self.bt.streaming else 0
            avrcp = p.get("avrcp")
            if self.source != "bluetooth" and avrcp != "paused" and \
                    (running_for >= 3 or (running_for and avrcp == "playing")):
                await self.take_over("bluetooth")
            elif self.source == "bluetooth" and not p.get("device"):
                self.source = "idle"  # Handy hat die Verbindung getrennt
            key = (self.bt.active, p.get("device"), p.get("state"), p.get("title"), p.get("volume"),
                   self.bt.pairing, tuple(sorted((d["path"], d["connected"]) for d in self.bt.devices.values())))
            if key != last:
                self.push()
            last = key

    # ------------------------------------------------------------ Zustand
    def subscribe(self) -> "asyncio.Queue[dict]":
        q: "asyncio.Queue[dict]" = asyncio.Queue(maxsize=50)
        self.clients.add(q)
        return q

    def unsubscribe(self, q) -> None:
        self.clients.discard(q)

    def broadcast(self, message: Dict[str, Any]) -> None:
        for q in list(self.clients):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass

    def push(self) -> None:
        """Zustand gebuendelt an alle Browser schicken (max. alle 100 ms)."""
        if self._push_pending:
            return
        self._push_pending = True

        async def later():
            await asyncio.sleep(0.1)
            self._push_pending = False
            self.broadcast({"type": "state", "data": await self.state()})
        self._spawn(later())

    async def _on_mpd_change(self, changed: List[str]) -> None:
        if "reconnect" in changed and self.settings.get("shares"):
            # MPD vergisst Einbindungen beim Neustart
            self._spawn(self._sync_shares())
        if "stored_playlist" in changed:
            self.broadcast({"type": "playlists"})
        if "playlist" in changed or "reconnect" in changed:
            self.broadcast({"type": "queue"})
        if "database" in changed or "update" in changed:
            self.broadcast({"type": "library"})
        if "player" in changed:
            try:
                status = await self.mpd.dict("status")
                if status.get("state") == "play" and self.source != "mpd":
                    await self.take_over("mpd")
            except (ConnectionError, MPDError):
                pass
        self.push()

    async def state(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "source": self.source,
            "device_name": self.settings.get("device_name"),
            "output": self.output.get("label", ""),
            "cd": self.cd_public(),
            "rip": self.ripper.public(),
            "media": self.media,
            "mpd_online": False,
            "services": {n: {"available": d.available, "running": d.running} for n, d in self.daemons.items()},
            "bluetooth": self.bt.public(),
            "network": self.net.public(),
            "tv_lyrics": self.settings.get("tv_lyrics"),
            "tv_theme": self.settings.get("tv_theme"),
            "timers": self.timers.public(),
            "history": self.history if self.settings.get("tv_history") else [],
            "weather": self.weather.public(),
            "web_build": WEB_BUILD,
            "ts": time.time(),
        }
        status: Dict[str, str] = {}
        song: Dict[str, str] = {}
        try:
            # Kurzes Limit: haengt MPD (z. B. beim Lesen einer ausgeworfenen CD), bleibt die Anzeige trotzdem aktuell
            status = await asyncio.wait_for(self.mpd.dict("status"), 2)
            song = await asyncio.wait_for(self.mpd.dict("currentsong"), 2)
            self._last_mpd = (status, song)
            out["mpd_online"] = True
        except asyncio.TimeoutError:
            status, song = self._last_mpd
            out["mpd_online"] = True
        except (ConnectionError, MPDError):
            pass
        out["volume"] = int(status.get("volume", -1))
        out["random"] = status.get("random") == "1"
        out["repeat"] = status.get("repeat") == "1"
        out["single"] = status.get("single") == "1"
        out["queue_length"] = int(status.get("playlistlength", 0))
        out["queue_pos"] = int(status["song"]) if "song" in status else None

        if self.source == "spotify" and self.spotify:
            sp = self.spotify
            elapsed = sp.get("elapsed", 0.0)
            if sp.get("state") == "play" and sp.get("at"):
                elapsed += time.time() - sp["at"]
            out["now"] = {"kind": "spotify", "state": sp.get("state", "stop"), "title": sp.get("title", ""),
                          "artist": sp.get("artist", ""), "album": sp.get("album", ""), "art": sp.get("art"),
                          "elapsed": elapsed, "duration": sp.get("duration", 0), "extra": sp.get("client", "")}
            out["volume"] = sp.get("volume", -1)
        elif self.source == "airplay" and self.airplay_active:
            m = self.airplay.meta
            if self.airplay.cover_current:
                art = f"/api/art/airplay?v={self.airplay.cover_version}"
            elif m.get("album"):
                # iOS hat (noch) kein Bild zum aktuellen Titel geschickt: Cover ueber MusicBrainz
                art = "/api/art?album=" + urlquote(m["album"]) + "&artist=" + urlquote(m.get("artist", ""))
            else:
                art = None
            out["now"] = {"kind": "airplay", "state": "pause" if m.get("paused") else "play",
                          "title": m.get("title", ""), "artist": m.get("artist", ""), "album": m.get("album", ""),
                          "art": art,
                          "elapsed": self.airplay.position(), "duration": m.get("duration", 0),
                          "extra": m.get("client", "")}
            out["volume"] = m.get("volume", -1)
        elif self.source == "upnp" and self.upnp.info:
            u = self.upnp.info
            elapsed = u.get("elapsed", 0.0)
            if u.get("state") == "play":
                elapsed += time.time() - u.get("at", time.time())
            if u.get("duration"):
                elapsed = min(elapsed, u["duration"])
            out["now"] = {"kind": "upnp", "state": u.get("state", "stop"), "title": u.get("title", ""),
                          "artist": u.get("artist", ""), "album": u.get("album", ""),
                          "art": u.get("art") or self._mb_art(u.get("album"), u.get("artist")),
                          "elapsed": elapsed, "duration": u.get("duration", 0), "extra": ""}
            out["volume"] = u.get("volume", -1)
        elif self.source == "bluetooth" and self.bt.player:
            p = self.bt.player
            out["now"] = {"kind": "bluetooth", "state": p.get("state", "stop"),
                          "title": p.get("title") or "Bluetooth-Audio",
                          "artist": p.get("artist", ""), "album": p.get("album", ""),
                          "art": self._mb_art(p.get("album"), p.get("artist")),
                          "elapsed": self.bt.position(), "duration": p.get("duration", 0),
                          "extra": p.get("device_name", "")}
            out["volume"] = p.get("volume", -1)
        else:
            out["now"] = self._mpd_now(status, song)
        self._remember(out["now"])
        return out

    # ------------------------------------------------------------ Zuletzt gehoert
    HISTORY_MAX = 16

    def _load_history(self) -> List[Dict[str, Any]]:
        try:
            data = json.loads((DATA_DIR / "history.json").read_text(encoding="utf-8"))
            return [h for h in data if isinstance(h, dict) and h.get("art")][: self.HISTORY_MAX]
        except (OSError, ValueError):
            return []

    def _remember(self, now: Dict[str, Any]) -> None:
        if now.get("state") != "play" or not now.get("kind"):
            return
        art = now.get("art") or ""
        if now["kind"] == "airplay" and art.startswith("/api/art/airplay"):
            art = self._mb_art(now.get("album"), now.get("artist")) or ""  # Bild vom Handy ist nur voruebergehend
        if now["kind"] == "radio":
            entry = {"art": art, "title": now.get("extra", "").split(" · ")[0], "sub": "Webradio"}
        else:
            entry = {"art": art, "title": now.get("album") or now.get("title", ""), "sub": now.get("artist", "")}
        if not entry["art"] or not entry["title"]:
            return
        if self.history and self.history[0]["title"] == entry["title"] and self.history[0]["sub"] == entry["sub"]:
            if self.history[0]["art"] == entry["art"]:
                return
            self.history[0] = entry  # gleiches Album, Cover kam spaeter
        else:
            self.history = [entry] + [h for h in self.history
                                      if (h["title"], h["sub"]) != (entry["title"], entry["sub"])][: self.HISTORY_MAX - 1]
        try:
            path = DATA_DIR / "history.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.history, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            log.info("Verlauf nicht gespeichert: %s", exc)

    async def _net_loop(self) -> None:
        # Adapter (z. B. USB-WLAN-Stick) und Adressen live in den Optionen
        while True:
            if await self.net.changed():
                self.push()
            await asyncio.sleep(3)

    async def _weather_loop(self) -> None:
        while True:
            if await self.weather.refresh():
                self.push()
            await asyncio.sleep(30)

    @staticmethod
    def _mb_art(album: Optional[str], artist: Optional[str]) -> Optional[str]:
        """Cover ueber MusicBrainz fuer Quellen, die kein Bild mitliefern."""
        if not album:
            return None
        return "/api/art?album=" + urlquote(album) + "&artist=" + urlquote(artist or "")

    def _mpd_now(self, status: Dict[str, str], song: Dict[str, str]) -> Dict[str, Any]:
        uri = song.get("file", "")
        kind = _media_kind(uri)
        now: Dict[str, Any] = {
            "kind": kind, "state": status.get("state", "stop"), "uri": uri,
            "title": song.get("Title", ""), "artist": song.get("Artist") or song.get("AlbumArtist", ""),
            "album": song.get("Album", ""), "art": None, "extra": "",
            "elapsed": float(status.get("elapsed", 0) or 0),
            "duration": float(status.get("duration") or song.get("Time") or 0),
            "bitrate": status.get("bitrate", ""), "format": status.get("audio", ""),
        }
        if kind == "file":
            if not now["title"]:
                now["title"] = os.path.splitext(os.path.basename(uri))[0]
            now["art"] = "/api/art?uri=" + urlquote(uri)
            if self._share_hold and self._share_hold["uri"] == uri:
                now["extra"] = f"Freigabe „{self._share_hold['share']['name']}“ nicht erreichbar – angehalten"
        elif kind == "radio":
            st = self.station(uri)
            now["extra"] = st.get("name") or song.get("Name", "")
            if self._stream_retry and self._stream_retry["uri"] == uri:
                now["extra"] += " · Verbindung unterbrochen – neuer Versuch …"
            now["art"] = st.get("favicon") or None
            stream = song.get("Title", "")
            if " - " in stream:
                now["artist"], now["title"] = stream.split(" - ", 1)
            else:
                now["title"], now["artist"] = stream or now["extra"], ""
            now["album"] = ""
        elif kind == "cd":
            try:
                number = int(uri.rstrip("/").rsplit("/", 1)[-1])
            except ValueError:
                number = 0
            track = next((t for t in self.cd.get("tracks", []) if t["number"] == number), {})
            now["title"] = track.get("title") or f"Titel {number}"
            now["artist"] = track.get("artist") or self.cd.get("artist", "")
            now["album"] = self.cd.get("album") or "Audio-CD"
            now["duration"] = now["duration"] or track.get("duration", 0)
            now["art"] = self.cd.get("art")
            if not self.cd.get("present"):
                now["state"] = "stop"  # MPD meldet nach dem Auswerfen noch eine Weile "play"
        if self._output_busy is not None:
            now["extra"] = " · ".join(p for p in (now["extra"], "Ausgabe gerade belegt – neuer Versuch …") if p)
        return now

    # ------------------------------------------------------------ Wiedergabe
    async def player(self, action: str) -> None:
        if self.source == "bluetooth" and self.bt.player.get("device"):
            # AVRCP: das Handy fuehrt den Befehl aus
            toggle = "Pause" if self.bt.player.get("state") == "play" else "Play"
            avrcp = {"play": "Play", "pause": "Pause", "toggle": toggle, "stop": "Pause",
                     "next": "Next", "prev": "Previous"}
            try:
                await self.bt.control(avrcp[action])
            except KeyError:
                raise ValueError("Unbekannte Aktion")
            except ValueError:
                raise
            except Exception as exc:  # noqa: BLE001 - D-Bus-Fehler verstaendlich melden
                raise ValueError(f"Bluetooth-Geraet reagiert nicht: {exc}")
            return
        if self.source == "upnp" and self.upnp.info:
            if action in ("next", "prev"):
                raise ValueError("Weiter und Zurück wählst du in der App, die streamt")
            toggle = "Pause" if self.upnp.info.get("state") == "play" else "Play"
            await self.upnp.action({"play": "Play", "pause": "Pause", "toggle": toggle, "stop": "Stop"}[action])
            return
        # AirPlay/Spotify werden vom Handy gesteuert; Play oder Stopp hier beendet die Fremdsitzung
        if self.source in ("airplay", "spotify") and action in ("play", "toggle", "stop"):
            await self.take_over("mpd")
        if self._output_busy is not None and action in ("pause", "stop", "toggle"):
            # Nutzer will nicht mehr warten: Wiederholung beenden, sonst startet es spaeter ungefragt
            self._output_busy = None
            await self.mpd.run("clearerror")
            self.push()
            if action == "toggle":
                return
        cmds = {"play": "play", "pause": "pause 1", "stop": "stop", "next": "next", "prev": "previous"}
        if action == "toggle":
            status = await self.mpd.dict("status")
            await self.mpd.raw("pause 1" if status.get("state") == "play" else "play")
        elif action in cmds:
            await self.mpd.raw(cmds[action])
        else:
            raise ValueError("Unbekannte Aktion")

    async def seek(self, position: float) -> None:
        if self.source == "upnp":
            await self.upnp.seek(position)
        elif self.source in ("bluetooth", "airplay", "spotify"):
            raise ValueError("Spulen geht bei dieser Quelle nur in der App")
        else:
            await self.mpd.run("seekcur", position)

    async def set_volume(self, volume: int) -> None:
        volume = max(0, min(100, volume))
        if self.source == "upnp":
            await self.upnp.set_volume(volume)
        elif self.source == "bluetooth":
            try:
                await self.bt.set_volume(volume)
            except ValueError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"Lautstärke lässt sich nur am Gerät einstellen ({exc})")
        elif self.source in ("airplay", "spotify"):
            raise ValueError("Die Lautstärke stellst du bei dieser Quelle am Handy ein")
        else:
            await self.mpd.run("setvol", volume)

    async def bt_action(self, action: str, path: str = "") -> None:
        try:
            if action == "pairing_on":
                await self.bt.set_pairing(True)
            elif action == "pairing_off":
                await self.bt.set_pairing(False)
            elif action == "disconnect":
                await self.bt.disconnect(path)
            elif action == "remove":
                await self.bt.remove(path)
            else:
                raise ValueError("Unbekannte Aktion")
        except ValueError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"Bluetooth: {exc}")
        await self.bt.poll()
        self.push()

    # ------------------------------------------------------------ Webradio-Waechter
    STREAM_STALL = 20        # s ohne Fortschritt bei "play" -> neu verbinden
    STREAM_RETRY_EVERY = 15  # s zwischen zwei Versuchen, wenn MPD mit Fehler angehalten hat
    STREAM_GIVE_UP = 1800    # s, danach bleibt der Sender aus
    OUTPUT_BUSY_GIVE_UP = 120  # s, danach bleibt die Wiedergabe angehalten (sonst startet sie irgendwann ungefragt)
    MIXER_FIX_WINDOW = 30    # s nach dem Start von WirePlumber, in denen die Regler zurueckgeholt werden

    async def _stream_loop(self) -> None:
        """Haelt Webradio nach einem Netzausfall am Laufen.

        Bricht die Verbindung ohne Fehler ab (Router weg, WLAN weg), bleibt MPD auf "play" stehen und
        verbindet nie neu - auch nicht, wenn das Netz zurueckkommt. Steht elapsed still, startet der
        Waechter den Sender neu und wiederholt das, bis er wieder spielt oder der Nutzer etwas anderes macht.
        """
        last: "tuple[str, float]" = ("", -1.0)
        still_since = 0.0
        while True:
            await asyncio.sleep(5)
            now = time.monotonic()
            retry = self._stream_retry
            try:
                status = await asyncio.wait_for(self.mpd.dict("status"), 3)
                song = await asyncio.wait_for(self.mpd.dict("currentsong"), 3)
            except (ConnectionError, MPDError, asyncio.TimeoutError):
                continue
            uri, state = song.get("file", ""), status.get("state")
            elapsed = float(status.get("elapsed", 0) or 0)
            playing_radio = self.source == "mpd" and state == "play" and _media_kind(uri) == "radio"
            if not playing_radio and not retry:
                last = ("", -1.0)  # nach Pause/Stopp neu anfangen zu zaehlen
                continue
            if playing_radio and (status.get("songid", ""), elapsed) != last:
                last, still_since = (status.get("songid", ""), elapsed), now
                if retry and retry["uri"] == uri and elapsed > 2:
                    log.info("Webradio spielt wieder: %s", uri)
                    self._stream_retry = None
                    self.push()
                continue

            if retry:
                # Nutzer hat gestoppt, pausiert, etwas anderes gewaehlt oder die Quelle gewechselt
                stopped_by_error = state == "stop" and status.get("error")
                if self.source != "mpd" or uri != retry["uri"] or not (playing_radio or stopped_by_error):
                    self._stream_retry = None
                    self.push()
                    continue
                if now > retry["until"]:
                    log.warning("Webradio nach %d min nicht erreichbar, gebe auf: %s", self.STREAM_GIVE_UP // 60, uri)
                    self._stream_retry = None
                    await self.mpd.run("stop")
                    self.push()
                    continue

            if playing_radio and now - still_since >= self.STREAM_STALL:
                if not retry:
                    log.warning("Webradio haengt seit %d s, verbinde neu: %s", self.STREAM_STALL, uri)
                    self._stream_retry = retry = {"uri": uri, "until": now + self.STREAM_GIVE_UP}
                await self._stream_restart(status)
                still_since = now
            elif retry and state == "stop" and now - still_since >= self.STREAM_RETRY_EVERY:
                await self._stream_restart(status)
                still_since = now

    async def _busy_loop(self) -> None:
        """Startet MPD neu, wenn die Ausgabe belegt war (Desktop-Ton ueber PipeWire auf derselben Karte).

        MPD bleibt dann mit "Device or resource busy" auf Pause und versucht es nicht wieder. PipeWire gibt die Karte
        ~5 s nach dem letzten Ton frei.
        """
        while True:
            await asyncio.sleep(3)
            try:
                status = await asyncio.wait_for(self.mpd.dict("status"), 2)
                error = status.get("error", "").lower()
                if "busy" not in error and "belegt" not in error:
                    if self._output_busy is not None:
                        self._output_busy = None
                        self.push()
                    continue
                now = time.monotonic()
                if self.source not in ("mpd", "idle") or status.get("state") == "stop":
                    give_up = True
                elif self._output_busy is None:
                    log.warning("Ausgabe belegt, versuche es weiter: %s", status.get("error"))
                    self._output_busy = now + self.OUTPUT_BUSY_GIVE_UP
                    self.push()
                    give_up = False
                else:
                    give_up = now > self._output_busy
                if give_up:
                    if self._output_busy is not None:
                        log.warning("Ausgabe weiter belegt, Wiedergabe bleibt angehalten")
                    self._output_busy = None
                    await self.mpd.run("clearerror")
                    self.push()
                    continue
                song = await asyncio.wait_for(self.mpd.dict("currentsong"), 2)
                elapsed = float(status.get("elapsed", 0) or 0)
                if elapsed > 1 and _media_kind(song.get("file", "")) != "radio":
                    await self.mpd.run("seek", status.get("song", "0"), elapsed)
                else:
                    await self.mpd.run("play", status.get("song", "0"))
            except (ConnectionError, MPDError, asyncio.TimeoutError):
                continue

    async def _mixer_loop(self) -> None:
        """Stellt die Regler wieder her, wenn WirePlumber startet (z. B. bei jeder Anmeldung am Desktop).

        WirePlumber setzt dabei HDMI und Kopfhoerer auf stumm/0 %, MPD spielt dann lautlos weiter. Nur in diesem Fall
        eingreifen: Wer die Regler sonst von Hand stumm schaltet, meint das so.
        """
        known = await asyncio.to_thread(audio.wireplumber_pids)
        fix_until = time.monotonic() + self.MIXER_FIX_WINDOW  # kann gerade eben erst gestartet sein
        while True:
            await asyncio.sleep(3)
            pids = await asyncio.to_thread(audio.wireplumber_pids)
            if pids - known:
                fix_until = time.monotonic() + self.MIXER_FIX_WINDOW
            known = pids
            if time.monotonic() < fix_until:
                fixed = await asyncio.to_thread(audio.prepare_mixer, self.output.get("id", ""))
                if fixed:
                    log.info("Mixer nach Start von WirePlumber: %s", ", ".join(fixed))

    async def _stream_restart(self, status: Dict[str, str]) -> None:
        try:
            await self.mpd.run("stop")
            await self.mpd.run("play", status.get("song", "0"))
        except (ConnectionError, MPDError) as exc:
            log.info("Neuverbindung fehlgeschlagen: %s", exc)
        self.push()

    # ------------------------------------------------------------ Freigabe-Waechter
    SHARE_STALL = 15  # s ohne Fortschritt bei einem Titel von einer Freigabe -> anhalten

    async def _share_loop(self) -> None:
        """Haelt die Wiedergabe an, wenn der Server einer Freigabe wegbricht, und setzt sie danach fort.

        Ohne das spielt MPD ~3 min nichts (bis CIFS aufgibt) und ueberspringt dann die ganze Warteschlange
        mit "Host is down". Ein "pause" kehrt auch waehrend des Haengers sofort zurueck und haelt die Stelle.
        """
        last: "tuple[str, float]" = ("", -1.0)
        still_since = 0.0
        next_check = 0.0
        while True:
            await asyncio.sleep(3)
            now = time.monotonic()
            try:
                status = await asyncio.wait_for(self.mpd.dict("status"), 3)
                song = await asyncio.wait_for(self.mpd.dict("currentsong"), 3)
            except (ConnectionError, MPDError, asyncio.TimeoutError):
                continue
            uri, state = song.get("file", ""), status.get("state")
            hold = self._share_hold
            if hold:
                if uri != hold["uri"] or state != "pause" or self.source != "mpd":
                    self._share_hold = None  # Nutzer hat selbst weitergemacht oder etwas anderes gewaehlt
                elif now >= next_check:
                    next_check = now + 10
                    if not await shares_mod.reachable(hold["share"]):
                        log.info("Freigabe %s wieder erreichbar, spiele weiter", hold["share"]["name"])
                        self._share_hold = None
                        self.shares.status[hold["share"]["id"]] = {"mounted": True, "error": ""}
                        self.broadcast({"type": "shares", "data": self.shares_public()})
                        try:
                            # an der alten Stelle neu ansetzen: hat CIFS waehrend des Ausfalls aufgegeben,
                            # ist der angefangene Titel fuer MPD sonst kaputt und es ginge beim naechsten weiter
                            await self.mpd.run("seekid", hold["id"], f"{hold['elapsed']:.1f}")
                        except MPDError:
                            pass
                        await self.mpd.run("play")
                        self.push()
                continue
            share = self._share_of(uri)
            if not (share and state == "play" and self.source == "mpd"):
                last = ("", -1.0)
                continue
            elapsed = float(status.get("elapsed", 0) or 0)
            if (status.get("songid", ""), elapsed) != last:
                last, still_since = (status.get("songid", ""), elapsed), now
                continue
            if now - still_since < self.SHARE_STALL:
                continue
            reason = await shares_mod.reachable(share)
            if not reason:
                still_since = now  # Server antwortet, MPD puffert nur (z. B. langsames WLAN)
                continue
            log.warning("Freigabe %s: %s - halte die Wiedergabe an", share["name"], reason)
            await self.mpd.run("pause", "1")
            self._share_hold = {"uri": uri, "share": share, "id": status.get("songid", ""), "elapsed": elapsed}
            self.shares.status[share["id"]] = {"mounted": False, "error": reason + " – Wiedergabe angehalten"}
            self.broadcast({"type": "shares", "data": self.shares_public()})
            self.push()
            next_check, last = now + 10, ("", -1.0)

    def _share_of(self, uri: str) -> Optional[Dict[str, Any]]:
        top = uri.split("/", 1)[0]
        if not top.startswith(shares_mod.PREFIX):
            return None
        return next((s for s in self.settings.get("shares") or [] if shares_mod.mount_name(s) == top), None)

    # ------------------------------------------------------------ CEC
    async def _resume_mpd(self) -> None:
        """Nach einem Geraetewechsel weiterspielen, sobald der neu gestartete MPD erreichbar ist."""
        for _ in range(15):
            await asyncio.sleep(1)
            try:
                status = await self.mpd.dict("status")
                song = await self.mpd.dict("currentsong")
                if _media_kind(song.get("file", "")) == "radio":
                    # Pausiert wiederhergestellter Stream laeuft nach "play" oft nicht weiter -> frisch verbinden
                    await self.mpd.run("play", status.get("song", "0"))
                else:
                    await self.mpd.run("play")
                return
            except (ConnectionError, MPDError):
                continue
        log.info("Wiedergabe nach dem Geraetewechsel nicht fortgesetzt: MPD nicht erreichbar")

    async def _apply_playback(self, tries: int = 15) -> None:
        """ReplayGain und Ueberblenden in MPD setzen (nach dem Start und bei Aenderung).

        Bit-perfekt schliesst beides aus: beides rechnet die Samples um.
        """
        s = self.settings
        bitperfect = s.get("bitperfect")
        mode = "auto" if s.get("loudness") == "replaygain" and not bitperfect else "off"
        fade = 0 if bitperfect else s.get("crossfade")
        for attempt in range(tries):
            if attempt:
                await asyncio.sleep(1)
            try:
                await self.mpd.run("replay_gain_mode", mode)
                await self.mpd.run("crossfade", str(fade))
                return
            except (ConnectionError, MPDError):
                continue
        log.info("ReplayGain/Ueberblenden nicht gesetzt: MPD nicht erreichbar")

    async def _apply_player_level(self, tries: int = 15) -> None:
        """Stellt den Player-Regler beim Start auf 100 %, danach bleibt er frei verschiebbar.

        Bei Bit-perfekt hat MPD keinen Regler.
        """
        if self.settings.get("bitperfect"):
            return
        for attempt in range(tries):
            if attempt:
                await asyncio.sleep(1)
            try:
                await self.mpd.run("setvol", 100)
                return
            except (ConnectionError, MPDError):
                continue
        log.info("Player-Regler nicht gesetzt: MPD nicht erreichbar")

    async def _is_playing(self) -> bool:
        if self.source == "airplay":
            return self.airplay_active and not self.airplay.meta.get("paused")
        if self.source == "spotify":
            return self.spotify.get("state") == "play"
        if self.source == "upnp":
            return self.upnp.info.get("state") == "play"
        if self.source == "bluetooth":
            return self.bt.player.get("state") == "play"
        try:
            return (await asyncio.wait_for(self.mpd.dict("status"), 2)).get("state") == "play"
        except (ConnectionError, MPDError, asyncio.TimeoutError):
            return False

    async def _cec_loop(self) -> None:
        """Beim Start der Wiedergabe TV einschalten; nach Stille optional wieder aus."""
        was_playing, quiet_since = False, None
        while True:
            await asyncio.sleep(2)
            s = self.settings
            if not (s.get("cec_enabled") and self.cec.available):
                was_playing = False
                continue
            playing = await self._is_playing()
            if playing and not was_playing and s.get("cec_tv_on"):
                await self.cec.wake()
            if playing:
                quiet_since = None
            elif was_playing:
                quiet_since = time.time()
            minutes = s.get("cec_standby_minutes")
            # Nur einen Fernseher ausschalten, den Klangstation selbst eingeschaltet hat
            if (not playing and quiet_since and minutes and self.cec.woke_at
                    and time.time() - quiet_since > minutes * 60):
                log.info("%s Minuten keine Wiedergabe, schalte Fernseher aus", minutes)
                await self.cec.standby()
                self.cec.woke_at = 0.0
                quiet_since = None
            was_playing = playing

    async def _remote_key(self, action: str) -> None:
        """Taste auf der TV-Fernbedienung."""
        if self.source in ("airplay", "spotify"):
            # Diese Quellen steuert das Handy; per CEC laesst sich ihre Wiedergabe nicht anhalten
            log.info("TV-Fernbedienung (%s) ignoriert: %s wird am Handy gesteuert", action, self.source)
            return
        try:
            log.info("TV-Fernbedienung: %s", action)
            await self.player(action)
        except (ValueError, ConnectionError, MPDError) as exc:
            log.info("TV-Fernbedienung (%s): %s", action, exc)

    async def _tv_turned_off(self) -> None:
        if self.settings.get("cec_pause_on_tv_off") and await self._is_playing() \
                and self.source not in ("airplay", "spotify"):
            log.info("Fernseher ausgeschaltet, pausiere Wiedergabe")
            try:
                await self.player("pause")
            except (ValueError, ConnectionError, MPDError):
                pass

    # ------------------------------------------------------------ Netzwerkfreigaben
    async def _sync_shares(self) -> None:
        await self.shares.sync(self.settings.get("shares"), before_unmount=self._drop_media)
        self.broadcast({"type": "library"})
        self.broadcast({"type": "settings"})

    def shares_public(self) -> List[Dict[str, Any]]:
        out = []
        for s in self.settings.public()["shares"]:
            st = self.shares.status.get(s["id"], {"mounted": False, "error": ""})
            name = shares_mod.mount_name(s)
            out.append(dict(s, mount=name, scan=self.shares.scanning.get(name), **st))
        return out

    def _on_share_scan(self) -> None:
        """Einlesen begonnen/fortgeschritten/beendet: Oberflaeche aktualisieren, Wiedergabe davon sperren."""
        started = set(self.shares.scanning) - self._scan_seen
        finished = self._scan_seen - set(self.shares.scanning)
        self._scan_seen = set(self.shares.scanning)
        if started:
            # Abspielen waehrend des Einlesens wuerde beides ueber dieselbe (WLAN-)Leitung ausbremsen
            self._spawn(self._drop_scanning(started))
        self.broadcast({"type": "shares", "data": self.shares_public()})
        if started or finished:
            self.broadcast({"type": "library"})

    async def _drop_scanning(self, names: Set[str]) -> None:
        try:
            await self._drop_media(names)
        except (ConnectionError, MPDError):
            pass

    def _check_scanning(self, uris: List[str]) -> None:
        name = self.shares.blocked(uris)
        if name:
            label = next((s["name"] for s in self.settings.get("shares") if shares_mod.mount_name(s) == name), name)
            raise ValueError(f"„{label}“ wird noch eingelesen – Abspielen geht, sobald der Scan fertig ist")

    async def share_action(self, action: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        current = list(self.settings.get("shares"))
        if action == "save":
            share = shares_mod.validate(data, current)
            old = next((s for s in current if s["id"] == share["id"]), None)
            current = [s for s in current if s["id"] != share["id"]] + [share]
            self.settings.update({"shares": current})
            if old:  # geaenderte Zugangsdaten: neu einbinden
                try:
                    await self._drop_media({shares_mod.mount_name(old)})
                except (MPDError, ConnectionError):
                    pass
                await self.shares.unmount(old)
        elif action == "remove":
            self.settings.update({"shares": [s for s in current if s["id"] != data.get("id")]})
        elif action == "rescan":
            share = next((s for s in current if s["id"] == data.get("id")), None)
            if not share:
                raise ValueError("Unbekannte Freigabe")
            if not self.shares.status.get(share["id"], {}).get("mounted"):
                # Nicht eingebunden: "Neu einlesen" heisst dann "nochmal versuchen" (nicht leer einlesen)
                await self._sync_shares()
                return self.shares_public()
            await self.shares.rescan(share)
            return self.shares_public()
        else:
            raise ValueError("Unbekannte Aktion")
        await self._sync_shares()
        return self.shares_public()

    # ------------------------------------------------------------ Wiedergabelisten
    @staticmethod
    def _playlist_name(name: Any) -> str:
        name = str(name or "").strip()
        if not name or len(name) > 80 or "/" in name or name.startswith("."):
            raise ValueError("Ungültiger Name für eine Wiedergabeliste")
        return name

    async def playlists(self) -> List[Dict[str, str]]:
        items = to_objects(await self.mpd.run("listplaylists"), starts=("playlist",))
        return sorted(({"name": p["playlist"], "modified": p.get("Last-Modified", "")} for p in items if "playlist" in p),
                      key=lambda p: p["name"].lower())

    async def playlist_tracks(self, name: str) -> List[Dict[str, Any]]:
        tracks = []
        for i, e in enumerate(to_objects(await self.mpd.run("listplaylistinfo", self._playlist_name(name)), starts=("file",))):
            uri = e.get("file", "")
            item = self._song(e)
            item["pos"] = i
            if _media_kind(uri) == "radio":
                item["name"] = self.station(uri).get("name") or e.get("Name") or uri
                item["artist"] = "Webradio"
            tracks.append(item)
        return tracks

    async def playlist_action(self, action: str, data: Dict[str, Any]) -> None:
        name = self._playlist_name(data.get("name"))
        if action in ("play", "append") and self.shares.scanning:
            self._check_scanning([v for k, v in await self.mpd.run("listplaylist", name) if k == "file"])
        if action == "save":
            existing = {p["name"] for p in await self.playlists()}
            if name in existing:
                if not data.get("overwrite"):
                    raise ValueError(f"Die Wiedergabeliste „{name}“ gibt es schon")
                await self.mpd.run("rm", name)
            await self.mpd.run("save", name)
        elif action == "play":
            await self.take_over("mpd")
            start = int(data.get("start", 0))
            await self.mpd.batch(["clear", build("load", name), f"play {max(0, start)}"])
        elif action == "append":
            await self.mpd.run("load", name)
        elif action == "add":
            uris = [u for u in data.get("uris", []) if isinstance(u, str)]
            if not uris:
                raise ValueError("Nichts zum Hinzufügen")
            for st in data.get("stations") or []:
                if isinstance(st, dict):
                    self.remember_station(st)
            await self.mpd.batch([build("playlistadd", name, u) for u in uris])
        elif action == "remove_track":
            await self.mpd.run("playlistdelete", name, int(data["pos"]))
        elif action == "move_track":
            await self.mpd.run("playlistmove", name, int(data["pos"]), int(data["to"]))
        elif action == "rename":
            await self.mpd.run("rename", name, self._playlist_name(data.get("new_name")))
        elif action == "delete":
            await self.mpd.run("rm", name)
        else:
            raise ValueError("Unbekannte Aktion")

    async def queue_add(self, uris: List[str], mode: str = "append") -> None:
        self._check_scanning(uris)
        if self.ripper.running and any(u.startswith("cdda://") for u in uris):
            raise ValueError("Die CD wird gerade gerippt – Abspielen geht danach wieder")
        lines = [build("add", u) for u in uris]
        if mode == "play":
            await self.take_over("mpd")
            await self.mpd.batch(["clear"] + lines + ["play 0"])
        else:
            await self.mpd.batch(lines)

    async def queue(self) -> List[Dict[str, Any]]:
        items = []
        for s in to_objects(await self.mpd.run("playlistinfo"), starts=("file",)):
            uri = s.get("file", "")
            kind = _media_kind(uri)
            title = s.get("Title") or s.get("Name") or os.path.splitext(os.path.basename(uri))[0]
            if kind == "radio":
                title = self.station(uri).get("name") or s.get("Name") or uri
            elif kind == "cd":
                n = uri.rsplit("/", 1)[-1]
                track = next((t for t in self.cd.get("tracks", []) if str(t["number"]) == n), {})
                title = track.get("title") or f"CD-Titel {n}"
            items.append({"id": int(s.get("Id", 0)), "pos": int(s.get("Pos", 0)), "uri": uri, "kind": kind,
                          "title": title, "artist": s.get("Artist", ""), "album": s.get("Album", ""),
                          "duration": float(s.get("duration") or s.get("Time") or 0)})
        return items

    def remember_station(self, st: Dict[str, Any]) -> None:
        """Sendername/Logo dauerhaft merken - MPD speichert bei Streams nur die Adresse."""
        url = st.get("url", "")
        if not url.startswith(("http://", "https://")):
            return
        info = {k: st.get(k) for k in ("uuid", "name", "favicon", "country", "url")}
        self.stations[url] = info
        self.cache.set("station:" + url, info, 5 * 365 * 86400)

    def station(self, url: str) -> Dict[str, Any]:
        if url in self.stations:
            return self.stations[url]
        fav = next((f for f in self.settings.get("radio_favorites") if f.get("url") == url), None)
        info = fav or self.cache.get("station:" + url) or {}
        if info:
            self.stations[url] = info
        return info

    async def play_station(self, st: Dict[str, Any]) -> None:
        url = st.get("url", "")
        if not url.startswith(("http://", "https://")):
            raise ValueError("Ungueltige Stream-URL")
        self.remember_station(st)
        await self.queue_add([url], "play")
        self._spawn(self.radio.click(st.get("uuid", "")))

    # ------------------------------------------------------------ Bibliothek
    async def browse(self, path: str) -> List[Dict[str, Any]]:
        out = []
        for e in await self.mpd.objects("lsinfo", path) if path else await self.mpd.objects("lsinfo"):
            if "directory" in e:
                d = e["directory"]
                out.append({"type": "dir", "uri": d, "name": self._dir_label(d)})
            elif "file" in e:
                out.append(self._song(e))
        return out

    def _dir_label(self, d: str) -> str:
        base = d.rsplit("/", 1)[-1]
        if "/" not in d:
            for m in self.media:
                if m["dir"] == base:
                    return m["label"]
            for s in self.settings.get("shares"):
                if shares_mod.mount_name(s) == base:
                    return s["name"] + (" (Netzwerk – wird eingelesen …)" if base in self.shares.scanning
                                        else " (Netzwerk)")
        return base

    @staticmethod
    def _song(e: Dict[str, str]) -> Dict[str, Any]:
        uri = e.get("file", "")
        return {"type": "song", "uri": uri, "name": e.get("Title") or os.path.splitext(os.path.basename(uri))[0],
                "artist": e.get("Artist", ""), "album": e.get("Album", ""),
                "track": e.get("Track", ""), "duration": float(e.get("duration") or e.get("Time") or 0)}

    async def albums(self) -> List[Dict[str, str]]:
        pairs = await self.mpd.run("list", "album", "group", "albumartist")
        result, artist = [], ""
        for k, v in pairs:
            if k == "AlbumArtist":
                artist = v
            elif k == "Album" and v:
                result.append({"album": v, "artist": artist})
        result.sort(key=lambda a: (a["artist"].lower(), a["album"].lower()))
        return result

    async def album_tracks(self, album: str, artist: str) -> List[Dict[str, Any]]:
        args = ["album", album] + (["albumartist", artist] if artist else [])
        songs = [self._song(e) for e in to_objects(await self.mpd.run("find", *args), starts=("file",)) if "file" in e]

        def key(s):
            try:
                return int(str(s["track"]).split("/")[0])
            except ValueError:
                return 999
        return sorted(songs, key=key)

    async def search(self, q: str) -> List[Dict[str, Any]]:
        found = to_objects(await self.mpd.run("search", "any", q), starts=("file",))
        return [self._song(e) for e in found if "file" in e][:300]

    async def art_for_file(self, uri: str):
        data = await self.mpd.picture(uri)
        if data:
            return data
        info = await self.mpd.dict("lsinfo", uri)
        return await self.mb.cover(artist=info.get("AlbumArtist") or info.get("Artist", ""),
                                   album=info.get("Album", ""), mbid=info.get("MUSICBRAINZ_ALBUMID", ""))

    async def art_for_album(self, album: str, artist: str):
        args = ["album", album] + (["albumartist", artist] if artist else [])
        first = to_objects(await self.mpd.run("find", *args, "window", "0:1"), starts=("file",))
        if first and "file" in first[0]:
            return await self.art_for_file(first[0]["file"])
        return await self.mb.cover(artist=artist, album=album)

    # ------------------------------------------------------------ Datentraeger
    def _scan_mounts(self) -> List[Dict[str, str]]:
        labels: Dict[str, str] = {}
        by_label = Path("/dev/disk/by-label")
        if by_label.is_dir():
            for link in by_label.iterdir():
                try:
                    raw = re.sub(rb"\\x([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]),
                                 os.fsencode(link.name))
                    labels[os.path.realpath(str(link))] = raw.decode("utf-8", "replace")
                except OSError:
                    continue
        mounts = []
        prefix = str(MEDIA_ROOT).rstrip("/") + "/"
        try:
            with open("/proc/mounts", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    dev, mnt, fstype = line.split()[:3]
                    mnt = mnt.replace("\\040", " ")
                    # Abgezogenes Geraet: Mount kann noch haengen, solange MPD die Datei offen hat
                    if mnt.startswith(prefix) and "/" not in mnt[len(prefix):] and os.path.exists(dev):
                        d = mnt[len(prefix):]
                        kind = "sd" if "mmcblk" in dev else "usb"
                        mounts.append({"dir": d, "device": dev, "kind": kind, "fstype": fstype,
                                       "label": labels.get(os.path.realpath(dev)) or
                                       ("SD-Karte" if kind == "sd" else "USB-Laufwerk") + f" ({d[:8]})"})
        except OSError:
            pass
        return sorted(mounts, key=lambda m: m["dir"])

    async def _mount_loop(self) -> None:
        while True:
            mounts = await asyncio.to_thread(self._scan_mounts)
            if mounts != self.media:
                removed = {m["dir"] for m in self.media} - {m["dir"] for m in mounts}
                self.media = mounts
                try:
                    if removed:
                        await self._drop_media(removed)
                    await self.mpd.run("update")
                except (ConnectionError, MPDError):
                    pass
                self.broadcast({"type": "library"})
                self.push()
            await asyncio.sleep(3)

    async def _drop_media(self, dirs: Set[str]) -> None:
        """Datentraeger wurde entfernt: Wiedergabe davon stoppen und Titel aus der Liste nehmen.

        Ohne das spielt MPD den Puffer weiter, haelt die Datei offen und
        systemd kann den Mount nicht abbauen.
        """
        prefixes = tuple(d + "/" for d in dirs)
        song = await self.mpd.dict("currentsong")
        if song.get("file", "").startswith(prefixes):
            await self.mpd.run("stop")
            log.info("Datentraeger entfernt, Wiedergabe gestoppt: %s", ", ".join(sorted(dirs)))
        items = await self.queue()
        await self.mpd.batch([f"deleteid {i['id']}" for i in items if i["uri"].startswith(prefixes)])

    # ------------------------------------------------------------ CD
    def cd_public(self) -> Dict[str, Any]:
        return {k: v for k, v in self.cd.items() if k not in ("toc", "art_path")}

    async def _cd_loop(self) -> None:
        last: Any = "init"
        while True:
            status = await asyncio.to_thread(cdrom.drive_status, CD_DEVICE)
            if status != last:
                # Beim Start der App liegt die CD schon im Laufwerk: kein Autoplay, nur beim Einlegen
                await self._cd_changed(status, inserted=last != "init")
                last = status
            await asyncio.sleep(2)

    async def _cd_changed(self, status: Optional[int], inserted: bool = True) -> None:
        if status == cdrom.CDS_DISC_OK:
            try:
                toc = await asyncio.to_thread(cdrom.read_toc, CD_DEVICE)
            except OSError as exc:
                log.warning("TOC nicht lesbar: %s", exc)
                toc = None
            if toc:
                self.cd = {"available": True, "status": "disc", "present": True, "audio": True,
                           "disc_id": toc["disc_id"], "toc": toc["toc"], "tracks": toc["tracks"],
                           "album": "Audio-CD", "artist": "", "art": None, "lookup": "pending"}
                self.push()
                self._spawn(self._cd_lookup(toc["disc_id"]))
                if inserted and self.settings.get("cd_autoplay"):
                    await self.cd_play(1)
            else:
                self.cd = {"available": True, "status": "disc", "present": True, "audio": False}
        else:
            had_disc = self.cd.get("present")
            # Erst die Anzeige: MPD kann nach dem Auswerfen noch lange versuchen, die CD zu lesen,
            # und reagiert in der Zeit kaum auf Befehle.
            self.cd = {"available": status is not None, "status": cdrom.STATUS_NAMES.get(status, "none"),
                       "present": False}
            if had_disc:
                self._spawn(self._remove_cd_from_queue())
        self.push()

    async def _remove_cd_from_queue(self) -> None:
        try:
            song = await self.mpd.dict("currentsong")
            if song.get("file", "").startswith("cdda://"):
                await self.mpd.run("stop")
            items = await self.queue()
            await self.mpd.batch([f"deleteid {i['id']}" for i in items if i["kind"] == "cd"])
        except (ConnectionError, MPDError):
            pass
        self.push()

    async def _cd_lookup(self, disc_id: str) -> None:
        if not self.settings.get("metadata_online"):
            self.cd["lookup"] = "off"
            self.push()
            return
        tracks = self.cd.get("tracks", [])
        attempt = 0
        while True:
            attempt += 1
            try:
                info = await self.mb.lookup_disc(disc_id, self.cd.get("toc", ""), [t["duration"] for t in tracks])
                break
            except Unavailable as exc:
                if self.cd.get("disc_id") != disc_id:
                    return
                if self.cd.get("lookup") != "offline":
                    log.info("CD-Abfrage bei MusicBrainz verschoben: %s - neuer Versuch jede Minute", exc)
                    self.cd["lookup"] = "offline"
                    self.push()
            # MusicBrainz pausiert nach Drosselung 5 Minuten: solange die CD drin ist, regelmaessig nachfragen
            # (die erste Viertelstunde jede Minute, danach alle 5 Minuten - z. B. bei laengerem Netzausfall)
            await asyncio.sleep(60 if attempt < 16 else 300)
            if self.cd.get("disc_id") != disc_id:
                return
        if self.cd.get("disc_id") != disc_id:
            return
        if not info:
            self.cd["lookup"] = "unknown"
            # Formular, mit dem man die CD bei MusicBrainz eintragen kann
            self.cd["submit_url"] = ("https://musicbrainz.org/cdtoc/attach?id=" + urlquote(disc_id)
                                     + f"&tracks={len(tracks)}&toc=" + self.cd.get("toc", "").replace(" ", "+"))
            self.push()
            return
        titles = {t["number"]: t for t in info["tracks"]}
        for i, t in enumerate(self.cd["tracks"]):
            meta = titles.get(i + 1) or {}
            t["title"], t["artist"] = meta.get("title", ""), meta.get("artist", "")
        self.cd.update({"album": info["album"], "artist": info["artist"], "date": info["date"],
                        "mbid": info["mbid"], "lookup": "found"})
        self.push()
        self.broadcast({"type": "queue"})
        path = await self.mb.cover(mbid=info["mbid"], group=info["group"])
        if path and self.cd.get("disc_id") == disc_id:
            self.cd["art"] = f"/api/art/cd?d={urlquote(disc_id)}"
            self.cd["art_path"] = str(path)
            self.push()

    async def cd_play(self, start: int = 1) -> None:
        tracks = self.cd.get("tracks") or []
        if not tracks:
            raise ValueError("Keine Audio-CD eingelegt")
        if self.ripper.running:
            raise ValueError("Die CD wird gerade gerippt – Abspielen geht danach wieder")
        await self.take_over("mpd")
        pos = max(0, next((i for i, t in enumerate(tracks) if t["number"] == start), 0))
        await self.mpd.batch(["clear"] + [build("add", t["uri"]) for t in tracks] + [f"play {pos}"])

    async def cd_eject(self) -> None:
        if self.ripper.running:
            raise ValueError("Die CD wird gerade gerippt – bitte zuerst abbrechen")
        await self._remove_cd_from_queue()
        try:
            await asyncio.to_thread(cdrom.eject, CD_DEVICE)
        except OSError as exc:
            raise ValueError(exc.strerror or str(exc))

    # ------------------------------------------------------------ CD rippen
    def rip_targets(self) -> List[Dict[str, Any]]:
        """Interner Speicher und eingesteckte USB-/SD-Datentraeger mit freiem Platz."""
        out = []
        for tid, label, path in [("local", "Interner Speicher", MEDIA_ROOT / ripper_mod.LOCAL_DIR)] + \
                [(m["dir"], m["label"], MEDIA_ROOT / m["dir"]) for m in self.media if m["fstype"] in WRITABLE_FS]:
            try:
                free = ripper_mod.free_bytes(path)
            except OSError:
                continue
            out.append({"id": tid, "label": label, "free": free})
        return out

    def rip_info(self) -> Dict[str, Any]:
        return {"targets": self.rip_targets(), "job": self.ripper.public(),
                "need": ripper_mod.estimate_bytes(self.cd) if self.cd.get("tracks") else 0,
                "target": self.settings.get("rip_target"), "eject": self.settings.get("rip_eject")}

    async def rip_start(self, target_id: str, eject: bool) -> None:
        if not (self.cd.get("present") and self.cd.get("tracks")):
            raise ValueError("Keine Audio-CD eingelegt")
        if self.cd.get("lookup") == "pending":
            raise ValueError("Bitte kurz warten, bis die Titel von MusicBrainz geladen sind")
        target = next((t for t in self.rip_targets() if t["id"] == target_id), None)
        if not target:
            raise ValueError("Das gewählte Ziel ist nicht (mehr) verfügbar")
        kind = "local" if target_id == "local" else "usb"
        dest = ripper_mod.LOCAL_DIR if kind == "local" else target_id

        async def store(work: Path, folder: str) -> str:
            if kind == "local":
                return await asyncio.to_thread(ripper_mod.store_local, work, folder)
            res = await shares_mod.helper({"action": "store", "src": work.name, "dest": dest, "folder": folder},
                                          timeout=1800)
            if res.get("ok"):
                return f"{dest}/{res['folder']}"
            # Gerippte Dateien nicht verwerfen, sonst waeren bis zu 20 min Rippen umsonst gewesen
            log.warning("Speichern auf %s fehlgeschlagen: %s - lege im internen Speicher ab", dest, res.get("error"))
            path = await asyncio.to_thread(ripper_mod.store_local, work, folder)
            if self.ripper.job:
                self.ripper.job.update(target="Interner Speicher",
                                       warning=f"Speichern auf „{target['label']}“ fehlgeschlagen ({res.get('error')}) "
                                               "– das Album liegt stattdessen im internen Speicher.")
            return path

        async def done(job: Dict[str, Any]) -> None:
            if job.get("state") != "done":
                return
            try:
                # Interpreten-Ordner statt Album-Ordner: MPD liest keinen Pfad ein, dessen Elternordner es
                # noch nicht kennt ("No such directory") - bei einem neuen Interpreten waere das der Fall
                await self.mpd.run("update", "/".join(job["path"].split("/")[:2]))
            except (ConnectionError, MPDError):
                pass
            self.broadcast({"type": "library"})
            if self.settings.get("rip_eject") and self.cd.get("disc_id") == job.get("disc_id"):
                # nicht cd_eject(): der Ripper gilt in diesem Moment noch als laufend
                try:
                    await asyncio.to_thread(cdrom.eject, CD_DEVICE)
                except OSError as exc:
                    log.warning("Auswerfen nach dem Rippen fehlgeschlagen: %s", exc.strerror or exc)

        self.settings.update({"rip_target": target_id, "rip_eject": bool(eject)})
        # Abspielen und Rippen gleichzeitig wuerde das Laufwerk staendig hin- und herspringen lassen
        await self._remove_cd_from_queue()
        self.ripper.start(self.cd, {"kind": kind, "dir": dest, "label": target["label"]}, store, done)

    async def rip_cancel(self) -> None:
        await self.ripper.cancel()

    # ------------------------------------------------------------ Einstellungen
    async def update_settings(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        # Passwort und Freigaben haben eigene Wege (Pruefung, Passwort-Behandlung)
        forbidden = set(changes) & {"auth_hash", "auth_scope", "shares", "upnp_uuid", "alarms"}
        if forbidden:
            raise ValueError("Diese Einstellung lässt sich hier nicht ändern: " + ", ".join(sorted(forbidden)))
        old_loudness = self.settings.get("loudness")
        changed = set(self.settings.update(changes))
        # Die dynamische Angleichung kennt MPD nur als Startoption -> Neustart wie beim Geraetewechsel
        restart_mpd = "loudness" in changed and "dynamic" in (old_loudness, self.settings.get("loudness"))
        if changed & {"output", "bitperfect", "speakers"} or restart_mpd:
            # MPD startet fuer das neue Geraet neu und stellt sich dann pausiert wieder her
            resume = self.source in ("mpd", "idle") and await self._is_playing()
            try:
                # Einen gemerkten Sender stellt MPD beim Start pausiert wieder her und versucht, darin zu
                # springen - so lange nimmt er keine Verbindung an (am Pi bis ueber 25 s)
                if _media_kind((await self.mpd.dict("currentsong")).get("file", "")) == "radio":
                    await self.mpd.run("stop")
            except (ConnectionError, MPDError):
                pass
            if changed & {"output", "bitperfect", "speakers"}:
                await self.apply_audio()
            else:
                await self.apply_audio(("mpd",))
            if resume:
                self._spawn(self._resume_mpd())
        else:
            if changed & {"device_name", "airplay_enabled"}:
                await self.apply_audio(("airplay",))
            if changed & {"device_name", "spotify_enabled", "spotify_bitrate"}:
                await self.apply_audio(("spotify",))
            if changed & {"device_name", "upnp_enabled"}:
                await self.apply_audio(("upnp",))
            if changed & {"device_name", "bluetooth_enabled"}:
                await self.apply_audio(("bluetooth",))
            if changed & {"device_name", "cec_enabled"}:
                await self.apply_audio(("cec",))
            if changed & {"loudness", "crossfade"}:
                await self._apply_playback(tries=1)
        if changed & {"weather_place", "metadata_online"}:
            self._spawn(self._weather_now())
        if "tv_enabled" in changed and self.settings.get("tv_enabled"):
            self.tv_launch += 1
        if changed:
            self.broadcast({"type": "settings"})
        self.push()
        return self.settings.public()

    async def _weather_now(self) -> None:
        if await self.weather.refresh():
            self.push()

    def tv_status(self) -> Dict[str, Any]:
        return {"enabled": self.settings.get("tv_enabled"), "launch": self.tv_launch}

    def tv_show(self) -> Dict[str, Any]:
        """Fernseh-Bildschirm (erneut) anzeigen, z. B. nachdem er von Hand geschlossen wurde."""
        if not self.settings.get("tv_enabled"):
            raise ValueError("Der „Läuft gerade“-Bildschirm ist in den Optionen ausgeschaltet")
        self.tv_launch += 1
        return self.tv_status()

    def services(self) -> List[Dict[str, Any]]:
        infos = [d.info() for d in self.daemons.values()]
        for info in infos:
            if info["name"] == "airplay":
                info["metadata"] = list(self.airplay.trace)
        return infos
