"""UPnP/DLNA-Renderer (gmediarender): Zustand und Titeldaten per SOAP abfragen, Wiedergabe steuern.

gmediarender lauscht nur auf der LAN-Adresse; die meldet es beim Start im Log
("Registered IPv4 10.0.0.5:49494"). Die Steuer-URLs sind fest.
"""
from __future__ import annotations

import html
import logging
import re
import time
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, Optional

import httpx

log = logging.getLogger("klangstation.upnp")

AVT = "urn:schemas-upnp-org:service:AVTransport:1"
RC = "urn:schemas-upnp-org:service:RenderingControl:1"
AVT_URL = "/upnp/control/rendertransport1"
RC_URL = "/upnp/control/rendercontrol1"
PORT = 49494

_REGISTERED = re.compile(r"Registered IPv4 (\d+\.\d+\.\d+\.\d+:\d+)")
# GStreamer kann das ALSA-Geraet nicht oeffnen, weil eine andere Quelle es noch belegt
_BUSY = re.compile(r"is busy|being used by another application|Playing failed", re.I)
_STATES = {"PLAYING": "play", "TRANSITIONING": "play", "PAUSED_PLAYBACK": "pause"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _seconds(value: str) -> float:
    """'0:03:25', '00:03:25.120' -> Sekunden; 'NOT_IMPLEMENTED' -> 0."""
    try:
        parts = [float(p) for p in value.split(":")]
    except (ValueError, AttributeError):
        return 0.0
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def _hms(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def parse_didl(didl: str) -> Dict[str, str]:
    """Titel/Interpret/Album/Cover aus DIDL-Lite (TrackMetaData)."""
    if not didl or not didl.lstrip().startswith("<"):
        return {}
    try:
        root = ET.fromstring(didl)
    except ET.ParseError:
        return {}
    out: Dict[str, str] = {}
    for el in root.iter():
        name, text = _local(el.tag), (el.text or "").strip()
        if not text:
            continue
        if name == "title":
            out.setdefault("title", text)
        elif name in ("artist", "creator"):
            out.setdefault("artist", text)
        elif name == "album":
            out.setdefault("album", text)
        elif name == "albumArtURI":
            out.setdefault("art", text)
    return out


class UpnpRenderer:
    def __init__(self) -> None:
        self.base: Optional[str] = None
        self.http = httpx.AsyncClient(timeout=3)
        self.info: Dict[str, Any] = {}
        self.on_busy: Optional[Callable[[], None]] = None
        self._polls = 0

    async def close(self) -> None:
        await self.http.aclose()

    def on_line(self, line: str) -> None:
        m = _REGISTERED.search(line)
        if m:
            self.base = "http://" + m.group(1)
            log.info("UPnP-Renderer erreichbar unter %s", self.base)
        elif _BUSY.search(line) and self.on_busy:
            self.on_busy()

    def reset(self) -> None:
        self.base = None
        self.info = {}

    @property
    def playing(self) -> bool:
        return self.info.get("transport") in ("PLAYING", "TRANSITIONING")

    async def _soap(self, service: str, path: str, action: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, str]:
        if not self.base:
            raise ConnectionError("UPnP-Renderer laeuft nicht")
        params = {"InstanceID": 0}
        params.update(args or {})
        inner = "".join(f"<{k}>{html.escape(str(v))}</{k}>" for k, v in params.items())
        body = ('<?xml version="1.0" encoding="utf-8"?>'
                '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                f'<u:{action} xmlns:u="{service}">{inner}</u:{action}></s:Body></s:Envelope>')
        try:
            resp = await self.http.post(self.base + path, content=body.encode("utf-8"), headers={
                "Content-Type": 'text/xml; charset="utf-8"', "SOAPACTION": f'"{service}#{action}"'})
        except httpx.HTTPError as exc:
            raise ConnectionError(f"UPnP-Renderer nicht erreichbar: {exc}")
        if resp.status_code >= 400:
            raise ValueError(f"UPnP-Aktion {action} abgelehnt (HTTP {resp.status_code})")
        out: Dict[str, str] = {}
        for el in ET.fromstring(resp.content).iter():
            if len(el) == 0:
                out[_local(el.tag)] = el.text or ""
        return out

    async def poll(self) -> Dict[str, Any]:
        t = await self._soap(AVT, AVT_URL, "GetTransportInfo")
        p = await self._soap(AVT, AVT_URL, "GetPositionInfo")
        # Lautstaerke seltener abfragen: jede Abfrage landet im Log von gmediarender
        vol = self.info.get("volume", -1)
        self._polls += 1
        if vol < 0 or self._polls % 5 == 0:
            try:
                vol = int((await self._soap(RC, RC_URL, "GetVolume", {"Channel": "Master"})).get("CurrentVolume", -1))
            except (ValueError, ConnectionError):
                vol = -1
        transport = t.get("CurrentTransportState", "")
        meta = parse_didl(p.get("TrackMetaData", ""))
        uri = p.get("TrackURI", "")
        self.info = {
            "transport": transport,
            "state": _STATES.get(transport, "stop"),
            "title": meta.get("title") or (uri.rsplit("/", 1)[-1] if uri else ""),
            "artist": meta.get("artist", ""),
            "album": meta.get("album", ""),
            "art": meta.get("art"),
            "elapsed": _seconds(p.get("RelTime", "")),
            "duration": _seconds(p.get("TrackDuration", "")),
            "volume": vol,
            "uri": uri,
            "at": time.time(),
        }
        return self.info

    async def action(self, name: str) -> None:
        args = {"Speed": 1} if name == "Play" else None
        await self._soap(AVT, AVT_URL, name, args)

    async def seek(self, seconds: float) -> None:
        await self._soap(AVT, AVT_URL, "Seek", {"Unit": "REL_TIME", "Target": _hms(seconds)})

    async def set_volume(self, volume: int) -> None:
        volume = max(0, min(100, volume))
        await self._soap(RC, RC_URL, "SetVolume", {"Channel": "Master", "DesiredVolume": volume})
        self.info["volume"] = volume
