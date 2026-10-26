"""Netzwerkfreigaben (SMB/NFS), vom System unter /media/klangstation/Netz-<Name> eingehaengt.

MPDs eigene storage-Plugins (Befehl "mount") nutzen wir bewusst nicht: libsmbclient ist nicht
threadsicher und bringt MPD beim Einlesen zum Absturz. Einhaengen darf der Dienstbenutzer nicht
selbst - das erledigt der root-Hilfsdienst ks-netmount (systemd-Socket), der nur genau das kann.
Fuer MPD ist die Freigabe danach ein gewoehnlicher Ordner wie ein USB-Stick.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from .config import DATA_DIR, MEDIA_ROOT
from .mpd import MPD, MPDError

log = logging.getLogger("klangstation.shares")

PREFIX = "Netz-"
HELPER_SOCKET = "/run/ks-netmount.sock"
_HOST = re.compile(r"^[A-Za-z0-9\[][A-Za-z0-9._:\[\]-]{0,252}$")
# MPD meldet beim Einlesen jede neue/geaenderte Datei ("update: added Netz-X/...")
_UPDATE_LINE = re.compile(r"update: (?:added|updating) (" + PREFIX + r"[^/]+)/")
AUDIO_EXT = {".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".mp4", ".aac", ".wav", ".aif", ".aiff",
             ".wma", ".ape", ".wv", ".mpc", ".dsf", ".dff", ".alac"}


def _count_audio(root: Path) -> int:
    n = 0
    for _, _, files in os.walk(root):
        n += sum(1 for f in files if os.path.splitext(f)[1].lower() in AUDIO_EXT)
    return n


def mount_name(share: Dict[str, Any]) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", share.get("name", "")).strip("-")[:30] or share["id"]
    return PREFIX + slug


_ERRORS = [
    (("permission denied", "access denied", "logon failure", "nt_status_access", "authentication", "error(13)"),
     "Zugriff verweigert – Benutzer/Passwort prüfen"),
    (("no such file", "not found", "bad network name", "object_name_not_found", "no such directory"),
     "Freigabe nicht gefunden – Namen/Pfad prüfen"),
    (("connection refused",), "Server lehnt die Verbindung ab (läuft dort SMB/NFS?)"),
    (("no route", "unreachable", "timed out", "timeout", "host is down", "antwortet nicht"), "Server nicht erreichbar"),
    (("name or service not known", "could not resolve", "resolve"), "Servername unbekannt"),
    (("operation not supported", "error(95)"), "Server unterstützt die SMB-Version nicht"),
    (("invalid argument", "error(22)"), "Ungültige Angaben – Freigabe als „Musik“ oder „Musik/Alben“ angeben"),
]


def explain(error: str) -> str:
    """mount-/Server-Fehler in eine verstaendliche Meldung uebersetzen."""
    low = error.lower()
    for needles, message in _ERRORS:
        if any(n in low for n in needles):
            return message
    return error or "Einbinden fehlgeschlagen"


async def reachable(share: Dict[str, Any]) -> str:
    """Leer, wenn der SMB-/NFS-Port antwortet, sonst eine Fehlermeldung."""
    host = share["host"].strip("[]")
    port = 2049 if share["type"] == "nfs" else 445
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=4)
        writer.close()
        return ""
    except asyncio.TimeoutError:
        return "Server nicht erreichbar"
    except ConnectionRefusedError:
        return "Server lehnt die Verbindung ab (läuft dort " + ("NFS" if port == 2049 else "SMB") + "?)"
    except OSError as exc:
        return "Servername unbekannt" if "Name or service" in str(exc) or exc.errno in (-2, -3) else "Server nicht erreichbar"


def validate(data: Dict[str, Any], existing: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Prueft und normalisiert eine Freigabe aus der Oberflaeche."""
    share = {
        "id": str(data.get("id") or secrets.token_hex(4)),
        "name": str(data.get("name", "")).strip()[:40],
        "type": data.get("type") if data.get("type") in ("smb", "nfs") else "smb",
        # Windows-Schreibweise (\\server\freigabe\ordner) wie Pfade mit "/" behandeln
        "host": str(data.get("host", "")).strip().replace("\\", "/").strip("/")
                .removeprefix("smb:").removeprefix("nfs:").strip("/"),
        "path": str(data.get("path", "")).strip().replace("\\", "/").strip("/"),
        "user": str(data.get("user", "")).strip()[:100],
        "password": str(data.get("password", ""))[:200],
    }
    if not share["name"]:
        raise ValueError("Bitte einen Namen angeben")
    if not _HOST.match(share["host"]):
        raise ValueError("Ungültiger Servername oder ungültige IP-Adresse")
    if not share["path"] or ".." in share["path"].split("/") or share["path"].startswith("-") \
            or any(c in share["path"] for c in ",\n\r\t"):
        raise ValueError("Bitte die Freigabe angeben (z. B. „Musik“ bzw. bei NFS „/export/musik“)")
    if any(c in share["user"] for c in ",=\n\r") or any(c in share["password"] for c in "\n\r\x00"):
        raise ValueError("Benutzername oder Passwort enthält unzulässige Zeichen")
    if share["type"] == "nfs":
        share["user"] = share["password"] = ""
    old = next((s for s in existing if s["id"] == share["id"]), None)
    if old and not share["password"] and data.get("keep_password", True):
        share["password"] = old.get("password", "")  # Passwort wird der Oberflaeche nie gezeigt
    names = {mount_name(s) for s in existing if s["id"] != share["id"]}
    if mount_name(share) in names:
        raise ValueError("Es gibt schon eine Freigabe mit diesem Namen")
    return share


