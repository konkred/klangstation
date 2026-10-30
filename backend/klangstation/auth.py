"""Optionaler Zugangsschutz: Passwort (PBKDF2), signiertes Sitzungs-Cookie, Bremse gegen Durchprobieren.

Zwei Stufen:
  "all"      - ohne Anmeldung ist nichts bedienbar
  "settings" - Abspielen geht fuer alle, Optionen/Kopplung/Freigaben nur mit Anmeldung
Anfragen vom Pi selbst (Hooks der Audio-Dienste, Fernseh-Bildschirm) sind immer erlaubt.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

from .config import Settings

COOKIE = "ks_session"
MAX_AGE = 30 * 86400
ITERATIONS = 200_000
LOCAL = {"127.0.0.1", "::1"}

# Immer erreichbar: die Seite selbst (ohne Daten) und die Anmeldung
_PUBLIC_PREFIXES = ("/css/", "/js/", "/img/")
_PUBLIC_PATHS = {"/", "/index.html", "/manifest.json", "/tv", "/tv.html", "/api/auth/status", "/api/auth/login", "/api/internal/hook"}
# Bei Stufe "settings" geschuetzt (alles, was Einstellungen oder Geraete veraendert)
_SETTINGS_PREFIXES = ("/api/settings", "/api/bluetooth/", "/api/shares", "/api/auth/password", "/api/tv/show")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${_b64(salt)}${_b64(dk)}"


def check_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), _unb64(salt), int(iterations))
        return hmac.compare_digest(dk, _unb64(digest))
    except (ValueError, TypeError):
        return False


class Auth:
    def __init__(self, settings: Settings, data_dir: Path):
        self.settings = settings
        self.secret_path = data_dir / "secret"
        self._secret = self._load_secret()
        self._fails: Dict[str, Tuple[int, float]] = {}   # IP -> (Fehlversuche, gesperrt bis)

    def _load_secret(self) -> bytes:
        try:
            data = self.secret_path.read_bytes()
            if len(data) >= 32:
                return data
        except OSError:
            pass
        return self.rotate_secret()

    def rotate_secret(self) -> bytes:
        """Neues Geheimnis: alle bestehenden Sitzungen werden ungueltig."""
        self._secret = secrets.token_bytes(32)
        tmp = self.secret_path.with_suffix(".tmp")
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(self._secret)
        os.replace(tmp, self.secret_path)
        return self._secret

    @property
    def enabled(self) -> bool:
        return bool(self.settings.get("auth_hash"))

    @property
    def scope(self) -> str:
        return self.settings.get("auth_scope")

    # ------------------------------------------------------------ Sitzungen
    def make_cookie(self) -> str:
        expires = str(int(time.time()) + MAX_AGE)
        sig = hmac.new(self._secret, expires.encode(), hashlib.sha256).hexdigest()
        return f"{expires}.{sig}"

    def cookie_valid(self, value: Optional[str]) -> bool:
        if not value or "." not in value:
            return False
        expires, sig = value.split(".", 1)
        expected = hmac.new(self._secret, expires.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig, expected) and expires.isdigit() and int(expires) > time.time()

    def needs_login(self, path: str, method: str, client: Optional[str], cookie: Optional[str]) -> bool:
        if not self.enabled or client in LOCAL or self.cookie_valid(cookie):
            return False
        if path in _PUBLIC_PATHS or path.startswith(_PUBLIC_PREFIXES):
            return False
        if self.scope == "all":
            return True
        # Stufe "settings": Lesen der Einstellungen bleibt offen (die Oberflaeche braucht z. B. Radio-Favoriten)
        if path == "/api/settings" and method == "GET":
            return False
        return path.startswith(_SETTINGS_PREFIXES)

    # ------------------------------------------------------------ Bremse
    def wait_seconds(self, ip: str) -> int:
        count, until = self._fails.get(ip, (0, 0.0))
        return max(0, int(until - time.time()) + 1) if until > time.time() else 0

    def failed(self, ip: str) -> None:
        count, _ = self._fails.get(ip, (0, 0.0))
        count += 1
        # ab dem 4. Fehlversuch steigende Sperre: 5 s, 10 s, 20 s ... hoechstens 15 Minuten
        delay = 0 if count < 4 else min(900, 5 * 2 ** (count - 4))
        self._fails[ip] = (count, time.time() + delay)
        if len(self._fails) > 1000:
            self._fails.pop(next(iter(self._fails)))

    def succeeded(self, ip: str) -> None:
        self._fails.pop(ip, None)
