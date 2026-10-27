"""Schlummer-Timer und Wecker.

Schlummer-Timer: nach einer Zeit oder am Ende des Titels leise ausblenden und anhalten.
Wecker: zur eingestellten Zeit einen Sender oder eine Wiedergabeliste starten, langsam lauter werden und
optional nach einer Weile wieder ausschalten. Laeuft schon Musik, bleibt sie ungestoert.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .mpd import MPDError, build

if TYPE_CHECKING:
    from .core import Core

log = logging.getLogger("klangstation.timers")

FADE_OUT = 30        # Sekunden Ausblenden vor dem Anhalten
RAMP_UP = 120        # Sekunden, bis der Wecker die Ziellautstaerke erreicht
CHECK_AFTER = 20     # Sekunden nach dem Wecken: laeuft nichts, Rueckfall auf die Bibliothek
VOLUME_SOURCES = ("mpd", "idle", "upnp", "bluetooth")  # Quellen, deren Lautstaerke Klangstation stellt
DAYS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
MAX_ALARMS = 10


def clean_alarm(data: Dict[str, Any], old: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Prueft einen Wecker aus der Oberflaeche und gibt ihn in gespeicherter Form zurueck."""
    hhmm = str(data.get("time", ""))
    try:
        hour, minute = (int(x) for x in hhmm.split(":"))
    except ValueError:
        raise ValueError("Ungültige Weckzeit")
    if not (0 <= hour < 24 and 0 <= minute < 60):
        raise ValueError("Ungültige Weckzeit")
    days = sorted({int(d) for d in data.get("days") or [] if str(d).isdigit() and 0 <= int(d) < 7})
    target = data.get("target") or {}
    if target.get("kind") == "station":
        url = str(target.get("url", ""))
        if not url.startswith(("http://", "https://")):
            raise ValueError("Ungültiger Sender")
        target = {"kind": "station", "url": url, "name": str(target.get("name", ""))[:120],
                  "uuid": str(target.get("uuid", ""))[:64], "favicon": str(target.get("favicon") or "")[:500]}
    elif target.get("kind") == "playlist":
        name = str(target.get("name", "")).strip()
        if not name or len(name) > 80:
            raise ValueError("Ungültige Wiedergabeliste")
        target = {"kind": "playlist", "name": name}
    elif target.get("kind") == "library":
        target = {"kind": "library"}
    else:
        raise ValueError("Bitte wähle, was der Wecker spielen soll")
    volume = int(data.get("volume", 30))
    stop_after = int(data.get("stop_after", 60))
    if stop_after not in (0, 15, 30, 60, 120):
        raise ValueError("Ungültige Ausschaltzeit")
    return {
        "id": (old or {}).get("id") or secrets.token_hex(4),
        "enabled": bool(data.get("enabled", True)),
        "time": f"{hour:02d}:{minute:02d}",
        "days": days,
        "target": target,
        "volume": max(1, min(100, volume)),
        "stop_after": stop_after,
    }


def next_ring(alarm: Dict[str, Any], now: float) -> Optional[float]:
    """Zeitpunkt, zu dem der Wecker als naechstes klingelt (lokale Zeit), oder None."""
    if not alarm.get("enabled"):
        return None
    hour, minute = (int(x) for x in alarm["time"].split(":"))
    lt = time.localtime(now)
    for offset in range(8):
        # mktime normalisiert den Tag ueber Monatsgrenzen und beachtet die Sommerzeit
        ts = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + offset, hour, minute, 0, 0, 0, -1))
        if ts <= now - 59:  # in der laufenden Minute gilt der Wecker noch als faellig
            continue
        if not alarm["days"] or time.localtime(ts).tm_wday in alarm["days"]:
            return ts
    return None


