#!/usr/bin/env bash
# Klangstation Installer
# Debian 13 / Raspberry Pi OS (andere Distributionen werden nicht unterstuetzt)
# Architekturen: x86_64, aarch64, armv7l
# Optionen: siehe usage() bzw. ./install.sh --help
set -euo pipefail

PREFIX=/opt/klangstation
DATA=/var/lib/klangstation
MEDIA=/media/klangstation
SVC_USER=klangstation
PORT=
WITH_AIRPLAY=1
WITH_SPOTIFY=1
WITH_UPNP=1
WITH_BLUETOOTH=1
WITH_WIFI=1
SPOTIFY_SOURCE=0
TV_HEADLESS=0
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m  %s\n' "$*" >&2; }
die()  { printf '\033[1;31mFehler:\033[0m %s\n' "$*" >&2; exit 1; }
# Desktop: PackageKit haelt nach dem Start oft die dpkg-Sperre (automatische Updates) -> warten statt abbrechen
apt-get() { command apt-get -o DPkg::Lock::Timeout=600 "$@"; }

usage() {
    cat <<'EOF'
Klangstation installieren bzw. aktualisieren (erneut aufrufen, Einstellungen bleiben erhalten).

Aufruf:  sudo ./install.sh [Optionen]

Ohne Optionen wird alles installiert: lokale Medien, Freigaben, Radio, CD, AirPlay, Spotify,
UPnP und Bluetooth. Die Optionen lassen sich beliebig kombinieren.

  --port <n>
      Weboberflaeche auf Port <n> statt 8080 (Firewall und Kiosk werden angepasst).
      Verwenden, wenn 8080 belegt ist, oder mit --port 80 fuer eine Adresse ohne Port.
      Ohne --port behaelt ein Update den bisherigen Port (auch einen in den Optionen geaenderten).

  --no-airplay
      shairport-sync nicht installieren: kein AirPlay-Lautsprecher.
      Verwenden ohne Apple-Geraete.

  --no-spotify
      librespot nicht installieren: kein Spotify Connect.
      Verwenden ohne Spotify Premium; spart ggf. einen Rust-Build (Raspberry Pi: 20-60 Minuten).

  --no-upnp
      gmediarender nicht installieren: kein UPnP/DLNA-Renderer.
      Verwenden, wenn niemand von Android-Apps, Windows ("Wiedergeben auf") oder NAS abspielt.

  --no-bluetooth
      bluez/bluez-alsa nicht installieren, Bluetooth- und WirePlumber-Konfiguration unveraendert lassen.
      Verwenden ohne Bluetooth-Adapter oder wenn Bluetooth fuer anderes gebraucht wird.

  --no-wifi
      Keine WLAN-Unterstuetzung (NetworkManager-WLAN, wpa_supplicant, Firmware fuer USB-WLAN-Sticks).
      Verwenden, wenn das Geraet nur per Kabel im Netz haengt und kein WLAN-Stick vorgesehen ist.

  --spotify-from-source
      librespot mit Cargo bauen statt aus dem Raspotify-Paketarchiv.
      Verwenden, wenn kein fremdes Paketarchiv eingebunden werden soll.

  --tv-headless
      "Laeuft gerade"-Bildschirm ohne Desktop: installiert cage + chromium und den Dienst
      klangstation-tv, der nach jedem Start im Vollbild auf tty1 laeuft (dort dann kein Login-Prompt).
      Verwenden auf Systemen OHNE Desktop (Pi OS Lite, Server) mit Fernseher/Monitor am HDMI-/DP-
      Ausgang. Mit Desktop nicht noetig - dort startet der Bildschirm nach dem Anmelden von selbst.

  -h, --help
      Diese Hilfe anzeigen.

Hinweis: --no-... verhindert nur die Installation. Bereits vorhandene Programme nutzt Klangstation
weiter; abschalten laesst sich jede Quelle auch unter Optionen > Dienste.

Beispiele:
  sudo ./install.sh                                   # alles, z. B. Raspberry Pi mit Desktop
  sudo ./install.sh --tv-headless --port 80           # Pi OS Lite am Fernseher
  sudo ./install.sh --no-spotify --no-upnp --no-bluetooth
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --port)
            [ $# -ge 2 ] && [[ "$2" =~ ^[0-9]+$ ]] && [ "$2" -ge 1 ] && [ "$2" -le 65535 ] \
                || die "--port braucht eine Portnummer (1-65535)"
            PORT="$2"; shift 2 ;;
        --no-airplay) WITH_AIRPLAY=0; shift ;;
        --no-spotify) WITH_SPOTIFY=0; shift ;;
        --no-upnp) WITH_UPNP=0; shift ;;
        --no-bluetooth) WITH_BLUETOOTH=0; shift ;;
        --no-wifi) WITH_WIFI=0; shift ;;
        --spotify-from-source) SPOTIFY_SOURCE=1; shift ;;
        --tv-headless) TV_HEADLESS=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) die "Unbekannte Option: $1 (Hilfe: ./install.sh --help)" ;;
    esac
