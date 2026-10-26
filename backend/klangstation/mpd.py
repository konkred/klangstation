"""Schlanker asyncio-Client fuer das MPD-Textprotokoll.

Eigene Implementierung statt python-mpd2, damit Binärantworten (albumart,
readpicture) und automatisches Reconnect ohne Abhaengigkeit funktionieren.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Dict, Iterable, List, Optional, Tuple

log = logging.getLogger("klangstation.mpd")

Pairs = List[Tuple[str, str]]


class MPDError(Exception):
    pass


def quote(arg) -> str:
    s = str(arg).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{s}"'


def build(cmd: str, *args) -> str:
    return " ".join([cmd] + [quote(a) for a in args])


class _Connection:
    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None

    async def connect(self) -> None:
        self.reader, self.writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), timeout=5)
        greeting = await self.reader.readline()
        if not greeting.startswith(b"OK MPD"):
            raise MPDError(f"Unerwartete Begruessung: {greeting!r}")

    def close(self) -> None:
        if self.writer:
            self.writer.close()
        self.reader = self.writer = None

    async def send(self, text: str) -> Tuple[Pairs, Optional[bytes]]:
        assert self.reader and self.writer
        self.writer.write(text.encode("utf-8") + b"\n")
        await self.writer.drain()
        pairs: Pairs = []
        binary: Optional[bytes] = None
        while True:
            raw = await self.reader.readline()
            if not raw:
                raise ConnectionError("MPD-Verbindung geschlossen")
            line = raw.decode("utf-8", "replace").rstrip("\n")
            if line == "OK" or line == "list_OK":
                if line == "OK":
                    break
                continue
            if line.startswith("ACK "):
                raise MPDError(line)
            key, _, value = line.partition(": ")
            if key == "binary":
                binary = await self.reader.readexactly(int(value))
                await self.reader.readexactly(1)
                continue
            pairs.append((key, value))
        return pairs, binary


def to_dict(pairs: Pairs) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in pairs:
        out.setdefault(k, v)
    return out


def to_objects(pairs: Pairs, starts: Iterable[str] = ("file", "directory", "playlist")) -> List[Dict[str, str]]:
    starts = set(starts)
    items: List[Dict[str, str]] = []
    for k, v in pairs:
        if k in starts or not items:
            items.append({})
        items[-1].setdefault(k, v)
    return items


class MPD:
    """Befehlsverbindung mit Reconnect und eigene Idle-Verbindung."""

    def __init__(self, host: str, port: int):
        self.host, self.port = host, port
        self._conn: Optional[_Connection] = None
        self._lock = asyncio.Lock()
        self.connected = False

    async def raw(self, text: str) -> Tuple[Pairs, Optional[bytes]]:
        async with self._lock:
            for attempt in (0, 1):
                try:
                    if self._conn is None:
                        conn = _Connection(self.host, self.port)
                        await conn.connect()
                        self._conn = conn
                    result = await asyncio.wait_for(self._conn.send(text), timeout=30)
                    self.connected = True
                    return result
                except MPDError:
                    raise
                except asyncio.CancelledError:
                    # Abbruch mitten in einer Antwort: Verbindung ist nicht mehr synchron
                    if self._conn:
                        self._conn.close()
                    self._conn = None
                    raise
                except (ConnectionError, OSError, asyncio.IncompleteReadError, asyncio.TimeoutError):
                    if self._conn:
                        self._conn.close()
                    self._conn = None
                    self.connected = False
                    if attempt:
                        raise ConnectionError("MPD nicht erreichbar")
        raise ConnectionError("MPD nicht erreichbar")

    async def run(self, cmd: str, *args) -> Pairs:
        return (await self.raw(build(cmd, *args)))[0]

    async def dict(self, cmd: str, *args) -> Dict[str, str]:
        return to_dict(await self.run(cmd, *args))

    async def objects(self, cmd: str, *args) -> List[Dict[str, str]]:
        return to_objects(await self.run(cmd, *args))

    async def batch(self, lines: List[str]) -> None:
        if not lines:
            return
        await self.raw("command_list_begin\n" + "\n".join(lines) + "\ncommand_list_end")

    async def picture(self, uri: str, limit: int = 8 * 1024 * 1024) -> Optional[bytes]:
        """Eingebettetes Bild (readpicture) oder cover.jpg im Ordner (albumart)."""
        for cmd in ("readpicture", "albumart"):
            data = bytearray()
            try:
                while True:
                    pairs, chunk = await self.raw(build(cmd, uri, len(data)))
                    info = to_dict(pairs)
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) >= int(info.get("size", 0)) or len(data) > limit:
                        break
            except MPDError:
                data = bytearray()
            if data:
                return bytes(data)
        return None

    async def idle_loop(self, on_change: Callable[[List[str]], Awaitable[None]]) -> None:
        backoff = 1.0
        while True:
            conn = _Connection(self.host, self.port)
            try:
                await conn.connect()
                backoff = 1.0
                await on_change(["reconnect"])
                while True:
                    pairs, _ = await conn.send(
                        "idle player mixer playlist options database update output stored_playlist")
                    changed = [v for k, v in pairs if k == "changed"]
                    if changed:
                        await on_change(changed)
            except asyncio.CancelledError:
                conn.close()
                raise
            except Exception as exc:  # noqa: BLE001 - Verbindung neu aufbauen
                log.debug("Idle-Verbindung verloren: %s", exc)
                conn.close()
                self.connected = False
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10)
