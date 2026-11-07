"""ALSA-Ausgabegeraete erkennen und Konfigurationen fuer die Audio-Dienste erzeugen.

Gelesen wird direkt aus /proc/asound, damit weder PulseAudio noch PipeWire noetig sind.
amixer (alsa-utils) dient nur dazu, stumme Regler einzuschalten und HDMI-Anschluesse zu erkennen.
Geraete werden ueber den Kartennamen adressiert (hw:CARD=Name,DEV=n), das bleibt auch nach
einem Neustart stabil.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

ASOUND = Path("/proc/asound")
_CARD_RE = re.compile(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(.+?)\s+-\s+(.*)$")

# Reihenfolge fuer die automatische Auswahl
_PRIORITY = ["usb", "i2s", "analog", "hdmi", "other"]

# Hochmischen auf 5.1/7.1: ein eigenes ALSA-Geraet (plug mit Verteiltabelle) in ~/.asoundrc des Dienstnutzers,
# das alle Quellen (MPD, AirPlay, Spotify, UPnP, Bluetooth) statt plughw: nutzen
SURROUND_PCM = "ks_surround"
_RC_MARK = "# Automatisch erzeugt von Klangstation"
# Kanalreihenfolge im Geraet: ALSA/HDA-Standard bzw. USB-Audio-Klasse
_ORDER_ALSA = ["FL", "FR", "RL", "RR", "FC", "LFE", "SL", "SR"]
_ORDER_USB = ["FL", "FR", "FC", "LFE", "RL", "RR", "SL", "SR"]
# Anteil von (links, rechts) je Lautsprecher; Hinten/Seite bekommen die Front, Center und Subwoofer die Mitte
_UPMIX = {"FL": (1, 0), "FR": (0, 1), "RL": (1, 0), "RR": (0, 1), "SL": (1, 0), "SR": (0, 1),
          "FC": (0.5, 0.5), "LFE": (0.5, 0.5)}
_channels: Dict[str, int] = {}
_surround: Dict[str, Any] = {}


def _classify(card_id: str, card_name: str, pcm_name: str, is_usb: bool) -> str:
    text = f"{card_id} {card_name} {pcm_name}".lower()
    if is_usb:
        return "usb"
    if "hdmi" in text or "displayport" in text:
        return "hdmi"
    if any(k in text for k in ("headphone", "analog", "bcm2835", "line out", "speaker", "alc", "cs4", "es83")):
        return "analog"
    if any(k in text for k in ("hifiberry", "iqaudio", "allo", "justboom", "i2s", "dac", "snd_rpi", "pcm51", "wm8")):
        return "i2s"
    return "other"


def _amixer(*args: str) -> str:
    try:
        res = subprocess.run(["amixer", *args], capture_output=True, text=True, timeout=5,
                             env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return res.stdout if res.returncode == 0 else ""


def _hdmi_jacks(card_idx: str) -> Dict[str, bool]:
    """HDMI/DisplayPort: ist an PCM-Geraet n ein Monitor/AV-Receiver angeschlossen? (leer = unbekannt)"""
    out: Dict[str, bool] = {}
    current = None
    for line in _amixer("-c", card_idx, "contents").splitlines():
        m = re.search(r"name='HDMI/DP,pcm=(\d+) Jack'", line)
        if m:
            current = m.group(1)
        elif current is not None and ": values=" in line:
            out[current] = line.split("values=", 1)[1].strip() == "on"
            current = None
    return out


def _vc4_connected(port: str) -> Optional[bool]:
    """Raspberry Pi: vc4hdmi hat keinen Jack-Regler - den Anschluss meldet DRM (vc4hdmi0 = HDMI-A-1)."""
    for status in Path("/sys/class/drm").glob(f"card*-HDMI-A-{int(port) + 1}/status"):
        try:
            return status.read_text().strip() == "connected"
        except OSError:
            pass
    return None


# Regler, die auf frisch installierten Systemen ohne Desktop oft stumm oder auf 0 stehen
_MIXER_CONTROLS = ("Master", "PCM", "Speaker", "Headphone", "Line Out", "Front", "IEC958")


def prepare_mixer(device_id: str) -> List[str]:
    """Schaltet stummgeschaltete Regler der Karte ein und stellt sie auf 100 %.

    Die Karte laeuft immer voll, geregelt wird nur in den Quellen (Software-Mixer, Spotify, AirPlay)."""
    m = re.match(r"^hw:CARD=([^,]+)", device_id)
    if not m:
        return []
    card = m.group(1)
    changed: List[str] = []
    blocks = re.split(r"^Simple mixer control ", _amixer("-c", card, "scontents"), flags=re.M)
    for block in blocks[1:]:
        head, _, body = block.partition("\n")
        hm = re.match(r"'(.+)',(\d+)", head)
        # Lautsprecher und Kopfhoerer bleiben beide an, beim Einstecken schaltet der Treiber um (PipeWire stellt das ab)
        if hm and hm.group(1) == "Auto-Mute Mode" and "Item0: 'Disabled'" in body and "'Enabled'" in body:
            _amixer("-c", card, "-q", "sset", f"Auto-Mute Mode,{hm.group(2)}", "Enabled")
            changed.append("Auto-Mute eingeschaltet")
            continue
        if not hm or hm.group(1) not in _MIXER_CONTROLS or not re.search(r"Capabilities:.*\bp(volume|switch)", body):
            continue
        name = f"{hm.group(1)},{hm.group(2)}"
        playback = [ln for ln in body.splitlines() if "Playback" in ln and "[" in ln]
        if any("[off]" in ln for ln in playback):
            _amixer("-c", card, "-q", "sset", name, "unmute")
            changed.append(f"{name} eingeschaltet")
        levels = [int(p) for ln in playback for p in re.findall(r"Playback \d+ \[(\d+)%\]", ln)]
        if levels and any(p != 100 for p in levels):
            _amixer("-c", card, "-q", "sset", name, "100%")
            changed.append(f"{name} auf 100 %")
    return changed


def wireplumber_pids() -> Set[int]:
    """Laufende WirePlumber-Prozesse (Desktop-Sitzungen). Ein neuer setzt die Regler der Karte auf stumm/0 %."""
    pids: Set[int] = set()
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                if (entry / "comm").read_text().strip() == "wireplumber":
                    pids.add(int(entry.name))
            except OSError:
                continue
    return pids


def max_channels(device_id: str) -> Optional[int]:
    """Hoechste Kanalzahl des Geraets (per aplay, ohne Daten). Belegt = unbekannt, wird spaeter erneut versucht."""
    if device_id in _channels:
        return _channels[device_id]
    # Pi-Klinke (bcm2835) meldet 8 Kanaele, die Buchse ist aber Stereo
    if not device_id.startswith("hw:") or device_id.startswith(("hw:CARD=vc4hdmi", "hw:CARD=Headphones,")):
        return None
    try:
        res = subprocess.run(["aplay", "-t", "raw", "-D", device_id, "--dump-hw-params", "/dev/null"],
                             capture_output=True, text=True, timeout=5, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = re.search(r"^CHANNELS:\s*(?:\[\s*\d+\s+(\d+)\s*\]|(\d+))", res.stdout + res.stderr, re.M)
    if not m:
        return None
    _channels[device_id] = int(m.group(1) or m.group(2))
    return _channels[device_id]


def configure_surround(device_id: str, speakers: int, bitperfect: bool) -> int:
    """Legt ks_surround fuer das Geraet an (oder entfernt es). Gibt die aktive Kanalzahl zurueck (2 = Stereo)."""
    _surround.clear()
    rc = Path.home() / ".asoundrc"
    try:
        ours = not rc.exists() or rc.read_text(errors="replace").startswith(_RC_MARK)
    except OSError:
        ours = False
    n = speakers if speakers in (6, 8) else 2
    if bitperfect or not device_id.startswith("hw:") or device_id.startswith("hw:CARD=vc4hdmi") or not ours:
        n = 2
    if n > 2:
        avail = max_channels(device_id)
        # unbekannt (gerade belegt): der Einstellung trauen, die Oberflaeche bietet sie nur bei genug Kanaelen an
        if avail is not None and avail < n:
            n = 2
    if n == 2:
        if ours and rc.exists():
            rc.unlink()
        return 2
    order = (_ORDER_USB if _is_usb(device_id) else _ORDER_ALSA)[:n]
    table = []
    for dst, name in enumerate(order):
        for src, gain in enumerate(_UPMIX[name]):
            if gain:
                table.append(f"    ttable.{src}.{dst} {gain:g}")
    label = {6: "5.1", 8: "7.1"}[n]
    rc.write_text(f"""{_RC_MARK} (Lautsprecher {label}) - Aenderungen werden ueberschrieben
