"""Webradio ueber die Radio Browser API (https://api.radio-browser.info).

Frei, ohne API-Key, Community-gepflegt (ca. 50.000 Sender). Die Server werden
wie empfohlen per DNS (all.api.radio-browser.info) ermittelt. Faellt einer aus,
wird der naechste genommen.
"""
from __future__ import annotations

import asyncio
import logging
import random
import socket
import time
from typing import Any, Dict, List, Optional

import httpx

from .config import VERSION

log = logging.getLogger("klangstation.radio")

# Stand 10/2026; fi1/nl1 gibt es nicht mehr. Wird immer mit der DNS-Liste zusammengefuehrt.
FALLBACK_SERVERS = ["de1.api.radio-browser.info", "de2.api.radio-browser.info"]
ROUNDS = 3   # die Server setzen zeitweise einzelne Verbindungen zurueck: mehrere Durchgaenge
DAY = 86400


def station(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "uuid": raw.get("stationuuid", ""),
        "name": (raw.get("name") or "").strip(),
        "url": raw.get("url_resolved") or raw.get("url", ""),
        "favicon": raw.get("favicon", ""),
        "country": raw.get("country", ""),
        "countrycode": raw.get("countrycode", ""),
        "tags": [t for t in (raw.get("tags") or "").split(",") if t][:5],
        "codec": raw.get("codec", ""),
        "bitrate": raw.get("bitrate", 0),
        "homepage": raw.get("homepage", ""),
    }


class RadioBrowser:
    def __init__(self):
        self.http = httpx.AsyncClient(timeout=10, headers={"User-Agent": f"Klangstation/{VERSION}"})
        self._servers: List[str] = []
        self._servers_at = 0.0
        self._memo: Dict[str, "tuple[float, Any]"] = {}

    async def close(self) -> None:
        await self.http.aclose()

    async def servers(self) -> List[str]:
        if self._servers and time.time() - self._servers_at < 3600:
            return self._servers
        loop = asyncio.get_running_loop()
        names = set()
        try:
            infos = await loop.getaddrinfo("all.api.radio-browser.info", 443, type=socket.SOCK_STREAM)
            for info in infos:
                try:
                    host = (await loop.run_in_executor(None, socket.gethostbyaddr, info[4][0]))[0]
                    if host.endswith("radio-browser.info"):
                        names.add(host)
                except OSError:
                    continue
        except OSError as exc:
            log.info("DNS-Ermittlung der Radio-Browser-Server fehlgeschlagen: %s", exc)
        servers = list(names | set(FALLBACK_SERVERS))
        random.shuffle(servers)
        self._servers, self._servers_at = servers, time.time()
        return servers

    async def _get(self, path: str, params: Optional[Dict[str, Any]] = None, ttl: float = 600) -> Any:
        key = path + repr(sorted((params or {}).items()))
        hit = self._memo.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        last_exc: Optional[Exception] = None
        servers = await self.servers()
        for attempt in range(ROUNDS):
            for server in servers:
                try:
                    resp = await self.http.get(f"https://{server}{path}", params=params)
                    resp.raise_for_status()
                    data = resp.json()
                    self._memo[key] = (time.time(), data)
                    if len(self._memo) > 300:
                        self._memo.pop(next(iter(self._memo)))
                    return data
                except (httpx.HTTPError, ValueError) as exc:
                    last_exc = exc
            await asyncio.sleep(0.4 * (attempt + 1))
        self._servers_at = 0
        detail = str(last_exc) or last_exc.__class__.__name__ if last_exc else "keine Server"
        log.info("Radio Browser nicht erreichbar: %s", detail)
        raise ConnectionError(f"Radio Browser nicht erreichbar ({detail})")

    async def search(self, name: str = "", country: str = "", tag: str = "",
                     limit: int = 60, offset: int = 0) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"limit": limit, "offset": offset, "hidebroken": "true",
                                  "order": "clickcount", "reverse": "true"}
        if name:
            params["name"] = name
        if country:
            params["countrycode"] = country
        if tag:
            params["tag"] = tag
            params["tagExact"] = "false"
        return [station(s) for s in await self._get("/json/stations/search", params)]

    async def countries(self) -> List[Dict[str, Any]]:
        data = await self._get("/json/countries", {"hidebroken": "true"}, ttl=DAY)
        return sorted(({"code": c.get("iso_3166_1", ""), "name": c.get("name", ""),
                        "count": c.get("stationcount", 0)} for c in data if c.get("iso_3166_1")),
                      key=lambda c: c["name"])

    async def tags(self, limit: int = 80) -> List[Dict[str, Any]]:
        data = await self._get("/json/tags", {"order": "stationcount", "reverse": "true",
                                              "limit": limit, "hidebroken": "true"}, ttl=DAY)
        return [{"name": t.get("name", ""), "count": t.get("stationcount", 0)} for t in data]

    async def click(self, uuid: str) -> None:
        """Meldet einen Abruf (gewuenscht vom Projekt, haelt die Beliebtheitslisten aktuell)."""
        if not uuid:
            return
        try:
            await self._get(f"/json/url/{uuid}", ttl=0)
        except ConnectionError:
            pass
