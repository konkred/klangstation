"""Liest die Metadaten-Pipe von shairport-sync (Titel, Interpret, Album, Cover, Position)."""
from __future__ import annotations

import asyncio
import base64
import binascii
import collections
import logging
import os
import re
import stat
import time
from pathlib import Path
from typing import Awaitable, Callable, Dict, Optional

log = logging.getLogger("klangstation.airplay")

_ITEM = re.compile(
    rb"<item><type>([0-9a-f]{8})</type><code>([0-9a-f]{8})</code><length>(\d+)</length>"
    rb"(?:\s*<data encoding=\"base64\">\s*(.*?)</data>)?\s*</item>", re.S)

_FIELDS = {("core", "minm"): "title", ("core", "asar"): "artist", ("core", "asal"): "album"}
# Fuer die Diagnose mitprotokollierte shairport-Codes (Titelwechsel, Bilder, Sitzungsende)
_TRACE_CODES = {"mdst", "mden", "pcst", "pcen", "PICT", "pbeg", "pend", "pfls", "prsm", "prgr", "phb0"}
_SUFFIX = re.compile(r"\s+[•·]\s+[^•·]*video[^•·]*$", re.I)


def _image_complete(data: bytes) -> bool:
    """JPEG muss mit EOI enden, PNG einen IEND-Block haben (abschliessende Nullen zaehlen nicht)."""
    if data[:3] == b"\xff\xd8\xff":
        return data.rstrip(b"\x00").endswith(b"\xff\xd9")
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return b"IEND" in data[-64:]
    return True


def _code(hexstr: bytes) -> str:
    return bytes.fromhex(hexstr.decode()).decode("latin-1")


