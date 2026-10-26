"""Audio-CDs verlustfrei als FLAC sichern (cdparanoia + flac).

Gerippt wird immer zuerst in DATA_DIR/rip/<Disc-ID>. Danach landen die Dateien entweder im internen
Speicher (MEDIA_ROOT/Lokal) oder - ueber den root-Hilfsdienst ks-netmount - auf einem USB-Datentraeger,
der nur fuer das Kopieren beschreibbar eingehaengt wird.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import time
import unicodedata
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .config import CD_DEVICE, DATA_DIR, MEDIA_ROOT

log = logging.getLogger("klangstation.ripper")

LOCAL_DIR = "Lokal"
RIP_DIR = DATA_DIR / "rip"
FLAC_RATIO = 0.62          # grobe Schaetzung FLAC-Groesse / WAV-Groesse fuer die Platzpruefung
WAV_BYTES_PER_SEC = 176400
# cdparanoia -e: "##: <Code> [<Funktion>] @ <Position in 16-Bit-Woertern>"
_PROGRESS = re.compile(r"\[wrote\] @ (\d+)")
_BAD_CHARS = re.compile(r'[\x00-\x1f\x7f/\\:*?"<>|]')


def safe_name(text: str, fallback: str) -> str:
    """Datei-/Ordnername, der auch auf FAT/exFAT-Sticks funktioniert."""
    text = unicodedata.normalize("NFC", text or "")
    text = _BAD_CHARS.sub("_", text).strip().strip(".").strip()
    return (text[:120].rstrip(" .") or fallback)


def album_folder(cd: Dict[str, Any]) -> str:
    """"Interpret/Album (Jahr)" - ohne MusicBrainz-Treffer ein eindeutiger Platzhalter."""
    if cd.get("lookup") == "found" and cd.get("album"):
        year = (cd.get("date") or "")[:4]
        album = safe_name(cd["album"], "Album") + (f" ({year})" if year.isdigit() else "")
        return safe_name(cd.get("artist") or "", "Verschiedene Interpreten") + "/" + album
    return "Unbekannter Interpret/Audio-CD " + safe_name((cd.get("disc_id") or "")[:8], "ohne Kennung")


def free_bytes(path: Path) -> int:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def estimate_bytes(cd: Dict[str, Any]) -> int:
    seconds = sum(t["duration"] for t in cd.get("tracks", []))
    return int(seconds * WAV_BYTES_PER_SEC * FLAC_RATIO)


class RipError(Exception):
    pass


class Ripper:
    def __init__(self) -> None:
        self.job: Optional[Dict[str, Any]] = None
        self.on_change: Optional[Callable[[], None]] = None
        self._task: Optional[asyncio.Task] = None
        self._proc: Optional[asyncio.subprocess.Process] = None

    @property
    def running(self) -> bool:
        return bool(self._task and not self._task.done())

    def public(self) -> Optional[Dict[str, Any]]:
        if not self.job:
            return None
        out = dict(self.job)
        if out.get("state") == "running" and out.get("started"):
            done = out.get("progress", 0)
            elapsed = time.monotonic() - out["started"]
            out["eta"] = int(elapsed / done - elapsed) if done > 0.03 else None
        out.pop("started", None)
        return out

    def _notify(self) -> None:
        if self.on_change:
            self.on_change()

    def start(self, cd: Dict[str, Any], target: Dict[str, str],
              store: Callable[[Path, str], Awaitable[str]], done: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        """target: {"kind": "local"|"usb", "dir": Ordner unter MEDIA_ROOT, "label": Anzeigename}."""
        if self.running:
            raise ValueError("Es wird schon eine CD gerippt")
        tracks = [dict(t) for t in cd.get("tracks") or []]
        if not tracks:
            raise ValueError("Keine Audio-CD eingelegt")
        need = estimate_bytes(cd)
        RIP_DIR.mkdir(parents=True, exist_ok=True)
        if free_bytes(RIP_DIR) < need + 200 * 2**20:
            raise ValueError(f"Zu wenig Platz im internen Speicher zum Zwischenspeichern "
                             f"(benötigt etwa {need / 2**30:.1f} GB)")
        if free_bytes(MEDIA_ROOT / target["dir"]) < need + 50 * 2**20:
            raise ValueError(f"Zu wenig Platz auf „{target['label']}“ (benötigt etwa {need / 2**30:.1f} GB)")
        self.job = {"state": "running", "disc_id": cd.get("disc_id"), "album": cd.get("album") or "Audio-CD",
                    "track": 0, "tracks": len(tracks), "title": "", "progress": 0.0, "target": target["label"],
                    "folder": album_folder(cd), "error": "", "started": time.monotonic()}
        self._task = asyncio.get_running_loop().create_task(self._run(dict(cd, tracks=tracks), target, store, done))
        self._notify()

    async def cancel(self) -> None:
        if not self.running:
            return
        assert self._task
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass

    async def _run(self, cd, target, store, done) -> None:
        job = self.job
        assert job is not None
        work = RIP_DIR / safe_name(cd.get("disc_id") or "cd", "cd")
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        tracks: List[Dict[str, Any]] = cd["tracks"]
        total_sec = sum(t["duration"] for t in tracks) or 1
        done_sec = 0.0
        try:
            cover = None
            if cd.get("art_path") and os.path.isfile(cd["art_path"]):
                cover = work / "cover.jpg"
                shutil.copyfile(cd["art_path"], cover)
            for i, t in enumerate(tracks, 1):
                title = t.get("title") or f"Titel {t['number']}"
                job.update(track=i, title=title)
                self._notify()
                wav = work / f"{t['number']:02d}.wav"
                flac = work / f"{t['number']:02d} {safe_name(title, 'Titel')}.flac"
                words = max(1, t["duration"] * 75 * 1176)

                def step(pos: int, base=done_sec, dur=t["duration"]) -> None:
                    job["progress"] = min(1.0, (base + dur * min(1.0, pos / words)) / total_sec)

                await self._read_track(t["number"], wav, step)
                await self._encode(wav, flac, cd, t, len(tracks), cover)
                wav.unlink(missing_ok=True)
                done_sec += t["duration"]
                job["progress"] = done_sec / total_sec
                self._notify()
            job.update(title="Wird gespeichert …")
            self._notify()
            # store() liefert den Pfad in der Bibliothek, z. B. "Lokal/Interpret/Album (2001)"
            job["path"] = await store(work, job["folder"])
            job.update(state="done", progress=1.0, title="", folder=job["path"].split("/", 1)[-1])
            log.info("CD gerippt: %s -> %s", job["album"], job["path"])
        except asyncio.CancelledError:
            job.update(state="cancelled", title="")
            log.info("Rippen abgebrochen")
            raise
        except (RipError, OSError) as exc:
            job.update(state="error", error=str(exc), title="")
            log.warning("Rippen fehlgeschlagen: %s", exc)
        finally:
            await self._kill()
            shutil.rmtree(work, ignore_errors=True)
            self._notify()
            try:
                await done(job)
            except Exception:  # noqa: BLE001 - Nacharbeiten duerfen den Ripper nicht mitreissen
                log.exception("Nacharbeiten nach dem Rippen fehlgeschlagen")

    async def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc and proc.returncode is None:
            proc.kill()
            await proc.wait()

    async def _read_track(self, number: int, wav: Path, step: Callable[[int], None]) -> None:
        # Volle Fehlerkorrektur (Standard von cdparanoia); -e liefert maschinenlesbaren Fortschritt
        try:
            self._proc = await asyncio.create_subprocess_exec(
                "cdparanoia", "-d", CD_DEVICE, "-e", "-q", str(number), str(wav),
                stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        except FileNotFoundError:
            raise RipError("cdparanoia ist nicht installiert (install.sh erneut ausführen)")
        assert self._proc.stderr
        tail: List[str] = []
        last = 0.0
        start: Optional[int] = None   # cdparanoia zaehlt ab CD-Anfang, nicht ab Titelanfang
        async for raw in self._proc.stderr:
            line = raw.decode("utf-8", "replace").strip()
            m = _PROGRESS.search(line)
            if m:
                pos = int(m.group(1))
                start = pos if start is None else min(start, pos)
                step(pos - start)
                if time.monotonic() - last > 1:
                    last = time.monotonic()
                    self._notify()
            elif line and not line.startswith("##"):
                tail = (tail + [line])[-3:]
        rc = await self._proc.wait()
        self._proc = None
        if rc != 0 or not wav.exists():
            detail = "; ".join(tail)
            if not os.path.exists(CD_DEVICE) or "no medium" in detail.lower() or "unable to open" in detail.lower():
                raise RipError("Die CD ließ sich nicht mehr lesen (ausgeworfen?)")
            raise RipError(f"Titel {number} ließ sich nicht lesen" + (f": {detail}" if detail else ""))

    async def _encode(self, wav: Path, flac: Path, cd: Dict[str, Any], t: Dict[str, Any], total: int,
                      cover: Optional[Path]) -> None:
        tags = {
            "TITLE": t.get("title") or f"Titel {t['number']}",
            "ARTIST": t.get("artist") or cd.get("artist") or "",
            "ALBUM": cd.get("album") if cd.get("lookup") == "found" else "",
            "ALBUMARTIST": cd.get("artist") or "",
            "DATE": cd.get("date") or "",
            "TRACKNUMBER": str(t["number"]),
            "TRACKTOTAL": str(total),
            "MUSICBRAINZ_ALBUMID": cd.get("mbid") or "",
            "MUSICBRAINZ_DISCID": cd.get("disc_id") or "",
        }
        args = ["flac", "--silent", "-5", "-f", "-o", str(flac)]
        for key, value in tags.items():
            if value:
                args.append(f"--tag={key}={value}")
        if cover:
            args.append(f"--picture={cover}")
        args.append(str(wav))
        try:
            self._proc = await asyncio.create_subprocess_exec(
                *args, stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE)
        except FileNotFoundError:
            raise RipError("flac ist nicht installiert (install.sh erneut ausführen)")
        _, err = await self._proc.communicate()
        rc = self._proc.returncode
        self._proc = None
        if rc != 0:
            raise RipError("FLAC-Umwandlung fehlgeschlagen: " + err.decode("utf-8", "replace").strip()[-200:])


def unique_folder(base: Path, folder: str) -> str:
    """Gibt es den Albumordner schon, wird " (2)", " (3)" ... angehaengt."""
    candidate, n = folder, 2
    while (base / candidate).exists():
        candidate, n = f"{folder} ({n})", n + 1
    return candidate


def store_local(work: Path, folder: str) -> str:
    base = MEDIA_ROOT / LOCAL_DIR
    folder = unique_folder(base, folder)
    dest = base / folder
    dest.mkdir(parents=True)
    for f in sorted(work.iterdir()):
        if f.suffix in (".flac", ".jpg") and f.is_file():
            shutil.move(str(f), dest / f.name)
    return f"{LOCAL_DIR}/{folder}"