done

[ "$(id -u)" -eq 0 ] || die "Bitte mit sudo bzw. als root ausfuehren."
[ -r /etc/os-release ] || die "/etc/os-release fehlt - Distribution unbekannt."
. /etc/os-release
case " ${ID:-} ${ID_LIKE:-} " in
    # vor debian pruefen: Ubuntu und Ableger (Mint, Pop!_OS ...) melden auch ID_LIKE=debian
    *" ubuntu "*) die "Ubuntu und davon abgeleitete Systeme werden nicht unterstuetzt (Browser nur als Snap). Bitte Debian oder Raspberry Pi OS verwenden." ;;
    *" debian "*|*" raspbian "*) ;;
    *" rhel "*|*" fedora "*|*" centos "*) die "${PRETTY_NAME:-$ID} wird nicht mehr unterstuetzt (seit 0.2.14 nur Debian). Bitte Debian 13 oder Raspberry Pi OS verwenden." ;;
    *) die "Nicht unterstuetzte Distribution: ${PRETTY_NAME:-$ID}. Bitte Debian 13 oder Raspberry Pi OS verwenden." ;;
esac
ARCH="$(uname -m)"
# Update ohne --port: bisherigen Port behalten (laesst sich auch unter Optionen > Netzwerk aendern)
if [ -z "$PORT" ]; then
    # || true: bei Erstinstallation fehlt die Unit, sed endet mit 2 (set -e + pipefail wuerde still abbrechen)
    PORT="$(sed -n 's/^Environment=KS_PORT=\([0-9]\+\)$/\1/p' /etc/systemd/system/klangstation.service 2>/dev/null | head -n1 || true)"
    PORT="${PORT:-8080}"
fi
PY=python3
log "System: ${PRETTY_NAME:-$ID} ($ARCH)"

# ------------------------------------------------------------------ librespot aus Quellcode
build_librespot() {
    log "Baue librespot aus dem Quellcode (auf einem Raspberry Pi kann das 20-60 Minuten dauern)..."
    apt-get install -y --no-install-recommends build-essential pkg-config libasound2-dev libssl-dev
    export CARGO_HOME=/root/.cargo RUSTUP_HOME=/root/.rustup
    if ! command -v cargo >/dev/null 2>&1 && [ ! -x "$CARGO_HOME/bin/cargo" ]; then
        curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal
    fi
    export PATH="$CARGO_HOME/bin:$PATH"
    cargo install librespot --locked --features alsa-backend --root "$PREFIX"
}

# ------------------------------------------------------------------ shairport-sync aus Quellcode
build_shairport() {
    log "Baue shairport-sync (klassisches AirPlay) aus dem Quellcode..."
    apt-get install -y --no-install-recommends build-essential git autoconf automake libtool pkg-config \
        libasound2-dev libavahi-client-dev libssl-dev libpopt-dev libconfig-dev
    local tmp; tmp="$(mktemp -d)"
    git clone --depth 1 https://github.com/mikebrady/shairport-sync.git "$tmp/shairport-sync"
    ( cd "$tmp/shairport-sync" && autoreconf -fi && \
      ./configure --prefix=/usr/local --sysconfdir=/etc --with-alsa --with-avahi --with-ssl=openssl --with-metadata && \
      make -j"$(nproc)" && make install )
    rm -rf "$tmp"
}

