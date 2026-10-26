"""HDMI-CEC ueber cec-ctl (v4l-utils, Linux-CEC-Framework).

* beim Abspielen Fernseher einschalten und auf den Eingang des Pi umschalten
* Tasten der TV-Fernbedienung (Play, Pause, Weiter ...) steuern Klangstation
* Fernseher geht aus -> Wiedergabe pausieren; optional TV nach Stille ausschalten
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
from typing import Callable, Optional

log = logging.getLogger("klangstation.cec")

_PHYS = re.compile(r"Physical Address\s*:\s*([0-9a-f]\.[0-9a-f]\.[0-9a-f]\.[0-9a-f])", re.I)
_UI_CMD = re.compile(r"ui-cmd:\s*([a-z0-9-]+)", re.I)
# Tasten der TV-Fernbedienung -> Aktionen von Klangstation
KEYS = {"play": "play", "pause": "pause", "pause-play-function": "toggle", "play-function": "play",
        "pause-play": "toggle", "select": "toggle", "stop": "stop", "stop-function": "stop",
        "forward": "next", "backward": "prev", "fast-forward": "next", "rewind": "prev"}


def device_for(output_id: str) -> Optional[str]:
    """Raspberry Pi: vc4hdmi0 -> /dev/cec0, vc4hdmi1 -> /dev/cec1; sonst der erste CEC-Adapter."""
    m = re.search(r"vc4hdmi(\d)", output_id or "")
    if m and os.path.exists(f"/dev/cec{m.group(1)}"):
        return f"/dev/cec{m.group(1)}"
    return "/dev/cec0" if os.path.exists("/dev/cec0") else None


class Cec:
    def __init__(self) -> None:
        self.device: Optional[str] = None
        self.phys: Optional[str] = None
        self.tv_responds: Optional[bool] = None   # None = noch nicht probiert
        self.error = ""
        self.on_key: Optional[Callable[[str], None]] = None
        self.on_tv_standby: Optional[Callable[[], None]] = None
        self._pending_ui = False
        self.woke_at = 0.0

    @property
    def tool(self) -> Optional[str]:
        return shutil.which("cec-ctl")

    @property
    def available(self) -> bool:
        return bool(self.device and self.tool and self.phys)

    async def _run(self, *args: str, timeout: float = 6) -> str:
        proc = await asyncio.create_subprocess_exec(self.tool, "-d", self.device, *args,
                                                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise
        return out.decode("utf-8", "replace")

    async def setup(self, name: str, output_id: str) -> None:
        """Als Abspielgeraet anmelden (OSD-Name erscheint im TV-Quellenmenue)."""
        self.device = device_for(output_id)
        self.phys = None
        if not self.tool:
            self.error = "cec-ctl ist nicht installiert (Paket v4l-utils)"
            return
        if not self.device:
            self.error = "Kein CEC-Adapter gefunden"
            return
        try:
            out = await self._run("--playback", "-o", name[:14])
        except (OSError, asyncio.TimeoutError) as exc:
            self.error = f"CEC nicht nutzbar: {exc}"
            return
        m = _PHYS.search(out)
        self.phys = m.group(1) if m and m.group(1) != "f.f.f.f" else None
        self.error = "" if self.phys else "Kein CEC-fähiges Gerät am HDMI-Ausgang erkannt"

    def monitor_args(self) -> list:
        return ["-d", self.device, "--wait-for-msgs"]

    def on_line(self, line: str) -> None:
        """Ausgabe von cec-ctl --wait-for-msgs (ein Ereignis ueber mehrere Zeilen)."""
        if "USER_CONTROL_PRESSED" in line:
            self._pending_ui = True
        elif self._pending_ui and "ui-cmd" in line:
            self._pending_ui = False
            m = _UI_CMD.search(line)
            action = KEYS.get(m.group(1).lower()) if m else None
            if action and self.on_key:
                self.on_key(action)
        elif "Received from TV" in line and "STANDBY" in line and self.on_tv_standby:
            self.on_tv_standby()

    async def wake(self) -> bool:
        """Fernseher einschalten und auf unseren Eingang umschalten."""
        if not self.available:
            return False
        try:
            out = await self._run("--to", "0", "--image-view-on")
            self.tv_responds = "Not Acknowledged" not in out
            if self.tv_responds:
                await self._run("--to", "15", "--active-source", f"phys-addr={self.phys}")
                self.woke_at = time.time()
            elif self.error == "":
                self.error = "Das angeschlossene Gerät reagiert nicht auf CEC (am TV aktivieren: Anynet+, SimpLink, Bravia Sync …)"
            return self.tv_responds
        except (OSError, asyncio.TimeoutError) as exc:
            self.error = f"CEC-Befehl fehlgeschlagen: {exc}"
            return False

    async def standby(self) -> None:
        if self.available:
            try:
                await self._run("--to", "0", "--standby")
            except (OSError, asyncio.TimeoutError):
                pass

    def public(self) -> dict:
        return {"available": self.available, "device": self.device, "physical_address": self.phys,
                "tv_responds": self.tv_responds, "error": self.error}
