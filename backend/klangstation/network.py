"""Netzwerk: Adapter, IP-Adressen, WLAN, SSH und offene Ports.

Lesen geht ohne root (nmcli, ip, ss, systemctl). Aendern erledigt der root-Hilfsdienst ks-netadmin
(systemd-Socket), der nur genau diese Einstellungen kann. Ohne NetworkManager zeigt Klangstation die
Adressen nur an.
"""
import asyncio
import ipaddress
import json
import logging
import os
import re
import shutil
import time
from typing import Any, Dict, List, Optional, Tuple

from .config import PORT

log = logging.getLogger("klangstation.network")

HELPER_SOCKET = "/run/ks-netadmin.sock"
NO_WIFI = "Kein WLAN-Adapter gefunden. Ein USB-WLAN-Stick genügt, er wird nach dem Einstecken automatisch erkannt."
# Bekannte Ports fuer die Liste in den Optionen
KNOWN_PORTS = {
    ("tcp", 22): "SSH",
    ("tcp", 80): "Weboberfläche",
    ("tcp", 5000): "AirPlay",
    ("udp", 68): "DHCP (Adresse vom Router)",
    ("udp", 546): "DHCPv6 (Adresse vom Router)",
    ("udp", 1900): "UPnP (Gerätesuche)",
    ("udp", 5353): "mDNS (Namen wie klangstation.local)",
    ("tcp", 4070): "Spotify Connect",
    ("tcp", 6600): "Player (MPD)",
    ("tcp", 9090): "Cockpit (Systemverwaltung)",
    ("tcp", 631): "Drucker (CUPS)",
    ("tcp", 3389): "Remotedesktop",
    ("tcp", 5900): "VNC",
}
KIND = {"ethernet": "LAN", "wifi": "WLAN", "bridge": "Brücke", "bond": "Bündel", "vlan": "VLAN", "tun": "VPN",
        "wireguard": "VPN"}
SKIP_TYPES = ("loopback", "wifi-p2p", "bridge-slave")


async def _run(*cmd: str, timeout: float = 10) -> Tuple[int, str]:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"})
    except FileNotFoundError:
        return 127, ""
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, ""
    return proc.returncode or 0, out.decode("utf-8", "replace")


def _split_terse(line: str) -> List[str]:
    """Zeile aus nmcli -t -e yes zerlegen (":" und "\\" sind mit "\\" maskiert)."""
    out, cur, i = [], [], 0
    while i < len(line):
        c = line[i]
        if c == "\\" and i + 1 < len(line):
            cur.append(line[i + 1])
            i += 2
            continue
        if c == ":":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(c)
        i += 1
    out.append("".join(cur))
    return out


def wifi_adapters() -> List[str]:
    try:
        return sorted(n for n in os.listdir("/sys/class/net") if os.path.isdir(f"/sys/class/net/{n}/wireless"))
    except OSError:
        return []


def _security(flags: str) -> str:
    """nmcli-SECURITY ("WPA2 WPA3", "WPA3", "--", "WPA2 802.1X") -> key-mgmt fuer ks-netadmin."""
    if "802.1X" in flags:
        return "enterprise"
    if not flags or flags == "--":
        return "none"
    if "WPA3" in flags and "WPA2" not in flags and "WPA1" not in flags:
        return "sae"
    return "wpa-psk"