# ------------------------------------------------------------------ Pakete
install_packages() {
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends python3 python3-venv mpd avahi-daemon avahi-utils ca-certificates curl util-linux \
        v4l-utils cifs-utils nfs-common cdparanoia flac alsa-utils ntfs-3g \
        dosfstools exfatprogs
    # dosfstools/exfatprogs: fsck.vfat bzw. fsck.exfat, sonst prueft systemd FAT- und exFAT-Sticks beim Einhaengen nicht
    # Equalizer (ALSA-Plugin mit den LADSPA-Filtern aus caps); ohne die Pakete bleibt er in der Oberflaeche aus
    apt-get install -y --no-install-recommends libasound2-plugin-equal caps \
        || warn "Equalizer-Pakete nicht installiert - der Equalizer bleibt aus"
    if [ "$TV_HEADLESS" = 1 ]; then
        apt-get install -y --no-install-recommends cage chromium fonts-dejavu-core
    fi
    if [ "$WITH_AIRPLAY" = 1 ]; then
        apt-get install -y --no-install-recommends shairport-sync || build_shairport
    fi
    if [ "$WITH_UPNP" = 1 ]; then
        apt-get install -y --no-install-recommends gmediarender gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
            gstreamer1.0-libav gstreamer1.0-alsa
    fi
    if [ "$WITH_BLUETOOTH" = 1 ]; then
        apt-get install -y --no-install-recommends bluez bluez-alsa-utils
    fi
    if [ "$WITH_WIFI" = 1 ]; then
        # WLAN ueber NetworkManager. Unter Debian laesst NetworkManager Adapter, die ifupdown schon verwaltet,
        # in Ruhe - die Kabelverbindung aendert sich durch die Installation nicht.
        apt-get install -y --no-install-recommends network-manager wpasupplicant iw rfkill
        # Firmware fuer gaengige USB-WLAN-Sticks (Realtek, MediaTek, Atheros) und Intel-Karten, soweit vorhanden
        # (braucht die Komponente non-free-firmware, die Raspberry Pi OS und Debian ab 12 mitbringen)
        local fw="" p
        # nur fehlende Pakete: vorhandene Firmware (am Pi auch die des eingebauten WLAN) nicht nebenbei aktualisieren
        for p in firmware-realtek firmware-mediatek firmware-atheros firmware-iwlwifi; do
            dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q "ok installed" && continue
            # apt-cache show findet auch Namen ohne installierbares Paket, darum den Kandidaten pruefen
            LC_ALL=C apt-cache policy "$p" 2>/dev/null | grep -q 'Candidate: [^(]' && fw="$fw $p"
        done
        # shellcheck disable=SC2086
        [ -z "$fw" ] || apt-get install -y --no-install-recommends $fw || warn "WLAN-Firmware liess sich nicht installieren"
    fi
    if [ "$WITH_SPOTIFY" = 1 ] && ! command -v librespot >/dev/null 2>&1 && [ ! -x "$PREFIX/bin/librespot" ]; then
        local deb_arch; deb_arch="$(dpkg --print-architecture)"
        if [ "$SPOTIFY_SOURCE" = 0 ] && { [ "$deb_arch" = amd64 ] || [ "$deb_arch" = arm64 ] || [ "$deb_arch" = armhf ]; }; then
            log "Installiere librespot ueber das Raspotify-Paketarchiv..."
            curl -fsSL https://dtcooper.github.io/raspotify/key.asc -o /usr/share/keyrings/raspotify_key.asc
            echo "deb [signed-by=/usr/share/keyrings/raspotify_key.asc] https://dtcooper.github.io/raspotify raspotify main" \
                > /etc/apt/sources.list.d/raspotify.list
            apt-get update
            apt-get install -y raspotify || build_librespot
        else
            build_librespot
        fi
    fi
}