pcm.{SURROUND_PCM} {{
    type plug
    slave {{
        pcm "{device_id}"
        channels {n}
    }}
    # Kanaele im Geraet: {" ".join(order)}
{chr(10).join(table)}
}}
""", encoding="utf-8")
    _surround.update({"device": device_id, "channels": n})
    return n


def _is_usb(device_id: str) -> bool:
    m = re.match(r"^hw:CARD=([^,]+)", device_id)
    return bool(m) and (ASOUND / m.group(1) / "usbid").exists()


def list_outputs() -> List[Dict[str, Any]]:
    outputs: List[Dict[str, Any]] = []
    cards_file = ASOUND / "cards"
    if cards_file.exists():
        lines = cards_file.read_text(errors="replace").splitlines()
        for i, line in enumerate(lines):
            m = _CARD_RE.match(line)
            if not m:
                continue
            idx, card_id, driver, card_name = m.group(1), m.group(2), m.group(3), m.group(4).strip()
            long_name = lines[i + 1].strip() if i + 1 < len(lines) else card_name
            card_dir = ASOUND / f"card{idx}"
            is_usb = (card_dir / "usbid").exists() or "usb" in driver.lower()
            jacks: Optional[Dict[str, bool]] = None
            for pcm in sorted(card_dir.glob("pcm*p")):
                dev = pcm.name[3:-1]
                pcm_name = ""
                info = pcm / "info"
                try:
                    for row in info.read_text(errors="replace").splitlines():
                        if row.startswith("name:"):
                            pcm_name = row.split(":", 1)[1].strip()
                except OSError:
                    pass
                kind = _classify(card_id, card_name, pcm_name, is_usb)
                if card_id.startswith("vc4hdmi"):
                    # Raspberry Pi 4/5: vc4hdmi0 = Buchse HDMI0 (neben USB-C), vc4hdmi1 = HDMI1
                    label = f"HDMI {card_id[7:] or '0'} (Raspberry Pi)"
                elif not pcm_name or pcm_name in card_name:
                    label = card_name
                else:
                    # auch fuer PC-Onboard-Sound mit mehreren HDMI-PCMs auf einer Karte ("HDMI 0", "HDMI 1" ...)
                    label = f"{card_name} – {pcm_name}"
                connected = None
                if card_id.startswith("vc4hdmi"):
                    connected = _vc4_connected(card_id[7:] or "0")
                    if connected is False:
                        label += " (nichts angeschlossen)"
                    elif connected:
                        label += " (Monitor angeschlossen)"
                elif kind == "hdmi":
                    if jacks is None:
                        jacks = _hdmi_jacks(idx)
                    connected = jacks.get(dev)
                    if connected is False:
                        label += " (nichts angeschlossen)"
                    elif connected:
                        label += " (Monitor angeschlossen)"
                outputs.append({
                    "id": f"hw:CARD={card_id},DEV={dev}",
                    "label": label,
                    # siehe alsa_device(): hier laeuft immer die Umrechnung der Karte
                    "detail": long_name + (" · Bit-perfekt hier nicht möglich" if card_id.startswith("vc4hdmi") else ""),
                    "kind": kind,
                    "connected": connected,
                    "channels": max_channels(f"hw:CARD={card_id},DEV={dev}"),
                })
    outputs.append({"id": "default", "label": "ALSA-Standardgerät", "detail": "default", "kind": "other"})
    return outputs


def output_signature() -> str:
    """Billiger Fingerabdruck der Ausgaenge (Karten, Bildschirme, HDMI-Jacks) ohne aplay - aendert er sich,
    wurde etwas an- oder abgesteckt."""
    parts: List[str] = []
    cards_file = ASOUND / "cards"
    try:
        cards = cards_file.read_text(errors="replace")
    except OSError:
        cards = ""
    parts.append(cards)
    for status in sorted(Path("/sys/class/drm").glob("card*-*/status")):
        try:
            parts.append(f"{status.parent.name}={status.read_text().strip()}")
        except OSError:
            pass
    for line in cards.splitlines():
        m = _CARD_RE.match(line)
        if m and any("HDMI" in _pcm_name(p) for p in (ASOUND / f"card{m.group(1)}").glob("pcm*p")):
            parts.append(f"{m.group(1)}:{sorted(_hdmi_jacks(m.group(1)).items())}")
    return "\n".join(parts)


def _pcm_name(pcm: Path) -> str:
    try:
        for row in (pcm / "info").read_text(errors="replace").splitlines():
            if row.startswith("name:"):
                return row.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def resolve(selected: Optional[str]) -> Dict[str, str]:
    outputs = list_outputs()
    for out in outputs:
        if out["id"] == selected:
            return out
    # automatisch nie einen HDMI-/DP-Ausgang ohne angeschlossenes Geraet waehlen
    real = [o for o in outputs if o["id"] != "default" and o.get("connected") is not False]
    # Zusatz-DAC/HAT hat jemand bewusst eingebaut; danach ein erkannter Fernseher/Monitor vor der Klinke
    # (an der Klinke laesst sich nicht feststellen, ob etwas steckt)
    for out in real:
        if out["kind"] in ("usb", "i2s"):
            return out
    for out in real:
        if out["kind"] == "hdmi" and out.get("connected"):
            return out
    for kind in _PRIORITY:
        for out in real:
            if out["kind"] == kind:
                return out
    return outputs[-1]


def alsa_device(device_id: str, bitperfect: bool) -> str:
    """plughw wandelt Formate/Raten um, hw reicht das Signal unveraendert durch."""
    if device_id.startswith("hw:CARD=vc4hdmi"):
        # Raspberry Pi (KMS): HDMI braucht IEC958-Rahmen, die nur das ALSA-"default" der Karte liefert
        return "default:CARD=" + device_id.split("CARD=", 1)[1].split(",", 1)[0]
    if device_id.startswith("hw:") and not bitperfect:
        if _surround.get("device") == device_id:
            return SURROUND_PCM
        return "plug" + device_id
    return device_id


def _q(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def mpd_config(*, data_dir: Path, media_root: Path, port: int, device: str, bitperfect: bool,
               normalize: bool = False) -> str:
    alsa = alsa_device(device, bitperfect)
    if bitperfect:
        output_opts = '    mixer_type     "none"\n    auto_resample  "no"\n    auto_channels  "no"\n    auto_format    "no"\n'
    else:
        output_opts = '    mixer_type     "software"\n'
        if alsa == SURROUND_PCM:
            # Mehrkanal-Dateien erst zu Stereo zusammenmischen, sonst fehlen ihre Zusatzkanaele in der Verteilung
            output_opts += '    format         "*:*:2"\n'
    # Dynamische Angleichung gibt es nur als Startoption; ReplayGain und Ueberblenden setzt core zur Laufzeit
    normalization = "yes" if normalize and not bitperfect else "no"
    return f"""# Automatisch erzeugt von Klangstation - Aenderungen werden ueberschrieben
