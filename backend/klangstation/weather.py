"""Wetter fuer den Ruhebildschirm (Open-Meteo: frei, ohne Schluessel).

Der Ort wird einmal in Koordinaten umgerechnet und gecacht, das Wetter hoechstens alle 20 Minuten geholt.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import httpx

from .cache import Cache
from .config import VERSION, Settings

log = logging.getLogger("klangstation.weather")

GEO = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST = "https://api.open-meteo.com/v1/forecast"
REFRESH = 20 * 60

# WMO-Wettercodes -> (Text, Symbol aus DejaVu Sans, das auch im Kiosk ohne Emoji-Schrift da ist)
_CODES = [
    ((0,), "Klar", "☀"), ((1,), "Überwiegend klar", "☀"), ((2,), "Teils bewölkt", "⛅"), ((3,), "Bedeckt", "☁"),
    ((45, 48), "Nebel", "≋"), ((51, 53, 55, 56, 57), "Nieselregen", "☂"), ((61, 63, 66, 80, 81), "Regen", "☂"),
    ((65, 67, 82), "Starker Regen", "☂"), ((71, 73, 75, 77, 85, 86), "Schnee", "❄"), ((95, 96, 99), "Gewitter", "⚡"),
]


def describe(code: int):
    for codes, text, sym in _CODES:
        if code in codes:
            return text, sym
    return "", ""


class Weather:
    def __init__(self, settings: Settings, cache: Cache):
        self.settings = settings
        self.cache = cache
        self.http = httpx.AsyncClient(timeout=15, headers={"User-Agent": f"Klangstation/{VERSION} (self-hosted)"})
        self.current: Optional[Dict[str, Any]] = None
        self._place = ""
        self._next = 0.0

    async def close(self) -> None:
        await self.http.aclose()

    def public(self) -> Optional[Dict[str, Any]]:
        if not self.current or self._place != self.settings.get("weather_place").strip():
            return None
        return self.current

    async def refresh(self) -> bool:
        """Holt das Wetter, wenn faellig. True, wenn sich etwas geaendert hat."""
        place = self.settings.get("weather_place").strip()
        if not place or not self.settings.get("metadata_online"):
            changed = self.current is not None
            self.current, self._place = None, place
            return changed
        if place == self._place and time.time() < self._next:
            return False
        if place != self._place:
            self.current = None
        self._place = place
        self._next = time.time() + REFRESH
        try:
            geo = await self._locate(place)
            if not geo:
                self.current = {"error": f"Ort „{place}“ nicht gefunden"}
                return True
            r = await self.http.get(FORECAST, params={
                "latitude": geo["lat"], "longitude": geo["lon"], "timezone": "auto", "forecast_days": 1,
                "current": "temperature_2m,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min"})
            r.raise_for_status()
            data = r.json()
            cur, day = data["current"], data["daily"]
            text, sym = describe(int(cur.get("weather_code", -1)))
            self.current = {"place": geo["name"], "temp": round(cur["temperature_2m"]), "text": text, "symbol": sym,
                            "max": round(day["temperature_2m_max"][0]), "min": round(day["temperature_2m_min"][0])}
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            log.info("Wetter nicht abrufbar: %s", exc)
            self._next = time.time() + 300  # bald noch einmal versuchen; altes Wetter bleibt stehen
            return False
        return True

    async def _locate(self, place: str) -> Optional[Dict[str, Any]]:
        key = "geo:" + place.lower()
        found, value = self.cache.lookup(key)
        if found:
            return value
        r = await self.http.get(GEO, params={"name": place, "count": 1, "language": "de", "format": "json"})
        r.raise_for_status()
        hits = r.json().get("results") or []
        geo = {"name": hits[0]["name"], "lat": hits[0]["latitude"], "lon": hits[0]["longitude"]} if hits else None
        self.cache.set(key, geo, 365 * 86400 if geo else 86400)
        return geo