class Timers:
    def __init__(self, core: "Core"):
        self.core = core
        # {"until": ts, "mode": "time"|"track", "track": Kennung, "minutes": n}
        self.sleep: Optional[Dict[str, Any]] = None
        self.ringing: Optional[Dict[str, Any]] = None   # {"id", "label", "at"} solange der Wecker laeuft
        self._fired: Dict[str, float] = {}               # "id@ts" -> wann ausgeloest
        self._fade: Optional[Dict[str, Any]] = None      # laufendes Ausblenden: {"start", "last"}
        self._ramp: Optional[asyncio.Task] = None

    # ------------------------------------------------------------ Zustand
    def public(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {"sleep": None, "next_alarm": None, "ringing": self.ringing, "ts": time.time()}
        if self.sleep:
            out["sleep"] = {"mode": self.sleep["mode"], "until": self.sleep.get("until"),
                            "minutes": self.sleep.get("minutes", 0)}
        now = time.time()
        best = None
        for alarm in self.alarms():
            ts = next_ring(alarm, now)
            if ts and (best is None or ts < best[0]):
                best = (ts, alarm)
        if best:
            ts, alarm = best
            out["next_alarm"] = {"id": alarm["id"], "at": ts, "time": alarm["time"],
                                 "day": DAYS[time.localtime(ts).tm_wday], "label": self.label(alarm)}
        return out

    def alarms(self) -> List[Dict[str, Any]]:
        return list(self.core.settings.get("alarms"))

    @staticmethod
    def label(alarm: Dict[str, Any]) -> str:
        t = alarm["target"]
        if t["kind"] == "station":
            return t.get("name") or "Webradio"
        if t["kind"] == "playlist":
            return t["name"]
        return "Bibliothek (Zufall)"

    # ------------------------------------------------------------ Wecker verwalten
    def alarm_action(self, action: str, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        alarms = self.alarms()
        idx = next((i for i, a in enumerate(alarms) if a["id"] == data.get("id")), None)
        if action == "save":
            if idx is None:
                if len(alarms) >= MAX_ALARMS:
                    raise ValueError(f"Höchstens {MAX_ALARMS} Wecker")
                alarms.append(clean_alarm(data))
            else:
                alarms[idx] = clean_alarm(data, alarms[idx])
        elif idx is None:
            raise ValueError("Diesen Wecker gibt es nicht (mehr)")
        elif action == "toggle":
            alarms[idx] = dict(alarms[idx], enabled=bool(data.get("enabled")))
        elif action == "remove":
            alarms.pop(idx)
        elif action == "test":
            self.core._spawn(self.ring(alarms[idx], test=True))
            return alarms
        else:
            raise ValueError("Unbekannte Aktion")
        self.core.settings.update({"alarms": alarms})
        self.core.push()
        return alarms

    # ------------------------------------------------------------ Schlummer-Timer
    async def set_sleep(self, minutes: Any) -> None:
        await self._cancel_sleep()
        if minutes in (0, None, "off"):
            log.info("Schlummer-Timer aus")
        elif minutes == "track":
            state = await self.core.state()
            now = state["now"]
            if not await self.core._is_playing():
                raise ValueError("Es läuft gerade nichts")
            if now.get("kind") == "radio" or not now.get("duration"):
                raise ValueError("Dieser Titel hat kein absehbares Ende – wähle eine Zeit")
            self.sleep = {"mode": "track", "track": self._track_key(now),
                          "until": time.time() + max(0, now["duration"] - now.get("elapsed", 0))}
            if self.core.source in ("mpd", "idle"):
                await self.core.mpd.run("single", "oneshot")  # MPD haelt nach dem Titel selbst an
            log.info("Schlummer-Timer: nach diesem Titel")
        else:
            minutes = int(minutes)
            if not 1 <= minutes <= 240:
                raise ValueError("Ungültige Zeit")
            self.sleep = {"mode": "time", "minutes": minutes, "until": time.time() + minutes * 60}
            log.info("Schlummer-Timer: %s min", minutes)
        self.core.push()

    async def _cancel_sleep(self) -> None:
        if self.sleep and self.sleep["mode"] == "track":
            await self._reset_single()
        await self._end_fade(restore=True)
        self.sleep = None

    async def _reset_single(self) -> None:
        # MPD laesst "single oneshot" nach dem Anhalten stehen - sonst hielte auch der naechste Titel an
        try:
            if (await self.core.mpd.dict("status")).get("single") == "oneshot":
                await self.core.mpd.run("single", "0")
        except (ConnectionError, MPDError):
            pass

    @staticmethod
    def _track_key(now: Dict[str, Any]) -> str:
        return "|".join(str(now.get(k) or "") for k in ("kind", "uri", "title", "artist"))

    async def _sleep_tick(self) -> None:
        sl = self.sleep
        if not sl:
            return
        playing = await self.core._is_playing()
        if sl["mode"] == "track":
            now = (await self.core.state())["now"]
            if not playing or self._track_key(now) != sl["track"]:
                # Titel ist zu Ende (MPD haelt per "single oneshot" selbst an) oder es wurde umgeschaltet
                if playing:
                    await self._stop_playback("Schlummer-Timer: Titel zu Ende")
                else:
                    log.info("Schlummer-Timer: Titel zu Ende")
                await self._reset_single()
                await self._end_fade(restore=True)
                self.sleep = None
                self.core.push()
            elif now.get("duration"):
                sl["until"] = time.time() + max(0, now["duration"] - now.get("elapsed", 0))
            return
        left = sl["until"] - time.time()
        if left <= 0:
            if playing:
                await self._stop_playback("Schlummer-Timer abgelaufen")
            await self._end_fade(restore=True)
            self.sleep = None
            self.core.push()
        elif left <= FADE_OUT and playing:
            await self._fade_step(left / FADE_OUT)

    async def _fade_step(self, factor: float) -> None:
        if self.core.source not in VOLUME_SOURCES:
            return
        state = await self.core.state()
        vol = state.get("volume", -1)
        if vol < 0:
            return
        if self._fade is None:
            self._fade = {"start": vol, "last": vol}
        elif vol != self._fade["last"]:
            # Jemand hat die Lautstaerke von Hand geaendert: nicht weiter hineinregeln
            self._fade["manual"] = True
            return
        if self._fade.get("manual"):
            return
        target = max(0, round(self._fade["start"] * factor))
        if target != vol:
            try:
                await self.core.set_volume(target)
                self._fade["last"] = target
            except (ValueError, ConnectionError, MPDError):
                self._fade["manual"] = True

    async def _end_fade(self, restore: bool) -> None:
        fade, self._fade = self._fade, None
        if not (fade and restore and not fade.get("manual")):
            return
        await asyncio.sleep(0.5)  # erst anhalten, dann zurueckdrehen - sonst ist es kurz laut
        try:
            await self.core.set_volume(fade["start"])
        except (ValueError, ConnectionError, MPDError):
            pass

    async def _stop_playback(self, why: str) -> None:
        log.info(why)
        src = self.core.source
        try:
            if src in ("mpd", "idle"):
                song = await self.core.mpd.dict("currentsong")
                # Webradio laesst sich nicht sinnvoll pausieren (spielt danach den alten Puffer)
                await self.core.player("stop" if song.get("file", "").startswith(("http://", "https://")) else "pause")
            elif src in ("airplay", "spotify"):
                await self.core.player("stop")  # beendet die Sitzung des Handys
            else:
                await self.core.player("pause")
        except (ValueError, ConnectionError, MPDError) as exc:
            log.info("Anhalten fehlgeschlagen: %s", exc)
        self.ringing = None

    # ------------------------------------------------------------ Wecker
    async def _alarm_tick(self) -> None:
        now = time.time()
        for alarm in self.alarms():
            ts = next_ring(alarm, now)
            if ts is None or ts > now:
                continue
            key = f"{alarm['id']}@{int(ts)}"
            if key in self._fired:
                continue
            self._fired[key] = now
            if not alarm["days"]:
                # Einmaliger Wecker: danach aus
                alarms = [dict(a, enabled=False) if a["id"] == alarm["id"] else a for a in self.alarms()]
                self.core.settings.update({"alarms": alarms})
            self.core._spawn(self.ring(alarm))
        for key, at in list(self._fired.items()):
            if now - at > 3600:
                del self._fired[key]

    async def ring(self, alarm: Dict[str, Any], test: bool = False) -> None:
        label = self.label(alarm)
        if not test and await self.core._is_playing():
            log.info("Wecker %s: es laeuft schon Musik, lasse sie weiterlaufen", alarm["time"])
            return
        log.info("Wecker %s%s: %s, Lautstaerke %s", alarm["time"], " (Test)" if test else "", label, alarm["volume"])
        if self._ramp:
            self._ramp.cancel()
        start_vol = max(1, round(alarm["volume"] * 0.15))
        try:
            await self.core.take_over("mpd")
            await self._setvol(start_vol)
            await self._start_target(alarm["target"])
        except (ValueError, ConnectionError, MPDError) as exc:
            log.warning("Wecker: %s laesst sich nicht abspielen (%s) - spiele die Bibliothek", label, exc)
            await self._fallback()
        self.ringing = {"id": alarm["id"], "label": label, "at": time.time()}
        self.core.push()
        if alarm["stop_after"] and not test:
            await self.set_sleep(alarm["stop_after"])
        self._ramp = asyncio.current_task()
        try:
            await self._ramp_up(start_vol, alarm["volume"])
        finally:
            self._ramp = None

    async def _setvol(self, volume: int) -> bool:
        try:
            await self.core.mpd.run("setvol", volume)
            return True
        except MPDError:
            return False  # z. B. Bit-perfekt ohne Mixer: Lautstaerke nur am Verstaerker

    async def _start_target(self, target: Dict[str, Any]) -> None:
        if target["kind"] == "station":
            await self.core.play_station(dict(target))
        elif target["kind"] == "playlist":
            await self.core.playlist_action("play", {"name": target["name"]})
        else:
            await self._library_shuffle()

    async def _library_shuffle(self) -> None:
        await self.core.take_over("mpd")
        await self.core.mpd.batch(["clear", build("add", ""), "shuffle", "play 0"])

    async def _fallback(self) -> None:
        try:
            await self._library_shuffle()
        except (ValueError, ConnectionError, MPDError) as exc:
            log.warning("Wecker: auch die Bibliothek laesst sich nicht abspielen: %s", exc)

    async def _ramp_up(self, start: int, target: int) -> None:
        mpd = self.core.mpd
        began = time.time()
        last = start
        checked = False
        while True:
            await asyncio.sleep(2)
            elapsed = time.time() - began
            try:
                status = await mpd.dict("status")
            except (ConnectionError, MPDError):
                continue
            if not checked and self.core.source in ("mpd", "idle"):
                # Sender nicht erreichbar: MPD meldet den Fehler erst nach dem Start und steht dann auf "stop";
                # oder er verbindet, liefert aber nichts (Position bleibt stehen)
                failed = status.get("state") == "stop" and status.get("error")
                silent = elapsed >= CHECK_AFTER and float(status.get("elapsed", 0) or 0) < 3
                if failed or silent:
                    checked = True
                    log.warning("Wecker: %s - spiele die Bibliothek", status.get("error") or "keine Wiedergabe")
                    await self._fallback()
                    continue
                checked = elapsed >= CHECK_AFTER
            if self.core.source not in ("mpd", "idle") or status.get("state") == "stop":
                self.ringing = None
                self.core.push()
                return
            vol = int(status.get("volume", -1))
            if vol >= 0 and vol != last:
                return  # von Hand verstellt
            if last >= target:
                return
            last = min(target, round(start + (target - start) * min(1.0, elapsed / RAMP_UP)))
            if not await self._setvol(last):
                return

    # ------------------------------------------------------------ Schleife
    async def loop(self) -> None:
        while True:
            await asyncio.sleep(1)
            await self._alarm_tick()
            await self._sleep_tick()
            if self.ringing and time.time() - self.ringing["at"] > 30 and not await self.core._is_playing():
                self.ringing = None
                self.core.push()
