"""Bluetooth-Empfaenger: Kopplung, Zustand und AVRCP-Steuerung ueber BlueZ und bluez-alsa (D-Bus).

Der Ton selbst laeuft ueber bluealsa (Systemdienst) und bluealsa-aplay, das
Klangstation mit dem gewaehlten Ausgabegeraet startet.

Hinweis: kein "from __future__ import annotations" - dbus-next liest die
D-Bus-Signaturen aus den Annotationen der Agent-Methoden.
"""
import logging
import os
import time
from typing import Any, Dict, List, Optional

try:
    from dbus_next import BusType, Message, MessageType, Variant
    from dbus_next.aio import MessageBus
    from dbus_next.errors import DBusError
    from dbus_next.service import ServiceInterface, method
except ImportError:  # Entwicklung ohne dbus-next
    MessageBus = None  # type: ignore[assignment,misc]
    ServiceInterface = object  # type: ignore[assignment,misc]

    def method():  # type: ignore[no-redef]
        return lambda fn: fn

from .airplay import _SUFFIX

log = logging.getLogger("klangstation.bluetooth")

AGENT_PATH = "/klangstation/agent"
PAIRING_SECONDS = 120
_STATUS = {"playing": "play", "paused": "pause"}
NO_ADAPTER = "Kein Bluetooth-Adapter gefunden. Ein USB-Bluetooth-Stick genügt, er wird nach dem Einstecken automatisch erkannt."


def _explain(exc: Exception) -> str:
    """D-Bus-Fehler in eine verstaendliche Meldung uebersetzen."""
    name = getattr(exc, "type", "") or ""
    if name in ("org.freedesktop.DBus.Error.NameHasNoOwner", "org.freedesktop.DBus.Error.ServiceUnknown"):
        # bluetoothd laeuft nicht - ohne Adapter startet systemd ihn gar nicht erst
        try:
            has_adapter = bool(os.listdir("/sys/class/bluetooth"))
        except OSError:
            has_adapter = False
        if not has_adapter:
            return NO_ADAPTER
        return "Der Bluetooth-Dienst (bluetoothd) läuft nicht. Abhilfe: sudo systemctl restart bluetooth"
    if isinstance(exc, (FileNotFoundError, ConnectionError)):
        return "Der Systembus (D-Bus) ist nicht erreichbar."
    return str(exc) or exc.__class__.__name__


def _v(props: Dict[str, Any], key: str, default: Any = None) -> Any:
    value = props.get(key)
    return value.value if value is not None and hasattr(value, "value") else (default if value is None else value)


class Agent(ServiceInterface):
    """Koppeln nur im Kopplungsfenster; danach verbinden sich nur vertraute Geraete."""

    def __init__(self, bt: "Bluetooth"):
        super().__init__("org.bluez.Agent1")
        self.bt = bt

    def _check(self, device: str) -> None:
        if not self.bt.pairing:
            log.info("Kopplung von %s abgelehnt (Kopplungsfenster geschlossen)", device)
            raise DBusError("org.bluez.Error.Rejected", "Kopplung ist gerade nicht erlaubt")

    @method()
    def Release(self):  # noqa: N802
        pass

    @method()
    def RequestPinCode(self, device: "o") -> "s":  # noqa: N802,F821
        self._check(device)
        return "0000"

    @method()
    def RequestPasskey(self, device: "o") -> "u":  # noqa: N802,F821
        self._check(device)
        return 0

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: N802,F821
        pass

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # noqa: N802,F821
        pass

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: N802,F821
        self._check(device)

    @method()
    def RequestAuthorization(self, device: "o"):  # noqa: N802,F821
        self._check(device)

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: N802,F821
        if not (self.bt.pairing or self.bt.devices.get(device, {}).get("trusted")):
            raise DBusError("org.bluez.Error.Rejected", "Geraet ist nicht gekoppelt")

    @method()
    def Cancel(self):  # noqa: N802
        pass


