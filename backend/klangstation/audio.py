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
from typing import Any, Dict, List, Optional

ASOUND = Path("/proc/asound")
_CARD_RE = re.compile(r"^\s*(\d+)\s+\[(\S+)\s*\]:\s*(.+?)\s+-\s+(.*)$")

# Reihenfolge fuer die automatische Auswahl
_PRIORITY = ["usb", "i2s", "analog", "hdmi", "other"]


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


# Regler, die auf frisch installierten Systemen ohne Desktop oft stumm oder auf 0 stehen
_MIXER_CONTROLS = ("Master", "PCM", "Speaker", "Headphone", "Line Out", "Front", "IEC958")


def prepare_mixer(device_id: str) -> List[str]:
    """Schaltet stummgeschaltete Regler der Karte ein und hebt Regler auf 0 % auf 80 %.

    Lautstaerken, die jemand bewusst eingestellt hat (alles ueber 0 %), bleiben unangetastet.
    Klangstation regelt die Lautstaerke selbst (Software-Mixer)."""
    m = re.match(r"^hw:CARD=([^,]+)", device_id)
    if not m:
        return []
    card = m.group(1)
    changed: List[str] = []
    blocks = re.split(r"^Simple mixer control ", _amixer("-c", card, "scontents"), flags=re.M)
    for block in blocks[1:]:
        head, _, body = block.partition("\n")
        hm = re.match(r"'(.+)',(\d+)", head)
        if not hm or hm.group(1) not in _MIXER_CONTROLS or not re.search(r"Capabilities:.*\bp(volume|switch)", body):
            continue
        name = f"{hm.group(1)},{hm.group(2)}"
        playback = [ln for ln in body.splitlines() if "Playback" in ln and "[" in ln]
        if any("[off]" in ln for ln in playback):
            _amixer("-c", card, "-q", "sset", name, "unmute")
            changed.append(f"{name} eingeschaltet")
        levels = [int(p) for ln in playback for p in re.findall(r"\[(\d+)%\]", ln)]
        if levels and max(levels) == 0:
            _amixer("-c", card, "-q", "sset", name, "80%")
            changed.append(f"{name} auf 80 %")
    return changed


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
                if kind == "hdmi" and not card_id.startswith("vc4hdmi"):
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
                })
    outputs.append({"id": "default", "label": "ALSA-Standardgerät", "detail": "default", "kind": "other"})
    return outputs


def resolve(selected: Optional[str]) -> Dict[str, str]:
    outputs = list_outputs()
    for out in outputs:
        if out["id"] == selected:
            return out
    # automatisch nie einen HDMI-/DP-Ausgang ohne angeschlossenes Geraet waehlen
    real = [o for o in outputs if o["id"] != "default" and o.get("connected") is not False]
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
        return "plug" + device_id
    return device_id


def _q(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def mpd_config(*, data_dir: Path, media_root: Path, port: int, device: str, bitperfect: bool) -> str:
    alsa = alsa_device(device, bitperfect)
    if bitperfect:
        output_opts = '    mixer_type     "none"\n    auto_resample  "no"\n    auto_channels  "no"\n    auto_format    "no"\n'
    else:
        output_opts = '    mixer_type     "software"\n'
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


def librespot_args(*, name: str, device: str, bitrate: int, hook: Path, cache: Path, port: int) -> List[str]:
    return [
        "--name", name,
        "--device-type", "speaker",
        "--backend", "alsa",
        "--device", alsa_device(device, False),
        "--bitrate", str(bitrate),
        "--initial-volume", "70",
        "--volume-ctrl", "log",
        "--enable-volume-normalisation",
        "--cache", str(cache),
        "--disable-audio-cache",
        "--zeroconf-port", str(port),
        "--onevent", str(hook),
    ]