class Network:
    def __init__(self) -> None:
        self.nmcli = shutil.which("nmcli") is not None
        self.rev = 0
        self._sig = ""
        # IP-Aenderung, die noch bestaetigt werden muss: {"until": Zeitpunkt, "address": neue Adresse}
        self.pending: Optional[Dict[str, Any]] = None

    # ------------------------------------------------------------ Ueberwachung
    async def changed(self) -> bool:
        """Adapter ein-/ausgesteckt, Adresse oder Verbindung geaendert? (fuer die Optionen live)"""
        code, out = await _run("ip", "-j", "addr", "show")
        try:
            # nur Name, Zustand und Adressen - die Restlaufzeiten der DHCP-Adressen aendern sich staendig
            sig = json.dumps([[l.get("ifname"), l.get("operstate"),
                               sorted(f"{a.get('local')}/{a.get('prefixlen')}" for a in l.get("addr_info", []))]
                              for l in json.loads(out)])
        except ValueError:
            sig = ""
        if self.nmcli:
            _, dev = await _run("nmcli", "-t", "-f", "DEVICE,STATE,CONNECTION", "device")
            sig += dev
        if self.pending and time.time() > self.pending["until"] + 5:
            self.pending = None   # der Hilfsdienst hat zurueckgenommen
            sig += "x"
        if sig != self._sig:
            first = not self._sig
            self._sig = sig
            if not first:
                self.rev += 1
                return True
        return False

    def public(self) -> Dict[str, Any]:
        """Kurzfassung fuer den Zustand: Aenderungszaehler und offene Bestaetigung."""
        pending = None
        if self.pending:
            pending = dict(self.pending, left=max(0, int(self.pending["until"] - time.time())))
        return {"rev": self.rev, "pending": pending}

    # ------------------------------------------------------------ Lesen
    async def info(self) -> Dict[str, Any]:
        adapters, nm_ok = await self._adapters()
        wifi = wifi_adapters()
        out: Dict[str, Any] = {
            "managed": nm_ok,
            "adapters": adapters,
            "wifi": {"adapters": wifi, "hint": "" if wifi else NO_WIFI, "radio": True, "networks": [], "saved": []},
            "ssh": await self._ssh(),
            "ports": await self._ports(),
            "web_port": PORT,
            "hostname": os.uname().nodename,
            "pending": self.public()["pending"],
        }
        if nm_ok:
            _, radio = await _run("nmcli", "-g", "WIFI", "general")
            out["wifi"]["radio"] = radio.strip() == "enabled"
            if wifi and out["wifi"]["radio"]:
                out["wifi"]["networks"] = await self._scan_list()
            out["wifi"]["saved"] = await self._saved_wifi(adapters)
        return out

    async def _adapters(self) -> Tuple[List[Dict[str, Any]], bool]:
        code, out = await _run("ip", "-j", "addr", "show")
        try:
            links = json.loads(out) if code == 0 else []
        except ValueError:
            links = []
        _, routes = await _run("ip", "-j", "-4", "route", "show", "default")
        try:
            gateways = {r.get("dev"): r.get("gateway", "") for r in json.loads(routes or "[]")}
        except ValueError:
            gateways = {}
        nm: Dict[str, Dict[str, Any]] = {}
        nm_ok = False
        if self.nmcli:
            code, text = await _run("nmcli", "-t", "-e", "yes", "-f",
                                    "GENERAL.DEVICE,GENERAL.TYPE,GENERAL.STATE,GENERAL.CONNECTION,GENERAL.CON-UUID,"
                                    "IP4.DNS", "device", "show")
            nm_ok = code == 0
            cur: Dict[str, Any] = {}
            for line in text.splitlines():
                key, _, value = line.partition(":")
                value = value.replace("\\:", ":").replace("\\\\", "\\")
                if key == "GENERAL.DEVICE":
                    cur = nm.setdefault(value, {"dns": []})
                elif key == "GENERAL.TYPE":
                    cur["type"] = value
                elif key == "GENERAL.STATE":
                    cur["state"] = re.sub(r"^\d+ \((.*)\)$", r"\1", value)
                elif key == "GENERAL.CONNECTION":
                    cur["connection"] = value
                elif key == "GENERAL.CON-UUID":
                    cur["uuid"] = value
                elif key.startswith("IP4.DNS") and value:
                    cur["dns"].append(value)
        adapters = []
        for link in links:
            name = link.get("ifname", "")
            info = nm.get(name, {})
            kind = info.get("type") or ("wifi" if os.path.isdir(f"/sys/class/net/{name}/wireless") else
                                        "loopback" if link.get("link_type") == "loopback" else
                                        "ethernet" if link.get("link_type") == "ether" else link.get("link_type", ""))
            if kind in SKIP_TYPES or name.startswith(("veth", "docker", "virbr", "br-")):
                continue
            v4 = [f"{a['local']}/{a['prefixlen']}" for a in link.get("addr_info", []) if a.get("family") == "inet"]
            v6 = [f"{a['local']}/{a['prefixlen']}" for a in link.get("addr_info", [])
                  if a.get("family") == "inet6" and a.get("scope") == "global"]
            speed = ""
            try:
                with open(f"/sys/class/net/{name}/speed", encoding="ascii") as fh:
                    mbit = int(fh.read().strip())
                speed = f"{mbit // 1000} Gbit/s" if mbit >= 1000 else f"{mbit} Mbit/s" if mbit > 0 else ""
            except (OSError, ValueError):
                pass
            adapter = {
                "name": name, "kind": KIND.get(kind, kind or "Netz"), "type": kind,
                "mac": link.get("address", "").upper(), "up": link.get("operstate") == "UP" or bool(v4),
                "state": info.get("state", (link.get("operstate") or "").lower()),
                "connection": info.get("connection", ""), "uuid": info.get("uuid", ""),
                "ipv4": v4, "ipv6": v6, "gateway": gateways.get(name, ""), "dns": info.get("dns", []),
                "speed": speed, "usb": "/usb" in os.path.realpath(f"/sys/class/net/{name}/device"),
                "method": "", "editable": False,
            }
            if nm_ok and adapter["uuid"] and kind in ("ethernet", "wifi"):
                code, cfg = await _run("nmcli", "-g", "ipv4.method,ipv4.addresses,ipv4.gateway,ipv4.dns",
                                       "connection", "show", "uuid", adapter["uuid"])
                # leere Felder sind leere Zeilen - nur den letzten Zeilenumbruch abschneiden
                values = cfg[:-1].split("\n") if cfg.endswith("\n") else cfg.split("\n")
                if code == 0 and len(values) == 4:
                    adapter["method"] = values[0]
                    adapter["config"] = {"address": values[1].split(",")[0].strip(), "gateway": values[2],
                                         "dns": [d.strip() for d in values[3].split(",") if d.strip()]}
                    adapter["editable"] = values[0] in ("auto", "manual")
            if kind == "wifi" and nm_ok and adapter["connection"]:
                adapter["ssid"] = await self._active_ssid(name)
            adapters.append(adapter)
        # verbundene zuerst, LAN vor WLAN, sonst nach Name
        order = {"ethernet": 0, "wifi": 1}
        adapters.sort(key=lambda a: (not a["ipv4"], order.get(a["type"], 2), a["name"]))
        return adapters, nm_ok

    async def _active_ssid(self, dev: str) -> str:
        code, out = await _run("nmcli", "-t", "-e", "yes", "-f", "IN-USE,SSID,SIGNAL", "device", "wifi", "list",
                               "ifname", dev, "--rescan", "no")
        for line in out.splitlines():
            parts = _split_terse(line)
            if len(parts) >= 2 and parts[0] == "*":
                return parts[1]
        return ""

    async def _scan_list(self) -> List[Dict[str, Any]]:
        code, out = await _run("nmcli", "-t", "-e", "yes", "-f", "IN-USE,SSID,SIGNAL,SECURITY,FREQ,DEVICE",
                               "device", "wifi", "list", "--rescan", "no")
        best: Dict[str, Dict[str, Any]] = {}
        for line in out.splitlines():
            parts = _split_terse(line)
            if len(parts) < 6 or not parts[1]:
                continue
            in_use, ssid, signal, sec, freq, dev = parts[:6]
            entry = {"ssid": ssid, "signal": int(signal) if signal.isdigit() else 0, "security": _security(sec),
                     "secured": sec not in ("", "--"), "band": "5 GHz" if freq.startswith(("5", "6")) else "2,4 GHz",
                     "active": in_use == "*", "device": dev}
            old = best.get(ssid)
            if not old or entry["active"] or (entry["signal"] > old["signal"] and not old["active"]):
                best[ssid] = entry
        return sorted(best.values(), key=lambda e: (not e["active"], -e["signal"], e["ssid"].lower()))[:40]

    async def _saved_wifi(self, adapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        code, out = await _run("nmcli", "-t", "-e", "yes", "-f", "NAME,UUID,TYPE,DEVICE", "connection", "show")
        saved = []
        for line in out.splitlines():
            parts = _split_terse(line)
            if len(parts) >= 4 and parts[2] == "802-11-wireless":
                c, ssid = await _run("nmcli", "-g", "802-11-wireless.ssid", "connection", "show", "uuid", parts[1])
                saved.append({"name": parts[0], "uuid": parts[1], "device": parts[3],
                              "ssid": ssid.strip().replace("\\:", ":") or parts[0]})
        return saved

    async def _ssh(self) -> Dict[str, Any]:
        for name in ("ssh", "sshd"):
            code, out = await _run("systemctl", "list-unit-files", "--no-legend", f"{name}.service")
            if code == 0 and out.strip():
                _, active = await _run("systemctl", "is-active", f"{name}.service", f"{name}.socket")
                _, enabled = await _run("systemctl", "is-enabled", f"{name}.service", f"{name}.socket")
                return {"installed": True, "active": "active" in active.split(),
                        "enabled": "enabled" in enabled.split()}
        return {"installed": False, "active": False, "enabled": False}

    async def _ports(self) -> List[Dict[str, Any]]:
        code, out = await _run("ss", "-Htlnu")
        found: Dict[Tuple[str, int], Dict[str, Any]] = {}
        for line in out.splitlines():
            cols = line.split()
            if len(cols) < 5:
                continue
            proto, local = cols[0], cols[4]
            host, _, port = local.rpartition(":")
            host = host.split("%")[0].strip("[]")
            if not port.isdigit():
                continue
            try:
                if host not in ("*", "0.0.0.0", "::") and ipaddress.ip_address(host).is_link_local:
                    continue
                local_only = host not in ("*", "0.0.0.0", "::") and ipaddress.ip_address(host).is_loopback
            except ValueError:
                local_only = False
            key = (proto, int(port))
            if local_only and key not in KNOWN_PORTS:
                continue
            name = "Weboberfläche (Klangstation)" if key == ("tcp", PORT) else KNOWN_PORTS.get(key, "")
            if key[0] == "tcp" and 49494 <= key[1] <= 49504:
                name = "UPnP/DLNA"
            entry = found.setdefault(key, {"proto": proto.upper(), "port": int(port), "name": name or "anderes Programm",
                                           "local": True})
            entry["local"] = entry["local"] and local_only
        return sorted(found.values(), key=lambda p: (p["port"], p["proto"]))

    # ------------------------------------------------------------ Aendern (root-Hilfsdienst)
    async def helper(self, request: Dict[str, Any], timeout: float = 90) -> Dict[str, Any]:
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_unix_connection(HELPER_SOCKET), timeout=5)
        except (OSError, asyncio.TimeoutError):
            return {"ok": False, "error": "Netzwerk-Dienst fehlt – bitte install.sh erneut ausführen"}
        try:
            writer.write((json.dumps(request) + "\n").encode())
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), timeout=timeout)
            return json.loads(line or b"{}") or {"ok": False, "error": "Keine Antwort vom Netzwerk-Dienst"}
        except asyncio.TimeoutError:
            return {"ok": False, "error": "Zeitüberschreitung"}
        except (OSError, ValueError) as exc:
            return {"ok": False, "error": f"Netzwerk-Dienst: {exc}"}
        finally:
            writer.close()

    async def action(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {"wifi_connect", "wifi_forget", "wifi_radio", "wifi_scan", "wifi_up", "wifi_down",
                   "ipv4", "ipv4_confirm", "ipv4_revert", "ssh", "port"}
        if action not in allowed:
            raise ValueError("Unbekannte Aktion")
        if not self.nmcli and action.startswith(("wifi", "ipv4")):
            raise ValueError("NetworkManager fehlt – Netzwerk lässt sich hier nur anzeigen")
        request = dict(data, action=action)
        res = await self.helper(request)
        if not res.get("ok"):
            raise ValueError(res.get("error") or "Fehlgeschlagen")
        if action == "ipv4":
            address = str(data.get("address", "")) if data.get("method") == "manual" else ""
            self.pending = {"until": time.time() + int(res.get("seconds", 120)), "address": address,
                            "uuid": data.get("uuid")}
        elif action in ("ipv4_confirm", "ipv4_revert"):
            self.pending = None
        if action == "wifi_scan":
            await asyncio.sleep(3)   # nmcli rescan kehrt sofort zurueck, die Liste fuellt sich danach
        self.rev += 1
        return res
