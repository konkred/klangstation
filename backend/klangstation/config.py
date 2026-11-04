"""Pfade, Umgebungsvariablen und persistente Einstellungen."""
from __future__ import annotations

import hashlib
import json
import os
import socket
import tempfile
from pathlib import Path
from typing import Any, Dict

VERSION = "0.1.0"

_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("KS_DATA_DIR", str(Path.home() / ".klangstation")))
RUN_DIR = DATA_DIR / "run"
COVER_DIR = DATA_DIR / "covers"
MEDIA_ROOT = Path(os.environ.get("KS_MEDIA_ROOT", "/media/klangstation"))
WEB_DIR = Path(os.environ.get("KS_WEB_DIR", str(_ROOT / "web")))
HOOK_PATH = Path(os.environ.get("KS_HOOK", str(_ROOT / "system" / "hooks" / "ks-hook")))
SPOTIFY_SINK = _ROOT / "system" / "ks-spotify-sink"


def _web_build() -> str:
    """Kennung der Oberflaechen-Dateien: aendert sich mit jedem Update, offene Bildschirme laden dann neu."""
    h = hashlib.sha1()
    for path in sorted(p for p in WEB_DIR.rglob("*") if p.is_file()):
        st = path.stat()
        h.update(f"{path.relative_to(WEB_DIR)}:{st.st_size}:{st.st_mtime_ns};".encode())
    return h.hexdigest()[:12]


WEB_BUILD = _web_build()

# Erscheinungsbilder von "Laeuft gerade" (je eine Datei web/css/tv-<name>.css, "classic" ist tv.css allein)
TV_THEMES = ("classic", "aero", "nacht", "winamp", "aqua", "hifi", "luna")

HOST = os.environ.get("KS_HOST", "0.0.0.0")
PORT = int(os.environ.get("KS_PORT", "8080"))
MPD_HOST = "127.0.0.1"
MPD_PORT = int(os.environ.get("KS_MPD_PORT", "6600"))
CD_DEVICE = os.environ.get("KS_CD_DEVICE", "/dev/sr0")
SPOTIFY_ZEROCONF_PORT = int(os.environ.get("KS_SPOTIFY_PORT", "4070"))

# Binaries koennen per Umgebung ueberschrieben werden (z. B. selbst gebautes librespot).
BIN_MPD = os.environ.get("KS_BIN_MPD", "mpd")
BIN_SHAIRPORT = os.environ.get("KS_BIN_SHAIRPORT", "shairport-sync")
BIN_LIBRESPOT = os.environ.get("KS_BIN_LIBRESPOT", "librespot")
BIN_GMEDIARENDER = os.environ.get("KS_BIN_GMEDIARENDER", "gmediarender")
BIN_BLUEALSA_APLAY = os.environ.get("KS_BIN_BLUEALSA_APLAY", "bluealsa-aplay")


def _default_name() -> str:
    host = socket.gethostname().split(".")[0] or "klangstation"
    return host[:1].upper() + host[1:]


DEFAULTS: Dict[str, Any] = {
    "device_name": _default_name(),
    "output": None,              # ALSA-Geraet, None = automatisch waehlen
    "bitperfect": False,         # hw: statt plughw:, kein Software-Mixer in MPD
    "speakers": 2,               # 2 = Stereo, 6 = 5.1, 8 = 7.1 (Stereo auf alle Lautsprecher hochmischen)
    "mixer_level": 0,            # Hardware-Regler der Karte in %, 0 = nicht festlegen (nur Regler auf 0 % auf 80 %)
    "loudness": "off",           # Lautstaerke angleichen: "off", "replaygain" (Tags) oder "dynamic" (MPD-Normalisierung)
    "crossfade": 0,              # Ueberblenden zwischen Titeln in Sekunden
    "airplay_enabled": True,
    "spotify_enabled": True,
    "spotify_bitrate": 320,
    "upnp_enabled": True,
    "upnp_uuid": "",             # wird beim ersten Start erzeugt, damit Apps den Renderer wiedererkennen
    "bluetooth_enabled": True,
    "cd_autoplay": False,
    "metadata_online": True,
    "musicbrainz_contact": "",   # E-Mail oder URL fuer den User-Agent
    "radio_country": "DE",
    "radio_favorites": [],
    "auth_hash": "",             # leer = kein Zugangsschutz
    "auth_scope": "settings",    # "all" oder "settings"
    "shares": [],                # Netzwerkfreigaben (SMB/NFS)
    "cec_enabled": True,
    "cec_tv_on": True,           # beim Abspielen Fernseher einschalten und Eingang waehlen
    "cec_standby_minutes": 0,    # Fernseher nach so vielen Minuten Stille ausschalten (0 = nie)
    "cec_pause_on_tv_off": True,
    "tv_enabled": True,          # "Laeuft gerade"-Bildschirm am HDMI-Ausgang
    "tv_lyrics": True,           # Liedtexte auf dem "Laeuft gerade"-Bildschirm
    "tv_theme": "classic",       # Erscheinungsbild des "Laeuft gerade"-Bildschirms (siehe TV_THEMES)
    "tv_history": True,          # Ruhebildschirm: zuletzt gehoerte Cover
    "weather_place": "",         # Ruhebildschirm: Wetter fuer diesen Ort (leer = aus)
    "alarms": [],                # Wecker (siehe timers.py)
    "rip_target": "local",       # Ziel beim CD-Rippen: "local" oder Ordnername eines USB-Datentraegers
    "rip_eject": True,           # CD nach dem Rippen auswerfen
}