music_directory     "{_q(str(media_root))}"
playlist_directory  "{_q(str(data_dir / 'playlists'))}"
state_file          "{_q(str(data_dir / 'mpd.state'))}"
sticker_file        "{_q(str(data_dir / 'sticker.sql'))}"
bind_to_address     "127.0.0.1"
port                "{port}"
auto_update         "yes"
follow_outside_symlinks "yes"
follow_inside_symlinks  "yes"
restore_paused      "yes"
log_level           "notice"
filesystem_charset  "UTF-8"
volume_normalization "{normalization}"

database {{
    plugin          "simple"
    path            "{_q(str(data_dir / 'mpd.db'))}"
}}

input {{
    plugin "curl"
}}

# mpg123 und mad lesen beim Einlesen jede MP3 ohne Xing-Header komplett (Laengenbestimmung) - auf
# Netzfreigaben ueber WLAN dauert das Stunden und lastet die Leitung aus. ffmpeg liest nur den Anfang.
decoder {{
    plugin  "mpg123"
    enabled "no"
}}
decoder {{
    plugin  "mad"
    enabled "no"
}}

# ISO-Abbilder auf Sticks nicht als Archiv durchsuchen: libcdio beendet bei einem Lesefehler (Stick
# abgezogen oder ausgehaengt) den ganzen MPD-Prozess per exit().
archive_plugin {{
    name    "iso"
    enabled "no"
}}