install_firewall() {
    if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
        log "Oeffne Ports in firewalld..."
        firewall-cmd --permanent --add-port="${PORT}/tcp"
        firewall-cmd --permanent --add-service=mdns
        firewall-cmd --permanent --add-port=5000/tcp --add-port=6001-6011/udp   # AirPlay
        firewall-cmd --permanent --add-port=4070/tcp                            # Spotify Connect (Zeroconf)
        # UPnP/DLNA (SSDP + Renderer); ist 49494 nach einem schnellen Neustart noch belegt, weicht libupnp nach oben aus
        firewall-cmd --permanent --add-port=1900/udp --add-port=49494-49504/tcp
        firewall-cmd --reload
    elif command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
        log "Oeffne Ports in ufw..."
        ufw allow "${PORT}/tcp"; ufw allow 5353/udp; ufw allow 5000/tcp; ufw allow 6001:6011/udp; ufw allow 4070/tcp
        ufw allow 1900/udp; ufw allow 49494:49504/tcp
    fi
}

# ------------------------------------------------------------------ Ablauf
mkdir -p "$PREFIX"
install_packages

log "Lege Dienstbenutzer '$SVC_USER' an..."
if ! id -u "$SVC_USER" >/dev/null 2>&1; then
    useradd --system --home-dir "$DATA" --no-create-home --shell /usr/sbin/nologin --user-group "$SVC_USER"
fi
# audio/cdrom: Ton und CD; video: HDMI-CEC (/dev/cec*); render/input: Bildschirm ohne Desktop (cage)
for grp in audio cdrom optical video render input; do
    if getent group "$grp" >/dev/null; then usermod -aG "$grp" "$SVC_USER"; fi
done

log "Kopiere Anwendung nach $PREFIX..."
rm -rf "$PREFIX/backend" "$PREFIX/web" "$PREFIX/system"
cp -r "$SRC/backend" "$SRC/web" "$SRC/system" "$SRC/requirements.txt" "$PREFIX/"
find "$PREFIX/backend" -name '__pycache__' -prune -exec rm -rf {} +
# Rechte unabhaengig von der Quelle setzen (ZIP/scp von Windows liefert oft 700/600)
chmod -R u=rwX,go=rX "$PREFIX/backend" "$PREFIX/web" "$PREFIX/system" "$PREFIX/requirements.txt"
for script in hooks/ks-hook ks-automount ks-netmount ks-netadmin ks-tv-kiosk ks-reset-password ks-spotify-sink; do
    sed -i 's/\r$//' "$PREFIX/system/$script"
    chmod 0755 "$PREFIX/system/$script"
done
sed -i "s/@PORT@/${PORT}/" "$PREFIX/system/ks-tv-kiosk"

log "Richte Python-Umgebung ein ($PY)..."
"$PY" -m venv "$PREFIX/venv"
"$PREFIX/venv/bin/pip" install --quiet --upgrade pip
"$PREFIX/venv/bin/pip" install --quiet -r "$PREFIX/requirements.txt"

install -d -o "$SVC_USER" -g "$SVC_USER" -m 0750 "$DATA"
install -d -m 0755 "$MEDIA"
install -d -o "$SVC_USER" -g "$SVC_USER" -m 0755 "$MEDIA/Lokal"

log "Richte automatisches Einhaengen von USB/SD ein..."
install -m 0644 "$PREFIX/system/99-klangstation-automount.rules" /etc/udev/rules.d/
udevadm control --reload-rules || true

# Netzwerkfreigaben: root-Hilfsdienst, den nur der Dienstbenutzer erreicht (Socket mit Gruppe klangstation).
# Er haengt ausschliesslich SMB/NFS lesend unter $MEDIA/Netz-* ein und aus.
log "Richte das Einhaengen von Netzwerkfreigaben ein..."
install -m 0644 "$PREFIX/system/ks-netmount.socket" "$PREFIX/system/ks-netmount@.service" /etc/systemd/system/
# Netzwerk (Optionen > Netzwerk): WLAN, IP-Adressen, SSH und Port aendert ebenfalls nur ein root-Hilfsdienst
install -m 0644 "$PREFIX/system/ks-netadmin.socket" "$PREFIX/system/ks-netadmin@.service" /etc/systemd/system/
rm -rf "$DATA/mpd-cache"   # frueher: Cache von MPDs SMB-Einbindung (enthielt Zugangsdaten im Dateinamen)

