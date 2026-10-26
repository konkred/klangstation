"""Optische Laufwerke: Disc-Erkennung, Inhaltsverzeichnis (TOC), MusicBrainz-Disc-ID, Auswerfen.

Nutzt die Linux-CDROM-ioctls direkt, damit libdiscid oder cd-discid nicht noetig
sind. Abgespielt wird von MPD ueber das cdio_paranoia-Plugin (cdda:///<Titel>).
"""
from __future__ import annotations

import base64
import errno
import hashlib
import os
import struct
import time
from typing import Any, Dict, List, Optional

try:
    import fcntl
except ImportError:  # Nicht-Linux (Entwicklung)
    fcntl = None  # type: ignore[assignment]

CDROMREADTOCHDR = 0x5305
CDROMREADTOCENTRY = 0x5306
CDROMSTOP = 0x5307
CDROMEJECT = 0x5309
CDROM_LOCKDOOR = 0x5329
CDROM_DRIVE_STATUS = 0x5326
CDSL_CURRENT = 0x7FFFFFFF
CDS_NO_DISC, CDS_TRAY_OPEN, CDS_DRIVE_NOT_READY, CDS_DISC_OK = 1, 2, 3, 4
CDROM_LBA = 0x01
CDROM_LEADOUT = 0xAA
CDROM_DATA_TRACK = 0x04
_TOCENTRY = struct.Struct("=BBBxiB3x")  # struct cdrom_tocentry, 12 Bytes

STATUS_NAMES = {0: "unknown", CDS_NO_DISC: "empty", CDS_TRAY_OPEN: "open",
                CDS_DRIVE_NOT_READY: "busy", CDS_DISC_OK: "disc"}


def _open(device: str) -> int:
    return os.open(device, os.O_RDONLY | os.O_NONBLOCK)


def drive_status(device: str) -> Optional[int]:
    """None = kein Laufwerk vorhanden bzw. nicht lesbar."""
    if fcntl is None or not os.path.exists(device):
        return None
    try:
        fd = _open(device)
    except OSError:
        return None
    try:
        return fcntl.ioctl(fd, CDROM_DRIVE_STATUS, CDSL_CURRENT)
    except OSError:
        return None
    finally:
        os.close(fd)


def read_toc(device: str) -> Optional[Dict[str, Any]]:
    """Liest das TOC und berechnet daraus die MusicBrainz-Disc-ID."""
    assert fcntl is not None
    fd = _open(device)
    try:
        hdr = fcntl.ioctl(fd, CDROMREADTOCHDR, bytes(2))
        first, last = hdr[0], hdr[1]
        entries = []
        for number in list(range(first, last + 1)) + [CDROM_LEADOUT]:
            buf = _TOCENTRY.pack(number, 0, CDROM_LBA, 0, 0)
            track, adr_ctrl, _fmt, lba, _mode = _TOCENTRY.unpack(fcntl.ioctl(fd, CDROMREADTOCENTRY, buf))
            entries.append({"number": number, "lba": lba, "data": bool((adr_ctrl >> 4) & CDROM_DATA_TRACK)})
    finally:
        os.close(fd)

    leadout = entries.pop()["lba"]
    audio = [e for e in entries if not e["data"]]
    if not audio:
        return None
    # Enhanced CD: Datentrack hinter den Audiotracks -> Lead-out der Audio-Session
    trailing_data = [e for e in entries if e["data"] and e["number"] > audio[-1]["number"]]
    if trailing_data:
        leadout = trailing_data[0]["lba"] - 11400

    first_audio, last_audio = audio[0]["number"], audio[-1]["number"]
    offsets = {e["number"]: e["lba"] + 150 for e in audio}
    leadout_off = leadout + 150

    tracks: List[Dict[str, Any]] = []
    for i, e in enumerate(audio):
        end = audio[i + 1]["lba"] if i + 1 < len(audio) else leadout
        tracks.append({"number": e["number"], "duration": round((end - e["lba"]) / 75.0, 1),
                       "uri": f"cdda:///{e['number']}"})

    return {
        "disc_id": disc_id(first_audio, last_audio, offsets, leadout_off),
        "toc": " ".join(str(v) for v in [first_audio, last_audio, leadout_off]
                        + [offsets[n] for n in range(first_audio, last_audio + 1) if n in offsets]),
        "tracks": tracks,
    }


def disc_id(first: int, last: int, offsets: Dict[int, int], leadout: int) -> str:
    """Algorithmus nach musicbrainz.org/doc/Disc_ID_Calculation."""
    text = "%02X%02X%08X" % (first, last, leadout)
    text += "".join("%08X" % offsets.get(n, 0) for n in range(1, 100))
    digest = hashlib.sha1(text.encode("ascii")).digest()
    return base64.b64encode(digest).decode().replace("+", ".").replace("/", "_").replace("=", "-")


def eject(device: str) -> None:
    """Schublade oeffnen. Blockierend (bis ca. 10 s) - nur aus einem Thread aufrufen."""
    assert fcntl is not None
    for attempt in range(2):
        fd = _open(device)
        try:
            # Erst den Motor anhalten: Manche USB-Laufwerke ignorieren das Auswerfen bei drehender CD
            # oder brechen dabei mangels Strom kurz vom USB ab
            try:
                fcntl.ioctl(fd, CDROMSTOP)
                time.sleep(1.5)
            except OSError:
                pass
            try:
                fcntl.ioctl(fd, CDROM_LOCKDOOR, 0)
            except OSError as exc:
                if exc.errno == errno.EBUSY:
                    raise OSError(errno.EBUSY, "Das Laufwerk wird von einem anderen Programm benutzt "
                                               "(z. B. vom Desktop) und lässt sich nicht auswerfen")
            fcntl.ioctl(fd, CDROMEJECT)
        finally:
            os.close(fd)
        time.sleep(2)
        if drive_status(device) != CDS_DISC_OK:
            return
    raise OSError(errno.EIO, "Das Laufwerk hat das Auswerfen nicht ausgeführt")