async def helper(request: Dict[str, Any], timeout: float = 45) -> Dict[str, Any]:
    """Eine Anfrage an den root-Hilfsdienst ks-netmount."""
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(HELPER_SOCKET), timeout=5)
    except (OSError, asyncio.TimeoutError):
        return {"ok": False, "error": "Einbinde-Dienst fehlt – bitte install.sh erneut ausführen"}
    try:
        writer.write((json.dumps(request) + "\n").encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
        return json.loads(line or b"{}") or {"ok": False, "error": "Keine Antwort vom Einbinde-Dienst"}
    except asyncio.TimeoutError:
        return {"ok": False, "error": "Server antwortet nicht"}
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": f"Einbinde-Dienst: {exc}"}
    finally:
        writer.close()


def _mounted() -> Set[str]:
    """Eingehaengte Netzwerkfreigaben laut /proc/mounts (Netz-* direkt unter MEDIA_ROOT)."""
    prefix = str(MEDIA_ROOT).rstrip("/") + "/" + PREFIX
    out = set()
    try:
        with open("/proc/mounts", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                parts = line.split()
                mnt = parts[1].replace("\\040", " ")
                if mnt.startswith(prefix) and "/" not in mnt[len(prefix):] and parts[2] in ("cifs", "smb3", "nfs", "nfs4"):
                    out.add(mnt.rsplit("/", 1)[-1])
    except OSError:
        pass
    return out


class Shares:
    def __init__(self, mpd: MPD):
        self.mpd = mpd
        self.status: Dict[str, Dict[str, Any]] = {}   # id -> {"mounted": bool, "error": str}
        # Freigaben, die MPD gerade einliest: Einhaengename -> {"done": n, "total": n | None}
        self.scanning: Dict[str, Dict[str, Optional[int]]] = {}
        self.on_scan: Optional[Callable[[], None]] = None   # Beginn/Ende/Fortschritt
        self._lock = asyncio.Lock()
        self._legacy_done = False
        self._watch: Optional[asyncio.Task] = None
        self._bg: Set[asyncio.Task] = set()  # Referenz halten, sonst raeumt der GC die Aufgabe weg
        self._mounted_names: Set[str] = set()

    # ------------------------------------------------------------ Einlesen (Scan)
    def start_scan(self, name: str, count: bool = True) -> None:
        """Ab jetzt gilt die Freigabe als "wird eingelesen" - Abspielen davon ist so lange gesperrt."""
        if name in self.scanning:
            return
        self.scanning[name] = {"done": 0, "total": None}
        log.info("Freigabe %s wird eingelesen", name)
        loop = asyncio.get_running_loop()
        if count:
            # Nur Verzeichnisse lesen (keine Dateiinhalte) - geht auch ueber WLAN zuegig
            async def total():
                n = await asyncio.to_thread(_count_audio, Path(MEDIA_ROOT) / name)
                if name in self.scanning:
                    self.scanning[name]["total"] = n
                    self._notify()
            task = loop.create_task(total())
            self._bg.add(task)
            task.add_done_callback(self._bg.discard)
        if not self._watch or self._watch.done():
            self._watch = loop.create_task(self._watch_scan())
        self._notify()

    def on_mpd_line(self, line: str) -> None:
        m = _UPDATE_LINE.search(line)
        if not m:
            return
        name = m.group(1)
        if name not in self._mounted_names:
            return   # z. B. Nachzuegler-Meldungen einer gerade entfernten Freigabe
        if name not in self.scanning:
            self.start_scan(name)   # z. B. MPD liest nach einem Neustart von selbst ein
        self.scanning[name]["done"] = (self.scanning[name]["done"] or 0) + 1

    async def _watch_scan(self) -> None:
        """Fortschritt melden, bis MPD fertig ist (kein "updating_db" mehr im Status)."""
        idle = 0
        while self.scanning:
            await asyncio.sleep(3)
            try:
                status = await asyncio.wait_for(self.mpd.dict("status"), timeout=10)
            except (ConnectionError, MPDError, asyncio.TimeoutError):
                continue
            # kurz nach "update" meldet MPD den Auftrag manchmal noch nicht
            idle = 0 if "updating_db" in status else idle + 1
            if idle >= 2:
                log.info("Einlesen abgeschlossen: %s", ", ".join(sorted(self.scanning)))
                self.scanning.clear()
            self._notify()

    def _notify(self) -> None:
        if self.on_scan:
            self.on_scan()

    def blocked(self, uris: List[str]) -> Optional[str]:
        """Einhaengename, falls eine der Adressen auf einer gerade eingelesenen Freigabe liegt."""
        for uri in uris:
            top = uri.split("/", 1)[0]
            if top in self.scanning:
                return top
        return None

    async def _cleanup_legacy(self) -> None:
        """Reste der frueheren Einbindung ueber MPD entfernen (inkl. Cache-Dateien mit Zugangsdaten im Namen)."""
        if self._legacy_done:
            return
        pairs = await self.mpd.run("listmounts")
        for k, v in pairs:
            if k == "mount" and v.startswith(PREFIX):
                try:
                    await self.mpd.run("unmount", v)
                except MPDError as exc:
                    log.info("MPD-Einbindung %s: %s", v, exc)
        cache = Path(DATA_DIR) / "mpd-cache"
        if cache.is_dir():
            for f in cache.iterdir():
                if f.name.startswith(("smb_", "nfs_")):
                    f.unlink(missing_ok=True)
        self._legacy_done = True

    async def _in_database(self, name: str) -> bool:
        try:
            await self.mpd.run("lsinfo", name)
            return True
        except MPDError:
            return False
        except ConnectionError:
            return True   # unklar - lieber nicht unnoetig neu einlesen

    async def unmount(self, share: Dict[str, Any]) -> None:
        res = await helper({"action": "umount", "name": mount_name(share)})
        if not res.get("ok"):
            log.info("Aushaengen von %s: %s", share["name"], res.get("error"))

    async def sync(self, shares: List[Dict[str, Any]],
                   before_unmount: Optional[Callable[[Set[str]], Awaitable[None]]] = None) -> None:
        """Gewuenschte Freigaben einhaengen, nicht mehr gewuenschte aushaengen."""
        async with self._lock:
            try:
                await self._cleanup_legacy()
            except (ConnectionError, MPDError) as exc:
                log.info("Freigaben: MPD nicht bereit (%s)", exc)
                return
            mounted = await asyncio.to_thread(_mounted)
            wanted = {mount_name(s): s for s in shares}
            stale = {n for n in mounted if n not in wanted}
            if stale:
                if before_unmount:
                    # sonst haelt MPD Dateien offen und das Aushaengen haengt
                    try:
                        await before_unmount(stale)
                    except (ConnectionError, MPDError):
                        pass
                for name in stale:
                    res = await helper({"action": "umount", "name": name})
                    log.info("Freigabe %s ausgehaengt%s", name, "" if res.get("ok") else f" ({res.get('error')})")
            changed = bool(stale)
            for name in stale:
                self.scanning.pop(name, None)
            new: List[str] = []
            for name, share in wanted.items():
                if name in mounted:
                    self.status[share["id"]] = {"mounted": True, "error": ""}
                    if not await self._in_database(name):
                        # Einhaengung blieb ueber einen Neustart erhalten, MPDs Datenbank kennt sie aber nicht
                        # (z. B. Einlesen abgebrochen) - neu einlesen
                        changed = True
                        new.append(name)
                    continue
                # Schnelle Vorpruefung: mount wartet bei toten Servern sonst sehr lange
                reach = await reachable(share)
                if reach:
                    self.status[share["id"]] = {"mounted": False, "error": reach}
                    log.info("Freigabe %s: %s", share["name"], reach)
                    continue
                res = await helper({"action": "mount", "name": name, "type": share["type"], "host": share["host"],
                                     "path": share["path"], "user": share.get("user", ""),
                                     "password": share.get("password", "")})
                if res.get("ok"):
                    self.status[share["id"]] = {"mounted": True, "error": ""}
                    log.info("Freigabe %s eingebunden", share["name"])
                    changed = True
                    new.append(name)
                else:
                    error = explain(str(res.get("error", "")))
                    self.status[share["id"]] = {"mounted": False, "error": error}
                    log.info("Freigabe %s: %s (%s)", share["name"], error, res.get("error"))
            for sid in list(self.status):
                if sid not in {s["id"] for s in shares}:
                    del self.status[sid]
            self._mounted_names = {n for n, s in wanted.items() if self.status.get(s["id"], {}).get("mounted")}
            if changed:
                for name in new:
                    self.start_scan(name)
                try:
                    await self.mpd.run("update")
                except (ConnectionError, MPDError):
                    pass

    async def rescan(self, share: Dict[str, Any]) -> None:
        name = mount_name(share)
        await self.mpd.run("update", name)
        # Neu einlesen meldet nur geaenderte Dateien - Gesamtzahl waere irrefuehrend
        self.start_scan(name, count=False)
