"""Liedtexte fuer den "Laeuft gerade"-Bildschirm.

Quellen in dieser Reihenfolge:
  * .lrc-Datei neben der Musikdatei (nur Bibliothek, funktioniert ohne Netz)
  * LRCLIB (lrclib.net): frei, ohne Schluessel, oft mit Zeitstempeln je Zeile

Ergebnis: {"kind": "synced", "lines": [{"t": Sekunden, "text": ...}]}, {"kind": "plain", "text": ...},
{"kind": "instrumental"} oder None. Treffer und "nicht gefunden" landen im Cache, Netzfehler nicht.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from .cache import Cache
from .config import VERSION, Settings
from .musicbrainz import strip_edition

log = logging.getLogger("klangstation.lyrics")

LRCLIB = "https://lrclib.net/api"
DAY = 86400

_STAMP = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")
_OFFSET = re.compile(r"\[offset:\s*([+-]?\d+)\]", re.I)
# Zusaetze, die Streamingdienste an Titel haengen ("Song - Remastered 2011", "Song (feat. X)")
_TITLE_EXTRA = re.compile(r"\s*(?:[\(\[](?:feat\.?|ft\.?|with)\s[^\)\]]*[\)\]]|\s-\s.*\b(?:remaster(?:ed)?|live|"
                          r"version|mix|edit|mono|stereo)\b.*)$", re.I)


def parse_lrc(text: str) -> Optional[Dict[str, Any]]:
    """LRC mit Zeitstempeln -> synced; ohne Zeitstempel -> plain."""
    offset = 0.0
    m = _OFFSET.search(text)
    if m:
        offset = int(m.group(1)) / 1000.0  # positiv = Text frueher zeigen
    lines: List[Dict[str, Any]] = []
    for raw in text.splitlines():
        stamps = _STAMP.findall(raw)
        if not stamps:
            continue
        words = _STAMP.sub("", raw).strip()
        for minutes, seconds in stamps:
            t = int(minutes) * 60 + float(seconds.replace(":", "."))
            lines.append({"t": round(max(0.0, t - offset), 2), "text": words})
    if lines:
        lines.sort(key=lambda line: line["t"])
        return {"kind": "synced", "lines": lines}
    plain = "\n".join(line for line in text.splitlines() if not re.match(r"^\s*\[[a-z]+:", line, re.I)).strip()
    return {"kind": "plain", "text": plain} if plain else None


def clean_title(title: str) -> str:
    previous = None
    while title and title != previous:
        previous, title = title, _TITLE_EXTRA.sub("", title).strip()
    return title or previous or ""


def _from_lrclib(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if item.get("instrumental"):
        return {"kind": "instrumental"}
    if item.get("syncedLyrics"):
        parsed = parse_lrc(item["syncedLyrics"])
        if parsed and parsed["kind"] == "synced":
            return parsed
    if item.get("plainLyrics"):
        return {"kind": "plain", "text": item["plainLyrics"].strip()}
    return None


class Unavailable(Exception):
    """LRCLIB voruebergehend nicht erreichbar - nicht als 'kein Text' cachen."""


class Lyrics:
    def __init__(self, settings: Settings, cache: Cache, media_root: Path):
        self.settings = settings
        self.cache = cache
        self.media_root = media_root
        self.http = httpx.AsyncClient(timeout=15, follow_redirects=True,
                                      headers={"User-Agent": f"Klangstation/{VERSION} (self-hosted)"})
        self._inflight: Dict[str, "asyncio.Future[Any]"] = {}
        self._blocked_until = 0.0

    async def close(self) -> None:
        await self.http.aclose()

    def _sidecar(self, uri: str) -> Optional[Dict[str, Any]]:
        root = self.media_root.resolve()
        path = (root / uri).with_suffix(".lrc").resolve()
        if root not in path.parents:
            return None
        try:
            return parse_lrc(path.read_text(encoding="utf-8-sig", errors="replace"))
        except OSError:
            return None

    async def find(self, *, artist: str, title: str, album: str = "", duration: float = 0,
                   uri: str = "") -> Optional[Dict[str, Any]]:
        if uri:
            local = await asyncio.to_thread(self._sidecar, uri)
            if local:
                return dict(local, source="Datei")
        if not (artist and title) or not self.settings.get("metadata_online"):
            return None
        key = "lrc:" + "|".join([artist.lower(), title.lower(), album.lower(), str(round(duration))])
        found, value = self.cache.lookup(key)
        if found:
            return value
        if time.time() < self._blocked_until:
            return None
        if key in self._inflight:
            return await asyncio.shield(self._inflight[key])
        fut = asyncio.get_running_loop().create_future()
        self._inflight[key] = fut
        try:
            result = await self._lookup(artist, title, album, duration)
            if result:
                result["source"] = "LRCLIB"
            self.cache.set(key, result, 90 * DAY if result else 7 * DAY)
            fut.set_result(result)
            return result
        except (Unavailable, ValueError) as exc:  # ValueError: kaputte JSON-Antwort
            # Kurz pausieren, damit bei jedem Titelwechsel nicht erneut ins Leere gefragt wird
            self._blocked_until = time.time() + 120
            log.info("Kein Liedtext fuer %s - %s: %s", artist, title, exc)
            fut.set_result(None)
            return None
        finally:
            self._inflight.pop(key, None)

    async def _request(self, path: str, params: Dict[str, str]) -> Any:
        log.info("LRCLIB-Anfrage: %s %s", path, params)
        try:
            resp = await self.http.get(LRCLIB + path, params=params)
        except httpx.HTTPError as exc:
            raise Unavailable(f"LRCLIB nicht erreichbar: {exc}")
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            raise Unavailable(f"LRCLIB antwortet mit HTTP {resp.status_code}")
        return resp.json()

    async def _lookup(self, artist: str, title: str, album: str, duration: float) -> Optional[Dict[str, Any]]:
        # Erst die genaue Abfrage (LRCLIB gleicht die Laenge auf +-2 s ab), dann die Suche
        if duration > 0 and album:
            item = await self._request("/get", {"artist_name": artist, "track_name": title,
                                                "album_name": strip_edition(album), "duration": str(round(duration))})
            if item:
                result = _from_lrclib(item)
                if result:
                    return result
        best: Optional[Dict[str, Any]] = None
        best_score = None
        for name in dict.fromkeys((title, clean_title(title))):
            items = await self._request("/search", {"artist_name": artist, "track_name": name}) or []
            for item in items:
                result = _from_lrclib(item)
                if not result:
                    continue
                diff = abs((item.get("duration") or 0) - duration) if duration > 0 else 0
                if duration > 0 and diff > 4:
                    continue  # andere Aufnahme (Live, Remix) - der Text liefe nicht mit
                score = (diff, 0 if result["kind"] == "synced" else 1)
                if best_score is None or score < best_score:
                    best, best_score = result, score
            if best:
                break
        return best
