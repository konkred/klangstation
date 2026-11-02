"""Hardware und Betriebssystem fuer Optionen > Info: Board, CPU, RAM, Bootlaufwerk, OS.

Alles ohne root lesbar (/proc, /sys, lsblk, lscpu). Was sich nicht aendert, wird einmal ermittelt;
freier Speicher und Belegung des Laufwerks bei jedem Aufruf.
"""
import json
import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("klangstation.sysinfo")

# Platzhalter, die Hersteller in DMI-Feldern stehen lassen
DMI_JUNK = {"", "to be filled by o.e.m.", "default string", "system product name", "system manufacturer",
            "not applicable", "not specified", "none", "unknown", "o.e.m.", "oem", "123456789", "x.x"}
# Uebliche Speichergroessen in GB; MemTotal liegt wegen Kernel/Grafik etwas darunter
RAM_SIZES = [0.5, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384, 512, 768, 1024]
# Merkmale der x86-64-Stufen (Flags aus /proc/cpuinfo)
X86_LEVELS = [
    ("v2", {"cx16", "lahf_lm", "popcnt", "sse4_1", "sse4_2", "ssse3"}),
    ("v3", {"avx", "avx2", "bmi1", "bmi2", "f16c", "fma", "abm", "movbe", "xsave"}),
    ("v4", {"avx512f", "avx512bw", "avx512cd", "avx512dq", "avx512vl"}),
]

_static: Optional[Dict[str, Any]] = None