audio_output {{
    type           "alsa"
    name           "Klangstation"
    device         "{_q(alsa)}"
{output_opts}}}
"""


def shairport_config(*, name: str, device: str, hook: Path, pipe: Path) -> str:
    alsa = alsa_device(device, False)
    return f"""// Automatisch erzeugt von Klangstation
general = {{
    name = "{_q(name)}";
    output_backend = "alsa";
    default_airplay_volume = 0.0;  // Vorschlag ans Handy, wenn es selbst keinen Wert mitbringt: volle Lautstaerke
}};

sessioncontrol = {{
    run_this_before_play_begins = "{_q(str(hook))} airplay start";
    run_this_after_play_ends = "{_q(str(hook))} airplay stop";
    wait_for_completion = "yes";  // erst abspielen, wenn andere Quellen das Geraet freigegeben haben
    allow_session_interruption = "yes";
    session_timeout = 60;  // neuere shairport-sync-Versionen erlauben nichts darunter
}};

alsa = {{
    output_device = "{_q(alsa)}";
}};

metadata = {{
    enabled = "yes";
    include_cover_art = "yes";
    pipe_name = "{_q(str(pipe))}";
    pipe_timeout = 5000;
}};
"""


def gmediarender_args(*, name: str, device: str, uuid: str, port: int) -> List[str]:
    return [
        "--friendly-name", name,
        "--uuid", uuid,
        "--port", str(port),
        "--output", "gst",
        "--gstout-audiosink", "alsasink",
        "--gstout-audiodevice", alsa_device(device, False),
        "--mime-filter", "audio",
        "--logfile", "stdout",
    ]


def bluealsa_aplay_args(*, device: str) -> List[str]:
    # Software-Lautstaerke: sonst stellt das Handy den Hardware-Mixer und damit alle Quellen lauter/leiser
    return ["--pcm=" + alsa_device(device, False), "--volume=software", "--single-audio"]


def librespot_args(*, name: str, device: str, bitrate: int, hook: Path, sink: Path, cache: Path,
                   port: int) -> List[str]:
    return [
        "--name", name,
        "--device-type", "speaker",
        # nicht "alsa": librespot beendet sich bei belegtem Geraet, ks-spotify-sink wartet stattdessen
        "--backend", "subprocess",
        "--format", "S16",
        "--device", f"{sink} {alsa_device(device, False)}",
        "--bitrate", str(bitrate),
        "--initial-volume", "100",
        "--volume-ctrl", "log",
        "--enable-volume-normalisation",
        "--cache", str(cache),
        "--disable-audio-cache",
        "--zeroconf-port", str(port),
        "--onevent", str(hook),
    ]
