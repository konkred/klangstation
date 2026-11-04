"""Kleine Helfer rund um das Geraet: Update-Hinweis, Musik hochladen, Sichern der Einstellungen."""
from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .config import MEDIA_ROOT, VERSION
from .ripper import LOCAL_DIR

log = logging.getLogger("klangstation.extras")

# ---------------------------------------------------------------- Update-Hinweis
# Das oeffentliche Repo kennt die neueste Version; es wird nichts ausser der Abfrage selbst uebertragen
UPDATE_URL = "https://raw.githubusercontent.com/konkred/klangstation/main/backend/klangstation/config.py"
UPDATE_EVERY = 24 * 3600
_VERSION_LINE = re.compile(r'^VERSION = "(\d+(?:\.\d+)*)"', re.M)


def _version_key(version: str) -> Tuple[int, ...]:
    return tuple(int(p) for p in version.split("."))


class UpdateCheck:
    def __init__(self, current: str = VERSION) -> None:
        self.current = current
        self.latest = ""
        self.checked = 0.0
        self.error = False

    def public(self) -> Dict[str, Any]:
        available = bool(self.latest) and _version_key(self.latest) > _version_key(self.current)
        return {"current": self.current, "latest": self.latest, "available": available,
                "checked": self.checked, "error": self.error}

    async def check(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                res = await client.get(UPDATE_URL)
            res.raise_for_status()
            m = _VERSION_LINE.search(res.text)
            if not m:
                raise ValueError("keine Versionsangabe gefunden")
            self.latest, self.error = m.group(1), False
        except (httpx.HTTPError, ValueError) as exc:
            log.info("Update-Pruefung fehlgeschlagen: %s", exc)
            self.error = True
        self.checked = time.time()
        return self.public()


# ---------------------------------------------------------------- Musik hochladen
UPLOAD_DIR = MEDIA_ROOT / LOCAL_DIR / "Hochgeladen"
UPLOAD_MAX = 4 * 1024 ** 3        # je Datei
UPLOAD_RESERVE = 500 * 1024 ** 2  # so viel bleibt auf dem Laufwerk frei
UPLOAD_EXT = {".flac", ".mp3", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".wav", ".wma", ".ape", ".wv", ".aif", ".aiff",
              ".dsf", ".dff", ".mka", ".jpg", ".jpeg", ".png", ".lrc"}


def upload_target(rel: str) -> Path:
    """Zielpfad unterhalb von Lokal/Hochgeladen; relative Ordner aus dem Browser bleiben erhalten."""
    parts = rel.replace("\\", "/").split("/")
    if not rel or len(parts) > 8 or any(not p or p.startswith(".") or len(p) > 200 or not p.isprintable() for p in parts):
        raise ValueError("Ungültiger Dateiname")
    if Path(parts[-1]).suffix.lower() not in UPLOAD_EXT:
        raise ValueError("Dieser Dateityp wird nicht angenommen")
    return UPLOAD_DIR.joinpath(*parts)


# ---------------------------------------------------------------- Sichern
BACKUP_FORMAT = 1
BACKUP_MAX = 5 * 1024 ** 2
# Passwort-Hash und Schutzumfang bleiben am Geraet; die UPnP-Kennung gehoert zu genau einem Geraet
BACKUP_SKIP = {"auth_hash", "auth_scope", "upnp_uuid"}


def make_backup(settings: Dict[str, Any], playlist_dir: Path) -> Dict[str, Any]:
    """Einstellungen und Wiedergabelisten als JSON. Freigabe-Passwoerter bleiben draussen."""
    data = {k: v for k, v in settings.items() if k not in BACKUP_SKIP}
    data["shares"] = [dict(s, password="") for s in settings.get("shares", [])]
    playlists = {p.stem: p.read_text(encoding="utf-8", errors="replace") for p in sorted(playlist_dir.glob("*.m3u"))}
    return {"klangstation_backup": BACKUP_FORMAT, "version": VERSION, "created": int(time.time()),
            "settings": data, "playlists": playlists}


def backup_parts(data: Any) -> Tuple[Dict[str, Any], Dict[str, str]]:
    if not isinstance(data, dict) or data.get("klangstation_backup") != BACKUP_FORMAT:
        raise ValueError("Das ist keine Sicherung von Klangstation")
    settings, playlists = data.get("settings"), data.get("playlists", {})
    if not isinstance(settings, dict) or not isinstance(playlists, dict):
        raise ValueError("Die Sicherung ist beschädigt")
    return ({k: v for k, v in settings.items() if k not in BACKUP_SKIP},
            {str(k): v for k, v in playlists.items() if isinstance(v, str)})


# ---------------------------------------------------------------- Nachtmodus
def in_window(start: str, end: str, now: Optional[time.struct_time] = None) -> bool:
    """Liegt die Uhrzeit im Zeitfenster? Es darf ueber Mitternacht gehen; gleiche Zeiten = immer."""
    now = now or time.localtime()
    minute = now.tm_hour * 60 + now.tm_min

    def parse(text: str) -> int:
        return int(text[:2]) * 60 + int(text[3:5])

    a, b = parse(start), parse(end)
    if a == b:
        return True
    return a <= minute < b if a < b else minute >= a or minute < b


def missing_passwords(shares: List[Dict[str, Any]]) -> int:
    return sum(1 for s in shares if s.get("type") == "smb" and s.get("user") and not s.get("password"))