# Die Distributionsdienste wuerden das Audiogeraet blockieren - Klangstation startet eigene Instanzen
for unit in mpd.service mpd.socket shairport-sync.service raspotify.service gmediarender.service bluealsa-aplay.service; do
    systemctl disable --now "$unit" >/dev/null 2>&1 || true
done
systemctl enable --now avahi-daemon.service || warn "avahi-daemon liess sich nicht starten (AirPlay/.local-Namen)"
if [ "$WITH_BLUETOOTH" = 1 ]; then
    # bluealsa (Systemdienst) stellt den A2DP-Empfaenger bereit; bluealsa-aplay startet Klangstation selbst.
    # Nur Empfaenger-Rolle (a2dp-sink): sonst kann der Pi auch als Tonquelle fuer andere Geraete auftreten.
    BLUEALSA_BIN="$(command -v bluealsa || echo /usr/bin/bluealsa)"
    install -d /etc/systemd/system/bluealsa.service.d
    printf '[Service]\nExecStart=\nExecStart=%s -S -p a2dp-sink\n' "$BLUEALSA_BIN" \
        > /etc/systemd/system/bluealsa.service.d/klangstation.conf
    # Geraeteklasse Audio/Video > Lautsprecher (0x000414). Ohne das meldet sich der Pi als "Sonstiges"
    # und Windows zeigt ihn nur als "Unbekanntes Geraet" an. Dienst-Bits ergaenzt BlueZ selbst.
    if [ -f /etc/bluetooth/main.conf ]; then
        if grep -qE '^\s*Class\s*=' /etc/bluetooth/main.conf; then
            sed -i -E 's/^\s*Class\s*=.*/Class = 0x000414/' /etc/bluetooth/main.conf
        else
            sed -i -E '0,/^\[General\]/s//[General]\n# Klangstation: als Lautsprecher anmelden\nClass = 0x000414/' /etc/bluetooth/main.conf
        fi
    fi
    # Das hostname-Plugin von BlueZ leitet die Geraeteklasse aus dem Gehaeusetyp ab (PC: "Desktop-Computer")
    # und ueberschreibt damit Class aus main.conf. Den Namen setzt Klangstation ohnehin selbst.
    BLUETOOTHD_BIN="$(for p in /usr/libexec/bluetooth/bluetoothd /usr/lib/bluetooth/bluetoothd; do
                          [ -x "$p" ] && { echo "$p"; break; }; done || true)"
    if [ -n "$BLUETOOTHD_BIN" ]; then
        install -d /etc/systemd/system/bluetooth.service.d
        printf '[Service]\nExecStart=\nExecStart=%s -P hostname\n' "$BLUETOOTHD_BIN" \
            > /etc/systemd/system/bluetooth.service.d/klangstation.conf
    fi
    systemctl daemon-reload
    systemctl enable bluetooth.service bluealsa.service >/dev/null 2>&1 || true
    systemctl restart bluetooth.service bluealsa.service || warn "Bluetooth-Dienste liessen sich nicht starten"
    rfkill unblock bluetooth 2>/dev/null || true
    # Desktop-Systeme: WirePlumber (PipeWire) wuerde Bluetooth-Audio selbst beanspruchen und bluez-alsa
    # leer ausgehen lassen. Rueckgaengig: die beiden Dateien loeschen.
    if [ -d /usr/share/wireplumber ]; then
        log "Ueberlasse Bluetooth-Audio bluez-alsa (WirePlumber-Bluetooth wird abgeschaltet)..."
        install -d /etc/wireplumber/wireplumber.conf.d /etc/wireplumber/bluetooth.lua.d
        cat > /etc/wireplumber/wireplumber.conf.d/90-klangstation-bluetooth.conf <<'EOF'