class MetadataReader:
    def __init__(self, pipe: Path, on_update: Callable[[Dict], Awaitable[None]]):
        self.pipe = pipe
        self.on_update = on_update
        self.meta: Dict = {}
        self.cover: bytes = b""
        self.cover_version = 0
        # RTP-Zeitstempel ordnen Bild und Titeldaten demselben Titel zu (mdst/pcst)
        self.meta_rtp: Optional[str] = None
        self.pic_rtp: Optional[str] = None
        self.cover_rtp: Optional[str] = None
        self.trace: "collections.deque[str]" = collections.deque(maxlen=40)
        # Zwischen mdst und mden kommen Titel, Interpret und Album einzeln - erst danach anzeigen,
        # sonst steht kurz das neue Album neben dem alten Titel
        self._in_block = False

    def ensure_pipe(self) -> None:
        self.pipe.parent.mkdir(parents=True, exist_ok=True)
        if self.pipe.exists() and not stat.S_ISFIFO(self.pipe.stat().st_mode):
            self.pipe.unlink()
        if not self.pipe.exists():
            os.mkfifo(str(self.pipe), 0o660)

    def reset(self) -> None:
        self.meta = {}
        self.cover = b""
        self.meta_rtp = self.pic_rtp = self.cover_rtp = None

    @property
    def cover_current(self) -> bool:
        """Gehoert das zuletzt empfangene Bild zum aktuellen Titel?"""
        if not self.cover:
            return False
        return not self.meta_rtp or not self.cover_rtp or self.cover_rtp == self.meta_rtp

    def position(self) -> float:
        """Aktuelle Position; shairport-sync meldet sie nur bei Start und Spulen."""
        elapsed = self.meta.get("elapsed", 0.0)
        if not self.meta.get("paused") and self.meta.get("at"):
            elapsed += time.time() - self.meta["at"]
        duration = self.meta.get("duration") or 0
        return min(elapsed, duration) if duration else elapsed

    async def run(self) -> None:
        if not hasattr(os, "mkfifo"):
            return
        self.ensure_pipe()
        loop = asyncio.get_running_loop()
        # O_RDWR: Unter Linux blockiert das Oeffnen nie und es gibt kein EOF,
        # wenn shairport-sync neu startet. Gelesen wird ereignisgesteuert.
        fd = os.open(str(self.pipe), os.O_RDWR | os.O_NONBLOCK)
        queue: "asyncio.Queue[bytes]" = asyncio.Queue()

        def readable() -> None:
            try:
                data = os.read(fd, 65536)
            except BlockingIOError:
                return
            if data:
                queue.put_nowait(data)

        loop.add_reader(fd, readable)
        buf = b""
        try:
            while True:
                buf += await queue.get()
                buf = await self._consume(buf)
        finally:
            loop.remove_reader(fd)
            os.close(fd)

    async def _consume(self, buf: bytes) -> bytes:
        changed = False
        end = 0
        for m in _ITEM.finditer(buf):
            end = m.end()
            kind, code = _code(m.group(1)), _code(m.group(2))
            try:
                data = base64.b64decode(m.group(4)) if m.group(4) else b""
            except (binascii.Error, ValueError):
                self.trace.append(f"{time.strftime('%H:%M:%S')} {kind}/{code} kaputt")
                continue
            if kind == "core" or code in _TRACE_CODES:
                preview = f"{len(data)} Bytes" if code == "PICT" else data[:60].decode("utf-8", "replace")
                self.trace.append(f"{time.strftime('%H:%M:%S')} {kind}/{code} {preview}")
            field = _FIELDS.get((kind, code))
            if field:
                value = data.decode("utf-8", "replace")
                if field == "artist":
                    # Apple Music haengt z. B. " • Video verfügbar" an den Interpreten
                    value = _SUFFIX.sub("", value)
                self.meta[field] = value
                changed = True
            elif (kind, code) == ("ssnc", "mdst"):
                self.meta_rtp = data.decode("ascii", "replace").strip() or None
                self._in_block = True
            elif (kind, code) == ("ssnc", "mden"):
                self._in_block = False
                changed = True
            elif (kind, code) == ("ssnc", "pcst"):
                self.pic_rtp = data.decode("ascii", "replace").strip() or None
            elif (kind, code) == ("ssnc", "PICT") and data and not _image_complete(data):
                # shairport-sync liefert manche Bilder nur teilweise (Rest mit Nullen aufgefuellt)
                self.trace.append(f"{time.strftime('%H:%M:%S')} ssnc/PICT unvollstaendig, verworfen")
                self.pic_rtp = None
            elif (kind, code) == ("ssnc", "PICT") and data:
                self.cover = data
                self.cover_rtp = self.pic_rtp or self.meta_rtp
                self.pic_rtp = None
                self.cover_version += 1
                changed = True
            elif (kind, code) == ("ssnc", "prgr") and data:
                try:
                    start, cur, stop = (int(x) for x in data.decode().split("/"))
                    # RTP-Zeitstempel sind 32 Bit und koennen ueberlaufen
                    self.meta["elapsed"] = ((cur - start) & 0xFFFFFFFF) / 44100.0
                    self.meta["duration"] = ((stop - start) & 0xFFFFFFFF) / 44100.0
                    self.meta["at"] = time.time()
                    self.meta["paused"] = False
                    changed = True
                except ValueError:
                    pass
            elif (kind, code) == ("ssnc", "pvol") and data:
                # "airplay_volume,volume,lowest,highest"; AirPlay-Skala -30..0 dB, -144 = stumm
                try:
                    av = float(data.decode().split(",")[0])
                    self.meta["volume"] = 0 if av <= -144 else round(max(0.0, min(1.0, (av + 30) / 30)) * 100)
                    changed = True
                except ValueError:
                    pass
            elif (kind, code) == ("ssnc", "pfls") and not self.meta.get("paused"):
                self.meta["elapsed"] = self.position()
                self.meta["paused"] = True
                changed = True
            elif (kind, code) == ("ssnc", "prsm") and self.meta.get("paused"):
                self.meta["at"] = time.time()
                self.meta["paused"] = False
                changed = True
            elif (kind, code) == ("ssnc", "snam"):
                self.meta["client"] = data.decode("utf-8", "replace")
                changed = True
            elif (kind, code) == ("ssnc", "pend"):
                self.reset()
                self._in_block = False
                changed = True
        if changed and not self._in_block:
            await self.on_update(self.meta)
        rest = buf[end:]
        return rest[-2_000_000:]  # nie unbegrenzt wachsen