# Werden nie ueber die API herausgegeben
SECRET_KEYS = ("auth_hash",)

_VALIDATORS = {
    "device_name": lambda v: isinstance(v, str) and 0 < len(v.strip()) <= 40,
    "output": lambda v: v is None or (isinstance(v, str) and len(v) < 200),
    "bitperfect": lambda v: isinstance(v, bool),
    "speakers": lambda v: v in (2, 6, 8),
    "mixer_level": lambda v: v in (0, 50, 60, 70, 80, 90, 100),
    "loudness": lambda v: v in ("off", "replaygain", "dynamic"),
    "crossfade": lambda v: v in (0, 2, 5, 10),
    "airplay_enabled": lambda v: isinstance(v, bool),
    "spotify_enabled": lambda v: isinstance(v, bool),
    "spotify_bitrate": lambda v: v in (96, 160, 320),
    "upnp_enabled": lambda v: isinstance(v, bool),
    "upnp_uuid": lambda v: isinstance(v, str) and len(v) <= 64,
    "bluetooth_enabled": lambda v: isinstance(v, bool),
    "cd_autoplay": lambda v: isinstance(v, bool),
    "metadata_online": lambda v: isinstance(v, bool),
    "musicbrainz_contact": lambda v: isinstance(v, str) and len(v) <= 200,
    "radio_country": lambda v: isinstance(v, str) and len(v) <= 2,
    "radio_favorites": lambda v: isinstance(v, list) and len(v) <= 500,
    "auth_hash": lambda v: isinstance(v, str) and len(v) <= 300,
    "auth_scope": lambda v: v in ("all", "settings"),
    "shares": lambda v: isinstance(v, list) and len(v) <= 20 and all(isinstance(s, dict) for s in v),
    "cec_enabled": lambda v: isinstance(v, bool),
    "cec_tv_on": lambda v: isinstance(v, bool),
    "cec_standby_minutes": lambda v: v in (0, 5, 10, 30, 60),
    "cec_pause_on_tv_off": lambda v: isinstance(v, bool),
    "tv_enabled": lambda v: isinstance(v, bool),
    "tv_lyrics": lambda v: isinstance(v, bool),
    "tv_theme": lambda v: v in TV_THEMES,
    "tv_history": lambda v: isinstance(v, bool),
    "weather_place": lambda v: isinstance(v, str) and len(v) <= 80,
    "alarms": lambda v: isinstance(v, list) and len(v) <= 10 and all(isinstance(a, dict) for a in v),
    "rip_target": lambda v: isinstance(v, str) and 0 < len(v) <= 64,
    "rip_eject": lambda v: isinstance(v, bool),
}


class Settings:
    def __init__(self, path: Path):
        self.path = path
        self._data: Dict[str, Any] = dict(DEFAULTS)
        if path.exists():
            try:
                stored = json.loads(path.read_text(encoding="utf-8"))
                for key, value in stored.items():
                    if key in _VALIDATORS and _VALIDATORS[key](value):
                        self._data[key] = value
            except (OSError, ValueError):
                pass

    def get(self, key: str) -> Any:
        return self._data[key]

    def all(self) -> Dict[str, Any]:
        return dict(self._data)

    def public(self) -> Dict[str, Any]:
        """Fuer die Oberflaeche: ohne Passwort-Hash und ohne Freigabe-Passwoerter."""
        out = {k: v for k, v in self._data.items() if k not in SECRET_KEYS}
        out["auth_enabled"] = bool(self._data.get("auth_hash"))
        out["shares"] = [dict(s, password="", has_password=bool(s.get("password"))) for s in self._data["shares"]]
        return out

    def update(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        """Uebernimmt gueltige Werte und gibt die tatsaechlich geaenderten zurueck."""
        changed = {}
        for key, value in changes.items():
            if key not in _VALIDATORS:
                raise ValueError(f"Unbekannte Einstellung: {key}")
            if isinstance(value, str) and key != "output":
                value = value.strip()
            if not _VALIDATORS[key](value):
                raise ValueError(f"Ungueltiger Wert fuer {key}")
            if self._data.get(key) != value:
                self._data[key] = value
                changed[key] = value
        if changed:
            self.save()
        return changed

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".settings")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self._data, fh, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)
