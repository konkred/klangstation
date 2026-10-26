"""Startet und ueberwacht mpd, shairport-sync und librespot als Kindprozesse.

Die Dienste laufen unter dem Benutzer der Webanwendung. So kann die App
Konfigurationen schreiben und Dienste neu starten, ohne Root-Rechte zu haben.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import os
import shutil
import time
from typing import Callable, Dict, List, Optional

log = logging.getLogger("klangstation.daemons")


class Daemon:
    def __init__(self, name: str, binary: str, on_line: Optional[Callable[[str], None]] = None):
        self.name = name
        self.binary = binary
        self.on_line = on_line
        self.cmd: Optional[List[str]] = None
        self.env: Optional[Dict[str, str]] = None
        self.proc: Optional[asyncio.subprocess.Process] = None
        self.tail: "collections.deque[str]" = collections.deque(maxlen=40)
        self._task: Optional[asyncio.Task] = None
        self._stopping = False

    @property
    def path(self) -> Optional[str]:
        return shutil.which(self.binary)

    @property
    def available(self) -> bool:
        return self.path is not None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.returncode is None

    def info(self) -> dict:
        return {"name": self.name, "available": self.available, "running": self.running,
                "log": list(self.tail)[-8:]}

    async def start(self, args: List[str], env: Optional[Dict[str, str]] = None) -> None:
        await self.stop()
        if not self.available:
            self.tail.append(f"{self.binary} ist nicht installiert")
            return
        self._args, self._extra_env = list(args), dict(env or {})
        self.cmd = [self.path] + self._args  # type: ignore[list-item]
        self.env = dict(os.environ, **self._extra_env)
        self._stopping = False
        self._task = asyncio.create_task(self._supervise())

    async def restart(self) -> None:
        if self.cmd:
            await self.start(self._args, self._extra_env)

    async def _supervise(self) -> None:
        backoff = 1.0
        while not self._stopping:
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *self.cmd, env=self.env, stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True)
            except OSError as exc:
                self.tail.append(f"Start fehlgeschlagen: {exc}")
                return
            log.info("%s gestartet (pid %s)", self.name, self.proc.pid)
            started = time.monotonic()
            assert self.proc.stdout
            async for raw in self.proc.stdout:
                line = raw.decode("utf-8", "replace").rstrip()
                if line:
                    self.tail.append(line)
                    log.debug("[%s] %s", self.name, line)
                    if self.on_line:
                        self.on_line(line)
            rc = await self.proc.wait()
            if self._stopping:
                break
            if time.monotonic() - started > 60:
                backoff = 1.0  # lief lange: frischer Fehler, kein Dauerabsturz
            log.warning("%s beendet (Code %s), Neustart in %.0fs", self.name, rc, backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def stop(self) -> None:
        self._stopping = True
        proc, task = self.proc, self._task
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
            except ProcessLookupError:
                pass
        if task:
            try:
                await asyncio.wait_for(task, timeout=3)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                task.cancel()
        self.proc = None
        self._task = None