class Bluetooth:
    def __init__(self) -> None:
        self.bus: Optional[Any] = None
        self.adapter: Optional[str] = None
        self.pairing_until = 0.0
        self.devices: Dict[str, Dict[str, Any]] = {}
        self.active: Optional[str] = None      # Geraet, von dem gerade Ton kommt
        self.player: Dict[str, Any] = {}
        self.error = ""
        self.name = ""
        self._bluez_owner = ""   # eindeutiger D-Bus-Name von bluetoothd bei der Agent-Anmeldung
        self._paired_before: set = set()   # beim Oeffnen des Kopplungsfensters schon gekoppelte Geraete
        self.just_paired: Optional[str] = None
        self.just_paired_at = 0.0

    @property
    def available(self) -> bool:
        return self.bus is not None and self.adapter is not None

    def adapter_removed(self) -> bool:
        """USB-Stick abgezogen? Dann gilt Bluetooth wieder als nicht verfuegbar (Neuversuch erkennt ihn wieder)."""
        if not self.adapter or os.path.exists("/sys/class/bluetooth/" + self.adapter.rsplit("/", 1)[-1]):
            return False
        log.warning("Bluetooth-Adapter %s wurde entfernt", self.adapter)
        self.adapter = None
        self.active = None
        self.player = {}
        self.devices = {}
        self.error = NO_ADAPTER
        return True

    @property
    def pairing(self) -> bool:
        return time.time() < self.pairing_until

    @property
    def streaming(self) -> bool:
        return self.active is not None

    # ------------------------------------------------------------ D-Bus-Hilfen
    async def _call(self, dest: str, path: str, iface: str, member: str, sig: str = "", body: Optional[List] = None):
        reply = await self.bus.call(Message(destination=dest, path=path, interface=iface, member=member,
                                            signature=sig, body=body or []))
        if reply.message_type == MessageType.ERROR:
            raise DBusError(reply.error_name, reply.body[0] if reply.body else "")
        return reply.body

    async def _set(self, path: str, iface: str, prop: str, sig: str, value: Any) -> None:
        await self._call("org.bluez", path, "org.freedesktop.DBus.Properties", "Set", "ssv",
                         [iface, prop, Variant(sig, value)])

    # ------------------------------------------------------------ Start
    async def start(self, name: str) -> None:
        if MessageBus is None:
            self.error = "Das Python-Paket dbus-next fehlt."
            return
        self.name = name
        previous = self.error
        try:
            if self.bus is None:
                self.bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                self.bus.export(AGENT_PATH, Agent(self))
            owner = await self._bluez_name_owner()
            if owner != self._bluez_owner:
                # bluetoothd vergisst Agenten bei einem Neustart: dann neu anmelden
                await self._call("org.bluez", "/org/bluez", "org.bluez.AgentManager1", "RegisterAgent", "os",
                                 [AGENT_PATH, "NoInputNoOutput"])
                await self._call("org.bluez", "/org/bluez", "org.bluez.AgentManager1", "RequestDefaultAgent", "o",
                                 [AGENT_PATH])
                self._bluez_owner = owner
            objs = (await self._call("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"))[0]
            self.adapter = next((p for p, ifaces in sorted(objs.items()) if "org.bluez.Adapter1" in ifaces), None)
            if not self.adapter:
                self.error = NO_ADAPTER
                if previous != self.error:
                    log.warning("Bluetooth nicht verfuegbar: %s", self.error)
                return
            await self.set_name(name)
            await self._set(self.adapter, "org.bluez.Adapter1", "Powered", "b", True)
            await self._set(self.adapter, "org.bluez.Adapter1", "Pairable", "b", True)
            self.error = ""
            if previous:
                log.info("Bluetooth-Adapter gefunden: %s", self.adapter)
        except Exception as exc:  # noqa: BLE001 - kein Bluetooth ist kein Grund zum Absturz
            self.error = _explain(exc)
            if previous != self.error:   # beim Neuversuch alle paar Sekunden nicht jedes Mal melden
                log.warning("Bluetooth nicht verfuegbar: %s (%s)", self.error, exc)

    async def _bluez_name_owner(self) -> str:
        return (await self._call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                 "GetNameOwner", "s", ["org.bluez"]))[0]

    async def ensure_registered(self) -> None:
        """Nach einem Neustart von bluetoothd Agent, Name und Kopplungsbereitschaft wiederherstellen."""
        if self.bus is None:
            return
        try:
            owner = await self._bluez_name_owner()
        except DBusError:
            return  # bluetoothd laeuft gerade nicht
        if owner != self._bluez_owner:
            log.info("bluetoothd wurde neu gestartet, melde Kopplungs-Agent neu an")
            await self.start(self.name)

    async def set_name(self, name: str) -> None:
        if self.adapter:
            await self._set(self.adapter, "org.bluez.Adapter1", "Alias", "s", name)

    # ------------------------------------------------------------ Zustand
    async def poll(self) -> None:
        objs = (await self._call("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects"))[0]
        devices: Dict[str, Dict[str, Any]] = {}
        players: Dict[str, Dict[str, Any]] = {}
        transports: Dict[str, Dict[str, Any]] = {}
        for path, ifaces in objs.items():
            if "org.bluez.Device1" in ifaces:
                d = ifaces["org.bluez.Device1"]
                devices[path] = {"path": path, "name": _v(d, "Alias", ""), "address": _v(d, "Address", ""),
                                 "paired": bool(_v(d, "Paired", False)), "trusted": bool(_v(d, "Trusted", False)),
                                 "connected": bool(_v(d, "Connected", False)), "icon": _v(d, "Icon", "")}
            if "org.bluez.MediaPlayer1" in ifaces:
                players[path] = ifaces["org.bluez.MediaPlayer1"]
            if "org.bluez.MediaTransport1" in ifaces:
                transports[path] = ifaces["org.bluez.MediaTransport1"]

        # Neu gekoppelte Geraete vertrauen, damit sie sich spaeter ohne Kopplungsfenster verbinden
        for path, d in devices.items():
            if d["paired"] and not d["trusted"]:
                try:
                    await self._set(path, "org.bluez.Device1", "Trusted", "b", True)
                    d["trusted"] = True
                except DBusError as exc:
                    log.info("Konnte %s nicht als vertraut markieren: %s", d["name"], exc)
        self.devices = devices

        # Neues Geraet gekoppelt: Kopplungsfenster sofort schliessen, damit der Pi nicht laenger sichtbar bleibt
        if self.pairing:
            new = [d for p, d in devices.items() if d["paired"] and p not in self._paired_before]
            if new:
                await self.set_pairing(False)
                self.just_paired, self.just_paired_at = new[0]["name"] or new[0]["address"], time.time()
                log.info("%s gekoppelt, Kopplungsfenster geschlossen", self.just_paired)

        # Ton laeuft, wenn eine A2DP-Sink-PCM von bluealsa "Running" ist (bluez-alsa 4.x: ObjectManager + PCM1)
        active = None
        try:
            pcms = (await self._call("org.bluealsa", "/org/bluealsa", "org.freedesktop.DBus.ObjectManager",
                                     "GetManagedObjects"))[0]
            for ifaces in pcms.values():
                props = ifaces.get("org.bluealsa.PCM1")
                if not props:
                    continue
                if str(_v(props, "Transport", "")).upper().startswith("A2DP-SINK") and _v(props, "Running", False):
                    active = _v(props, "Device")
            if self.error.startswith("bluealsa"):
                self.error = ""
        except DBusError as exc:
            self.error = f"bluealsa: {exc}"
        self.active = active

        # AVRCP: Titeldaten und Status vom Geraet, das verbunden ist (bevorzugt das spielende)
        connected = [p for p, d in devices.items() if d["connected"]]
        source = active or (connected[0] if connected else None)
        info: Dict[str, Any] = {}
        if source:
            player_path = next((p for p in players if p.startswith(source + "/")), None)
            if player_path:
                pl = players[player_path]
                track = _v(pl, "Track", {}) or {}
                position = int(_v(pl, "Position", 0) or 0) / 1000.0
                old = self.player
                at = old.get("at", time.time()) if old.get("raw_position") == position else time.time()
                duration = int(_v(track, "Duration", 0) or 0)
                if duration >= 0xFFFFFFFF or duration > 24 * 3600 * 1000:
                    duration = 0  # AVRCP: 0xFFFFFFFF = Laenge unbekannt
                info = {"player": player_path, "state": _STATUS.get(_v(pl, "Status", ""), "stop"),
                        "avrcp": _v(pl, "Status", ""),
                        # Apple Music haengt wie bei AirPlay z. B. " • Video verfügbar" an den Interpreten
                        "title": _v(track, "Title", ""), "artist": _SUFFIX.sub("", _v(track, "Artist", "")),
                        "album": _v(track, "Album", ""), "duration": duration / 1000.0,
                        "raw_position": position, "at": at}
            transport = next((t for p, t in transports.items() if p.startswith(source + "/")), None)
            volume = _v(transport, "Volume") if transport else None
            info.update({"device": source, "device_name": devices.get(source, {}).get("name", ""),
                         "transport": next((p for p in transports if p.startswith(source + "/")), None),
                         "volume": round(int(volume) / 127 * 100) if volume is not None else -1})
            if active:
                # Kommt Ton an, spielt das Geraet - viele Laptops/Browser melden per AVRCP trotzdem "stopped"
                info["state"] = "play"
        self.player = info

    def position(self) -> float:
        p = self.player
        pos = p.get("raw_position", 0.0)
        if p.get("state") == "play" and p.get("at"):
            pos += time.time() - p["at"]
        return min(pos, p["duration"]) if p.get("duration") else pos

    # ------------------------------------------------------------ Aktionen
    async def set_pairing(self, enabled: bool) -> None:
        if not self.adapter:
            raise ValueError(self.error or "Bluetooth ist nicht verfuegbar")
        if enabled:
            self._paired_before = {p for p, d in self.devices.items() if d["paired"]}
            self.just_paired = None
        self.pairing_until = time.time() + PAIRING_SECONDS if enabled else 0.0
        await self._set(self.adapter, "org.bluez.Adapter1", "DiscoverableTimeout", "u", PAIRING_SECONDS)
        await self._set(self.adapter, "org.bluez.Adapter1", "Discoverable", "b", enabled)

    async def control(self, action: str) -> None:
        """AVRCP an das Handy: Play, Pause, Stop, Next, Previous."""
        player = self.player.get("player")
        if not player:
            raise ValueError("Das verbundene Geraet unterstuetzt keine Fernsteuerung")
        await self._call("org.bluez", player, "org.bluez.MediaPlayer1", action)

    async def set_volume(self, percent: int) -> None:
        transport = self.player.get("transport")
        if not transport:
            raise ValueError("Lautstaerke wird am Geraet eingestellt")
        await self._set(transport, "org.bluez.MediaTransport1", "Volume", "q", round(max(0, min(100, percent)) * 127 / 100))

    async def disconnect(self, path: str) -> None:
        await self._call("org.bluez", path, "org.bluez.Device1", "Disconnect")

    async def remove(self, path: str) -> None:
        if not self.adapter or path not in self.devices:
            raise ValueError("Unbekanntes Geraet")
        await self._call("org.bluez", self.adapter, "org.bluez.Adapter1", "RemoveDevice", "o", [path])

    def public(self) -> Dict[str, Any]:
        return {
            "available": self.available,
            "error": self.error,
            "pairing": self.pairing,
            "pairing_left": max(0, int(self.pairing_until - time.time())),
            # eine Minute lang anzeigen, welches Geraet gerade gekoppelt wurde
            "just_paired": self.just_paired if time.time() - self.just_paired_at < 60 else None,
            "devices": [{k: d[k] for k in ("path", "name", "address", "connected", "icon")}
                        for d in self.devices.values() if d["paired"]],
        }