# Klangstation: Bluetooth-Audio uebernimmt bluez-alsa, nicht die Desktop-Sitzung (WirePlumber >= 0.5)
wireplumber.profiles = {
  main = {
    monitor.bluez = disabled
  }
}
EOF
        # WirePlumber 0.4 (Debian 12 / Raspberry Pi OS Bookworm)
        echo '-- Klangstation: Bluetooth-Audio uebernimmt bluez-alsa' > /etc/wireplumber/bluetooth.lua.d/90-klangstation.lua
        echo 'bluez_monitor.enabled = false' >> /etc/wireplumber/bluetooth.lua.d/90-klangstation.lua
        for user in $(loginctl list-users --no-legend 2>/dev/null | awk '{print $2}'); do
            systemctl --user -M "${user}@" restart wireplumber.service >/dev/null 2>&1 || true
        done
    fi
fi

# Desktop-Systeme: WirePlumber setzt beim Anschlusswechsel (Kopfhoerer ein/aus) und ueber den Lautstaerkeregler
# des Desktops die Regler der Karte (Master/PCM), MPD spielt dann leiser. Im Profil "pro-audio" fasst PipeWire
# Regler und Anschluesse nicht an (Desktop-Ton per Software), Lautsprecher/Kopfhoerer schaltet der Treiber um
# (Auto-Mute, setzt Klangstation). Ein Software-Mixer allein reicht nicht: Dann schaltet PipeWire beim
# Herausziehen den Kopfhoerer stumm, aber den Lautsprecher nicht wieder ein. Rueckgaengig: Datei loeschen.
if [ -d /usr/share/wireplumber ]; then
    install -d /etc/wireplumber/wireplumber.conf.d
    mixer_conf=/etc/wireplumber/wireplumber.conf.d/90-klangstation-mixer.conf
    mixer_new=$(cat <<'EOF'
# Klangstation: PipeWire laesst Regler und Anschluesse der Karten in Ruhe (WirePlumber >= 0.5)
monitor.alsa.rules = [
  {
    matches = [ { device.name = "~alsa_card.*" } ]
    actions = { update-props = { device.profile = "pro-audio" } }
  }
]
EOF
)
    if [ "$(cat "$mixer_conf" 2>/dev/null || true)" != "$mixer_new" ]; then
        log "PipeWire laesst die Regler der Karte in Ruhe (WirePlumber-Profil pro-audio)..."
        printf '%s\n' "$mixer_new" > "$mixer_conf"
        for user in $(loginctl list-users --no-legend 2>/dev/null | awk '{print $2}'); do
            systemctl --user -M "${user}@" restart wireplumber.service >/dev/null 2>&1 || true
        done
    fi
fi

sed "s/@PORT@/${PORT}/" "$PREFIX/system/klangstation.service" > /etc/systemd/system/klangstation.service
# Ports unter 1024 (z. B. 80) darf der Dienstbenutzer nur mit dieser Faehigkeit belegen
if [ "$PORT" -lt 1024 ]; then
    install -d /etc/systemd/system/klangstation.service.d
    printf '[Service]\n# Port unter 1024 (z. B. 80)\nAmbientCapabilities=CAP_NET_BIND_SERVICE\n' \
        > /etc/systemd/system/klangstation.service.d/port.conf
else
    rm -f /etc/systemd/system/klangstation.service.d/port.conf
fi

# "Laeuft gerade"-Bildschirm: mit Desktop per Autostart in der Sitzung, ohne Desktop optional per cage
if [ "$TV_HEADLESS" = 1 ]; then
    log "Richte den Bildschirm ohne Desktop ein (cage)..."
    install -m 0644 "$PREFIX/system/klangstation-tv.service" /etc/systemd/system/klangstation-tv.service
    systemctl enable klangstation-tv.service >/dev/null 2>&1 || true
    # Chromium startet in der Kiosk-Sitzung sonst per Socket-Aktivierung PipeWire/WirePlumber. WirePlumber
    # setzt dann die ALSA-Regler auf seinen eigenen Stand zurueck (HDMI/DP stumm) und belegt die Geraete.
    # Der Bildschirm braucht keinen Ton, Klangstation spielt direkt ueber ALSA.
    install -d -o "$SVC_USER" -g "$SVC_USER" -m 0700 "$DATA/.config" "$DATA/.config/systemd" "$DATA/.config/systemd/user"
    for unit in pipewire.socket pipewire.service pipewire-pulse.socket pipewire-pulse.service wireplumber.service; do
        ln -sfn /dev/null "$DATA/.config/systemd/user/$unit"
    done