def _read(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").replace("\x00", "").strip()
    except OSError:
        return ""


def _cmd(*args: str) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5,
                              env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _dmi(name: str) -> str:
    val = _read(f"/sys/class/dmi/id/{name}")
    return "" if val.lower() in DMI_JUNK else val


def _gb(n_bytes: float) -> str:
    gb = n_bytes / 1024 ** 3
    if gb >= 1000:
        return f"{gb / 1024:.1f}".replace(".", ",") + " TB"
    return (f"{gb:.1f}" if gb < 100 else f"{gb:.0f}").replace(".", ",") + " GB"


def _board() -> Dict[str, str]:
    model = _read("/proc/device-tree/model")          # Raspberry Pi und andere ARM-Boards
    if model:
        return {"name": model, "detail": ""}
    vendor, product, version = _dmi("sys_vendor"), _dmi("product_name"), _dmi("product_version")
    if vendor.upper() == "LENOVO" and version:          # Lenovo: Typnummer in product_name, Modell in version
        product = version
    name = product if product.lower().startswith(vendor.lower()) else " ".join(p for p in (vendor, product) if p)
    bvendor, bname = _dmi("board_vendor"), _dmi("board_name")
    detail = " ".join(p for p in (bvendor, bname) if p)
    if not name:
        name, detail = detail, ""
    return {"name": name or "unbekannt", "detail": f"Mainboard {detail}" if detail and detail != name else ""}


def _cpu() -> Dict[str, str]:
    info: Dict[str, str] = {}
    try:
        for f in json.loads(_cmd("lscpu", "-J") or "{}").get("lscpu", []):
            info[f.get("field", "").rstrip(":")] = (f.get("data") or "").strip()
    except ValueError:
        pass
    name = info.get("Model name", "")
    if not name:
        for line in _read("/proc/cpuinfo").splitlines():
            if line.lower().startswith(("model name", "hardware")):
                name = line.split(":", 1)[1].strip()
                break
    for mark in ("(R)", "(TM)", "(tm)"):
        name = name.replace(mark, "")
    name = " ".join(name.split())
    vendor = info.get("Vendor ID", "")
    if vendor and vendor not in ("GenuineIntel", "AuthenticAMD") and vendor.lower() not in name.lower():
        name = f"{vendor} {name}".strip()                # z. B. "ARM Cortex-A72"
    threads = os.cpu_count() or 1
    cores = set()
    for topo in Path("/sys/devices/system/cpu").glob("cpu[0-9]*/topology"):
        cores.add((_read(str(topo / "physical_package_id")), _read(str(topo / "core_id"))))
    parts = [f"{len(cores) or threads} Kerne" + (f", {threads} Threads" if cores and threads != len(cores) else "")]
    khz = _read("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
    if khz.isdigit():
        parts.append(f"bis {int(khz) / 1e6:.1f} GHz".replace(".", ","))
    arch = platform.machine()
    if arch == "x86_64":
        flags = set()
        for line in _read("/proc/cpuinfo").splitlines():
            if line.startswith("flags"):
                flags = set(line.split(":", 1)[1].split())
                break
        level = ""
        for lvl, need in X86_LEVELS:
            if need <= flags:
                level = lvl
            else:
                break
        arch = f"x86-64-{level}" if level else "x86-64"
    parts.append(arch)
    return {"name": name or "unbekannt", "detail": " · ".join(parts)}


def _ram_size(total: int) -> str:
    gb = total / 1024 ** 3
    for size in RAM_SIZES:
        if gb <= size and gb >= size * 0.85:
            return (f"{size:g}".replace(".", ",")) + " GB"
    return _gb(total)


def _disk_kind(disk: Dict[str, Any]) -> str:
    name, tran = disk.get("name", ""), (disk.get("tran") or "").lower()
    if name.startswith("mmcblk"):
        return "eMMC" if _read(f"/sys/block/{name}/device/type") == "MMC" else "SD-Karte"
    if tran == "nvme" or name.startswith("nvme"):
        return "NVMe-SSD"
    if tran == "usb":
        return "USB-Laufwerk"
    if name.startswith(("vd", "xvd")):
        return "virtuelles Laufwerk"
    kind = "Festplatte" if disk.get("rota") else "SSD"
    return f"{tran.upper()}-{kind}" if tran in ("sata", "sas") else kind


def _boot_disk() -> Dict[str, str]:
    source = _cmd("findmnt", "-n", "-o", "SOURCE", "/").strip().split("[")[0]
    fstype = _cmd("findmnt", "-n", "-o", "FSTYPE", "/").strip()
    disk: Dict[str, Any] = {}
    if source.startswith("/dev/"):
        try:
            tree = json.loads(_cmd("lsblk", "-nsJb", "-o", "NAME,TYPE,MODEL,SIZE,TRAN,ROTA", source) or "{}")
        except ValueError:
            tree = {}
        # -s zeigt den Baum umgekehrt: Partition oben, das Laufwerk ganz unten
        stack: List[Dict[str, Any]] = list(tree.get("blockdevices", []))
        while stack:
            node = stack.pop()
            if node.get("type") == "disk":
                disk = node
                break
            stack.extend(node.get("children") or [])
    model = (disk.get("model") or "").strip()
    name = disk.get("name", "")
    if not model and name.startswith("mmcblk"):
        model = _read(f"/sys/block/{name}/device/name")
    parts = []
    if disk:
        parts.append(_disk_kind(disk))
        if disk.get("size"):
            parts.append(_gb(int(disk["size"])))
    title = model or (f"/dev/{name}" if name else source or "unbekannt")
    return {"name": title, "detail": " · ".join(parts), "device": f"/dev/{name}" if name else source,
            "fstype": fstype}


def _os() -> Dict[str, str]:
    rel: Dict[str, str] = {}
    for line in (_read("/etc/os-release") or _read("/usr/lib/os-release")).splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            rel[k] = v.strip().strip('"')
    name = rel.get("PRETTY_NAME") or rel.get("NAME") or platform.system()
    version = rel.get("VERSION_ID", "")
    if rel.get("ID") == "debian" or "debian" in rel.get("ID_LIKE", ""):
        deb = _read("/etc/debian_version")                  # z. B. 13.1 statt 13; Ubuntu: "forky/sid"
        version = deb if deb[:1].isdigit() else version
    if Path("/etc/rpi-issue").exists() and "raspberry" not in name.lower():
        name = f"Raspberry Pi OS ({name})"
    user_bits = 64 if platform.architecture()[0] == "64bit" else 32
    kernel_arch = platform.machine()
    kernel_bits = 64 if kernel_arch in ("x86_64", "aarch64", "ppc64le", "s390x", "riscv64") else 32
    bits = f"{user_bits} Bit"
    if kernel_bits != user_bits:
        bits += f" (Kernel {kernel_bits} Bit)"
    boot = "UEFI" if Path("/sys/firmware/efi").exists() else ("" if Path("/proc/device-tree").exists() else "BIOS")
    return {"name": name, "version": version, "bits": bits, "arch": kernel_arch, "kernel": platform.release(),
            "boot": boot}


def _collect_static() -> Dict[str, Any]:
    return {"board": _board(), "cpu": _cpu(), "disk": _boot_disk(), "os": _os(), "hostname": platform.node()}


def info() -> Dict[str, Any]:
    """Fuer die Info-Seite; das Statische nur beim ersten Mal (lscpu/lsblk)."""
    global _static
    if _static is None:
        try:
            _static = _collect_static()
        except Exception:                               # nie die Einstellungen blockieren
            log.exception("Systeminfo nicht lesbar")
            return {}
    out = json.loads(json.dumps(_static))
    mem = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        if v.strip().endswith("kB"):
            mem[k] = int(v.split()[0]) * 1024
    total = mem.get("MemTotal", 0)
    out["ram"] = {"name": _ram_size(total) if total else "unbekannt",
                  "detail": f"{_gb(mem.get('MemAvailable', 0))} von {_gb(total)} frei" if total else ""}
    try:
        du = shutil.disk_usage("/")
        out["disk"]["usage"] = f"{_gb(du.free)} von {_gb(du.total)} frei"
    except OSError:
        out["disk"]["usage"] = ""
    try:
        up = float(_read("/proc/uptime").split()[0])
    except (ValueError, IndexError):
        up = 0
    d, rest = divmod(int(up), 86400)
    out["uptime"] = (f"{d} T. " if d else "") + f"{rest // 3600} Std. {rest % 3600 // 60} Min."
    return out