elif [ "$(systemctl get-default)" = graphical.target ] && [ -d /etc/xdg/autostart ]; then
    log "Richte den Bildschirm fuer die Desktop-Sitzung ein (Autostart)..."
    install -m 0644 "$PREFIX/system/klangstation-tv.desktop" /etc/xdg/autostart/klangstation-tv.desktop
fi
# Ein Musikserver darf nicht einschlafen: GNOME versetzt den Rechner sonst nach 15 min ohne Eingabe in Bereitschaft
log "Schalte Bereitschaft und Ruhezustand ab..."
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target >/dev/null 2>&1 || true
# Laptop: Zuklappen soll nichts ausloesen (logind wuerde sonst versuchen, in den Ruhezustand zu gehen)
install -d /etc/systemd/logind.conf.d
printf '[Login]\nHandleLidSwitch=ignore\nHandleLidSwitchExternalPower=ignore\nHandleLidSwitchDocked=ignore\n' \
    > /etc/systemd/logind.conf.d/90-klangstation.conf
systemctl kill -s HUP systemd-logind >/dev/null 2>&1 || true
# dhcpcd (Debian ohne Desktop, ifupdown): direkte IPv6-Route ins eigene Netz, sonst bleibt AirPlay stumm
for d in /usr/lib/dhcpcd/dhcpcd-hooks /lib/dhcpcd/dhcpcd-hooks; do
    if [ -d "$d" ]; then
        install -m 0644 "$PREFIX/system/dhcpcd-hook-klangstation" "$d/90-klangstation"
        break
    fi
done
systemctl daemon-reload
install_firewall
systemctl enable --now ks-netmount.socket ks-netadmin.socket
systemctl enable klangstation.service
systemctl restart klangstation.service
if [ "$TV_HEADLESS" = 1 ]; then
    # eine schon laufende Kiosk-Sitzung (samt PipeWire) beenden, damit die Sperren oben greifen
    systemctl stop klangstation-tv.service "user@$(id -u "$SVC_USER").service" >/dev/null 2>&1 || true
    systemctl restart klangstation.service
    systemctl restart klangstation-tv.service || warn "Bildschirm ohne Desktop liess sich nicht starten"
elif [ -f /etc/xdg/autostart/klangstation-tv.desktop ]; then
    # Der Autostart greift erst bei der naechsten Anmeldung: in einer laufenden Sitzung gleich starten
    for session in $(loginctl list-sessions --no-legend 2>/dev/null | awk '{print $1}'); do
        case "$(loginctl show-session "$session" -p Type --value 2>/dev/null || true)" in wayland|x11) ;; *) continue ;; esac
        session_user="$(loginctl show-session "$session" -p Name --value 2>/dev/null || true)"
        [ -n "$session_user" ] || continue
        pgrep -u "$session_user" -x ks-tv-kiosk >/dev/null 2>&1 && continue
        systemd-run --user --machine="$session_user@" --collect --quiet "$PREFIX/system/ks-tv-kiosk" >/dev/null 2>&1 || true
    done
fi

# bereits eingesteckte Datentraeger einhaengen
udevadm trigger --action=add --subsystem-match=block || true

HOST="$(hostname -s 2>/dev/null || hostname)"
log "Fertig. Oeffne im Browser:  http://${HOST}.local:${PORT}"
command -v librespot >/dev/null 2>&1 || [ -x "$PREFIX/bin/librespot" ] || [ "$WITH_SPOTIFY" = 0 ] || warn "librespot fehlt - Spotify Connect ist deaktiviert"
command -v shairport-sync >/dev/null 2>&1 || [ "$WITH_AIRPLAY" = 0 ] || warn "shairport-sync fehlt - AirPlay ist deaktiviert"
command -v gmediarender >/dev/null 2>&1 || [ "$WITH_UPNP" = 0 ] || warn "gmediarender fehlt - UPnP/DLNA ist deaktiviert"
command -v bluealsa-aplay >/dev/null 2>&1 || [ "$WITH_BLUETOOTH" = 0 ] || warn "bluez-alsa fehlt - Bluetooth ist deaktiviert"
