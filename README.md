# Klangstation

Headless-Musik-Streamer mit Weboberfläche für Raspberry Pi und Mini-PCs. Ein Gerät am Verstärker,
Aktivlautsprecher oder Fernseher, bedient über den Browser von Handy, Tablet oder PC.

**Inhalt:** [Funktionen](#funktionen) · [Unterstützte Systeme](#unterstützte-systeme) ·
[Installation](#installation) · [Bedienung](#bedienung) · [Fehlersuche](#fehlersuche) ·
[Technik](#technik) · [API](#api-auszug)

## Funktionen

| Quelle / Funktion | Umsetzung |
|---|---|
| USB-Sticks, USB-Platten, SD-Karten | udev + `systemd-mount` hängen sie automatisch nur lesend ein, MPD liest sie ein |
| Netzwerkfreigaben | SMB/NFS (z. B. Synology, Windows-Freigabe), vom System nur lesend eingehängt, mit Fortschrittsbalken beim Einlesen; fällt der Server aus, hält die Wiedergabe an und geht danach an derselben Stelle weiter |
| Webradio | [Radio Browser API](https://api.radio-browser.info) (frei, ohne Key), Suche nach Land und Genre, Favoriten; verbindet nach Netzausfall von selbst neu |
| Apple AirPlay | `shairport-sync`, mit Titel, Interpret und Cover |
| Spotify Connect | `librespot` (Premium-Konto nötig, Anmeldung über die Spotify-App) |
| UPnP/DLNA | `gmediarender` als Renderer (z. B. BubbleUPnP, Hi-Fi Cast, Windows „Wiedergeben auf“) |
| Bluetooth | `bluez-alsa` (A2DP), Titeldaten und Fernsteuerung per AVRCP, Koppeln nur im 2-Minuten-Fenster |
| Audio-CD (USB-Laufwerk) | Erkennung per ioctl, Titelliste über MusicBrainz, Wiedergabe per MPD, optional Autoplay |
| CD rippen | `cdparanoia` (Fehlerkorrektur) + `flac`, mit Tags und Cover, in den internen Speicher oder auf USB |
| Metadaten & Cover | MusicBrainz + Cover Art Archive, gedrosselt und dauerhaft gecacht |
| Ausgabegerät | alle ALSA-Geräte (USB-DAC, I²S-HAT, Klinke, HDMI/DisplayPort, PC-Lautsprecher), automatische Wahl, wahlweise bit-perfekt |
| Wiedergabelisten | speichern, laden, ab Eintrag abspielen, umbenennen, Einträge entfernen; auch Radiosender |
| HDMI-CEC | TV beim Abspielen einschalten und Eingang wählen, TV-Fernbedienung, Pause bei TV aus, optional Standby |
| „Läuft gerade“ | Vollbild unter `/tv` (Cover, Titel, Fortschritt) am HDMI-Ausgang oder in jedem Browser; im Ruhezustand wandernde Uhr mit Datum, nächstem Wecker, Wetter ([Open-Meteo](https://open-meteo.com), optional) und einem Band der zuletzt gehörten Cover |
| Schlummer-Timer & Wecker | Timer (15–90 min oder Titelende) blendet die letzten 30 s aus und hält an; Wecker zu Uhrzeit und Wochentagen mit Radio-Favorit, Wiedergabeliste oder Bibliothek im Zufall, wird über 2 min lauter, schaltet optional nach einer Weile wieder aus, Rückfall auf die Bibliothek, wenn der Sender nicht spielt |
| Liedtexte | auf „Läuft gerade“ zeilengenau mitlaufend, Instrumental-Pausen als Noten: aus einer `.lrc`-Datei neben dem Titel oder von [LRCLIB](https://lrclib.net) (frei, ohne Key), gecacht; nicht bei Webradio |
| Lautstärke & Übergänge | Angleichen nach ReplayGain (Album/Titel automatisch) oder dynamisch, Überblenden 2–10 s; nicht bei bit-perfekt |
| Handy | als App auf den Homescreen legen; auf Wunsch Titel, Cover und Tasten im Sperrbildschirm (Bibliothek, Radio, CD) |
| Erscheinungsbild | klassisch (Media Player der 2000er) oder Frutiger Aero (Glas, Himmel, Blasen): Oberfläche pro Gerät, „Läuft gerade“ in den Optionen |
| Zugangsschutz | optionales Passwort für die Optionen oder die ganze Oberfläche |

## Unterstützte Systeme

Debian, Ubuntu und Raspberry Pi OS sowie RHEL, AlmaLinux, Rocky und Fedora, jeweils auf x86_64, aarch64 und
armv7. Mit Desktop oder ohne (dann zeigt `--tv-headless` den „Läuft gerade“-Bildschirm am Fernseher).

### Getestet auf

| System | Ergebnis |
|---|---|
| Raspberry Pi 4, Raspberry Pi OS (Debian 13 „trixie“), aarch64, mit Desktop | alle Quellen, CD-Wiedergabe und Rippen (USB-Laufwerk), Synology per SMB (auch Serverausfall), Webradio bei Netzausfall, CEC, HDMI-Ton und Klinke, Bluetooth mit iPhone, Update und Neustart |
| Raspberry Pi 4, Raspberry Pi OS Lite (Debian 13), aarch64, ohne Desktop | Installation von null mit `--tv-headless`, alle Dienste, „Läuft gerade“ am Fernseher, AirPlay ↔ Spotify, NFS-Freigabe (auch Serverausfall), Update und Neustart |
| PC, AlmaLinux 10.2, x86_64, ohne Desktop (SELinux aktiv) | Installation inkl. Quellcode-Builds, Ton über PC-Lautsprecher und DisplayPort, bit-perfekt, Radio (auch bei Netzausfall), AirPlay mit Fortschritt, Spotify, UPnP, Bluetooth (USB-Stick RTL8761BU, iPhone, Ein-/Ausstecken im Betrieb, automatische Wiederverbindung nach Neustart), USB-Sticks mit FAT32 und NTFS (auch Abziehen im Betrieb), Synology per SMB (auch Serverausfall), CD-Wiedergabe (internes SATA-Laufwerk) und Rippen auf USB-Stick, „Läuft gerade“ per `--tv-headless`, Lautstärke angleichen und Überblenden, Sperrbildschirm und Home-Bildschirm-App (iPhone), Wecker, beide Erscheinungsbilder, Update und Neustart |
| PC (Celeron ohne AVX), AlmaLinux 10.2 x86_64_v2, mit GNOME (SELinux aktiv) | Installation auf frischem System (ffmpeg aus EPEL statt RPM Fusion), „Läuft gerade“ per Firefox nach dem Anmelden, AirPlay ↔ Spotify, UPnP (mconnect), Bluetooth mit iPhone, NFS-Freigabe (auch Serverausfall), CD über USB-Laufwerk (MusicBrainz-Neuversuch, Rippen auf USB-Stick, Rückfall in den internen Speicher), Neustart |

Noch nicht geprüft: CEC unter RHEL-Systemen (braucht einen USB-CEC-Adapter).

## Installation

### Voraussetzungen

* ein unterstütztes System (siehe oben) mit Internetzugang und root- bzw. sudo-Rechten
* ein Audioausgang: Klinke, HDMI/DisplayPort, USB-DAC oder I²S-HAT
* optional: USB-CD-Laufwerk, Bluetooth-Adapter, Fernseher mit CEC

### Schnellstart

```bash
git clone <dieses-repo> klangstation && cd klangstation
sudo ./install.sh
```

Danach im Browser `http://<hostname>.local:8080` öffnen (z. B. `http://raspberrypi.local:8080`).
Klappt der `.local`-Name nicht, geht auch die IP-Adresse: `http://192.168.x.y:8080`.

Ohne Optionen wird alles installiert: lokale Medien, Freigaben, Radio, CD, AirPlay, Spotify, UPnP und
Bluetooth. Die Dauer hängt vom System ab: Auf Debian und Raspberry Pi OS kommt fast alles als Paket
(wenige Minuten). Unter RHEL-Systemen werden mehrere Programme aus dem Quellcode gebaut, das dauert auf
einem PC etwa 10–20 Minuten.

### Optionen

Die Optionen lassen sich beliebig kombinieren. `sudo ./install.sh --help` zeigt sie auch im Terminal an.

| Option | Was sie tut | Wann verwenden |
|---|---|---|
| `--port <n>` | Die Weboberfläche lauscht auf Port `<n>` statt 8080. Firewall, Kiosk-Bildschirm und Dienst werden passend eingerichtet. | Wenn 8080 schon belegt ist oder die Adresse ohne Port gehen soll (`--port 80` → `http://<hostname>.local`). |
| `--no-airplay` | `shairport-sync` wird nicht installiert bzw. gebaut, das Gerät erscheint nicht als AirPlay-Lautsprecher. | Wenn niemand Apple-Geräte nutzt, oder um auf RHEL-Systemen den Quellcode-Build zu sparen. |
| `--no-spotify` | `librespot` wird nicht installiert, kein Spotify Connect. | Ohne Spotify-Premium-Konto. Spart unter RHEL-Systemen und auf Debian ohne passendes Paket den Rust-Build, der auf einem Raspberry Pi 20–60 Minuten dauert. |
| `--no-upnp` | `gmediarender` wird nicht installiert, das Gerät erscheint nicht als UPnP/DLNA-Renderer. | Wenn niemand von Android-Apps, Windows („Wiedergeben auf“) oder einem NAS aus abspielt. |
| `--no-bluetooth` | `bluez` und `bluez-alsa` werden nicht installiert, die Bluetooth-Konfiguration bleibt unverändert. Auf Systemen mit Desktop wird auch WirePlumber nicht angefasst. | Ohne Bluetooth-Adapter, oder wenn Bluetooth am Gerät für etwas anderes gebraucht wird (Tastatur, Kopfhörer am Desktop). |
| `--spotify-from-source` | `librespot` wird mit Cargo aus dem Quellcode gebaut statt aus dem Raspotify-Paketarchiv geholt. | Nur Debian/Raspberry Pi OS: wenn kein fremdes Paketarchiv eingebunden werden soll oder das Raspotify-Paket Probleme macht. Unter RHEL-Systemen wird ohnehin gebaut. |
| `--tv-headless` | Installiert `cage` (minimaler Wayland-Kiosk) und `chromium` und richtet den Dienst `klangstation-tv` ein. Er zeigt den „Läuft gerade“-Bildschirm nach jedem Start im Vollbild auf dem ersten Bildschirm (tty1), ohne Anmeldung und ohne Desktop. | Auf Systemen **ohne** Desktop (Raspberry Pi OS Lite, AlmaLinux-Server, Debian ohne GUI), wenn am HDMI-/DP-Ausgang ein Fernseher oder Monitor hängt. Auf Systemen **mit** Desktop nicht nötig, dort startet der Bildschirm automatisch nach dem Anmelden. |
| `-h`, `--help` | Zeigt die Optionen an und beendet sich. | |

Hinweise:

* `--no-…` verhindert nur die Installation. Ist ein Programm schon vorhanden (aus einer früheren
  Installation oder von Hand installiert), nutzt Klangstation es trotzdem. Einzelne Quellen lassen sich
  außerdem jederzeit unter *Optionen › Dienste* abschalten, ohne neu zu installieren.
* Die Firewall-Ports werden immer für alle Dienste geöffnet, auch für abgewählte.
* `--tv-headless` belegt tty1: Dort erscheint kein Anmeldeprompt mehr. Anmelden geht weiter per SSH oder auf
  tty2 (Strg+Alt+F2).

### Beispiele

```bash
# Raspberry Pi mit Desktop, alles
sudo ./install.sh

# Raspberry Pi OS Lite am Fernseher, Oberfläche ohne Port
sudo ./install.sh --tv-headless --port 80

# Server ohne Bildschirm, nur Medien, Radio und AirPlay
sudo ./install.sh --no-spotify --no-upnp --no-bluetooth

# AlmaLinux-PC am Monitor, ohne Bluetooth-Adapter
sudo ./install.sh --tv-headless --no-bluetooth
```

### Aktualisieren

Neue Version holen und den Installer mit denselben Optionen erneut aufrufen:

```bash
git pull && sudo ./install.sh <dieselben Optionen wie beim ersten Mal>
```

Einstellungen, Favoriten, Wiedergabelisten, Freigaben und die Musikdatenbank in `/var/lib/klangstation`
sowie die Musik in `/media/klangstation/Lokal` bleiben erhalten.

### Verzeichnisse und Ports

| Pfad | Inhalt |
|---|---|
| `/opt/klangstation` | Anwendung, Python-venv, Hilfsskripte |
| `/var/lib/klangstation` | Einstellungen, Datenbank, Cover-Cache, Wiedergabelisten, Zwischenspeicher beim Rippen |
| `/media/klangstation/Lokal` | Musik auf dem Gerät selbst (hierhin kopieren oder rippen) |
| `/media/klangstation/<Name>` | eingesteckte USB-Medien, Netzwerkfreigaben als `Netz-<Name>` |

| Port | Dienst |
|---|---|
| 8080/tcp (bzw. `--port`) | Weboberfläche |
| 5353/udp (mDNS) | `.local`-Namen, AirPlay- und Spotify-Erkennung |
| 5000/tcp, 6001–6011/udp | AirPlay |
| 4070/tcp | Spotify Connect |
| 1900/udp, 49494–49504/tcp | UPnP/DLNA |

### Was der Installer macht

* **Debian/Raspberry Pi OS:** Pakete aus den offiziellen Quellen: `mpd`, `shairport-sync`, `gmediarender`,
  `bluez-alsa-utils`, `avahi-daemon`, `cdparanoia`, `flac`, `cifs-utils`, `nfs-common`, `alsa-utils`,
  `ntfs-3g`, `v4l-utils` (CEC). `librespot` kommt aus dem Raspotify-Archiv (amd64/arm64/armhf), sonst per Cargo.
* **RHEL/Alma/Rocky/Fedora:** Aktiviert EPEL, CRB und RPM Fusion Free. Was dort nicht als Paket existiert, wird
  aus dem Quellcode gebaut und nach `/usr/local` installiert: unter EL10 `mpd` (neueste 0.24.x),
  `shairport-sync`, `gmediarender`, `bluez-alsa`; `librespot` immer per Cargo. `ntfs-3g` kommt aus EPEL
  (die EL-Kernel lesen NTFS nicht selbst).
* Legt den Systembenutzer `klangstation` an (Gruppen `audio`, `cdrom`, `video`, `render`, `input`), installiert
  die Anwendung mit Python-venv nach `/opt/klangstation` und richtet den Dienst `klangstation` ein.
* Richtet die udev-Regel für USB/SD-Medien, den Hilfsdienst `ks-netmount` (Freigaben, Speichern gerippter CDs)
  und die Firewall (firewalld bzw. ufw) ein.
* Schaltet die distributionseigenen Dienste `mpd`, `shairport-sync`, `raspotify`, `gmediarender` und
  `bluealsa-aplay` ab. Klangstation startet eigene Instanzen, damit es das Audiogerät zwischen den Quellen
  umschalten kann.
* Mit Bluetooth: `bluealsa` nur als Empfänger, Gerätetyp „Lautsprecher“ (auch auf PCs, deren Gehäusetyp BlueZ
  sonst „Desktop-Computer“ melden lässt); auf Desktops überlässt WirePlumber Bluetooth-Audio an `bluez-alsa`
  (rückgängig: `/etc/wireplumber/*/90-klangstation*` löschen). Mit SELinux lädt er das Modul
  `klangstation-bluealsa`: Ohne es darf bluealsa als Dienst den Tonkanal nicht über D-Bus weiterreichen und
  stürzt beim ersten Abspielen ab (rückgängig: `semodule -r klangstation-bluealsa`).
* „Läuft gerade“: mit Desktop ein Autostart-Eintrag (`/etc/xdg/autostart/klangstation-tv.desktop`), mit
  `--tv-headless` der Dienst `klangstation-tv`. Für dessen Sitzung werden PipeWire und WirePlumber gesperrt:
  Chromium würde sie sonst starten, und WirePlumber setzt die ALSA-Regler zurück (HDMI/DP nach dem Booten stumm).

## Bedienung

### Ausgabe

*Optionen › Ausgabe* listet alle Tonausgänge. Hinter HDMI-/DP-Ausgängen steht, ob ein Monitor oder Fernseher
angeschlossen ist. Solange dort nichts von Hand gewählt ist, nimmt Klangstation in dieser Reihenfolge:
USB-DAC oder I²S-HAT, dann HDMI/DP mit erkanntem Gerät, dann die Klinke. Ein HDMI-Ausgang ohne
angeschlossenes Gerät wird nie automatisch gewählt. Beim Wechsel spielt laufende Musik nach wenigen Sekunden
am neuen Ausgang weiter.

Darunter, unter *Wiedergabe*, gilt für Bibliothek, Radio und CD:

* **Lautstärke angleichen:** „Nach ReplayGain-Werten“ nutzt die in den Dateien gespeicherten Werte (Album-Wert
  bei geordneter Wiedergabe, Titel-Wert bei Zufall) und verändert den Klang nicht. Dateien ohne diese Werte
  bleiben, wie sie sind. Werte lassen sich z. B. mit foobar2000, beets oder MusicBrainz Picard berechnen.
  „Dynamisch“ regelt laufend nach und wirkt auch ohne ReplayGain; dafür startet der Player kurz neu.
* **Überblenden:** 2, 5 oder 10 Sekunden zwischen zwei Titeln; „Aus“ spielt lückenlos.
* Bei *Bit-perfekt* ist beides aus.

### Erscheinungsbild

* **Oberfläche:** *Optionen › Ausgabe › Auf diesem Gerät* wechselt zwischen „Klassisch“ und „Frutiger Aero“. Die
  Wahl gilt nur für diesen Browser, jedes Handy und jeder PC kann ein anderes Erscheinungsbild haben.
* **„Läuft gerade“:** *Optionen › Fernseher › Erscheinungsbild* gilt für alle Bildschirme, die `/tv` zeigen (in
  Aero mit aufsteigenden Luftblasen und Glaskarte).

### Handy

* **Als App:** In Safari *Teilen › Zum Home-Bildschirm*, in Chrome *Zum Startbildschirm hinzufügen*. Klangstation
  öffnet sich dann ohne Browserleisten.
* **Sperrbildschirm:** *Optionen › Ausgabe › Auf diesem Gerät* zeigt Titel, Cover und Tasten im Sperrbildschirm und
  Kontrollzentrum. Handys tun das nur, solange die Seite selbst etwas abspielt – darum läuft eine stille
  Tonspur mit, solange Bibliothek, Radio oder CD spielen. Bei AirPlay und Bluetooth bleibt sie aus, damit sie die
  Wiedergabe des Handys nicht unterbricht. Die Einstellung gilt nur für diesen Browser.

### „Läuft gerade“-Bildschirm

* **Mit Desktop:** Nach dem Anmelden öffnet sich Chromium im Vollbild auf `/tv`. Alt+F4 schließt ihn,
  *Optionen › Fernseher › Jetzt am HDMI-Ausgang anzeigen* holt ihn zurück.
* **Ohne Desktop** (`--tv-headless`): Der Dienst `klangstation-tv` startet nach jedem Boot von selbst.
* *Optionen › Fernseher* schaltet den Bildschirm in beiden Fällen ganz ab und wieder an.
* Jeder andere Browser (Tablet an der Wand, Fernseher-Browser): `http://<hostname>.local:8080/tv`.
* Ohne Wiedergabe zeigt er Uhr, Datum, den nächsten Wecker und unten ein langsam durchlaufendes Band der zuletzt
  gehörten Alben und Sender. Für das Wetter trägt man unter *Optionen › Fernseher* einen Ort ein (braucht
  Online-Metadaten). Uhr und Band bewegen sich ständig, damit nichts einbrennt.
* Nach einem Update lädt der Bildschirm die neue Oberfläche von selbst.

### Schlummer-Timer und Wecker

Das Mond-Symbol neben der Lautstärke öffnet beides.

* **Schlummer-Timer:** 15 bis 90 Minuten oder „Titelende“. In den letzten 30 Sekunden wird leiser geblendet (bei
  Bibliothek, Radio, CD, UPnP und Bluetooth), danach angehalten und die Lautstärke zurückgestellt. AirPlay- und
  Spotify-Sitzungen werden beendet. Die Restzeit steht unten rechts und oben auf dem Fernseher.
* **Wecker:** Uhrzeit, Wochentage (keiner = einmalig), was gespielt wird (Radio-Favorit, Wiedergabeliste oder die
  Bibliothek im Zufall), Ziellautstärke und ob er nach 15 Minuten bis 2 Stunden wieder ausschaltet. Er beginnt
  leise und wird über zwei Minuten lauter; wer die Lautstärke verstellt, übernimmt. Läuft zur Weckzeit schon
  Musik, bleibt sie ungestört. Spielt der Sender nach 20 Sekunden nicht, kommt Musik aus der Bibliothek. Ist
  HDMI-CEC an, schaltet sich der Fernseher mit ein.
* Wecker werden in den Einstellungen gespeichert und überstehen Neustarts; ein laufender Schlummer-Timer nicht.

### Netzwerkfreigaben

*Optionen › Freigaben*: Server, Freigabe und ggf. Zugangsdaten eintragen. Klangstation prüft zuerst, ob der
Server erreichbar ist, hängt die Freigabe nur lesend unter `/media/klangstation/Netz-<Name>` ein und liest
sie ein. Der Fortschritt steht als Balken in der Liste. Bis das Einlesen fertig ist, lassen sich Titel der
Freigabe nicht abspielen, damit das Einlesen schnell bleibt. Danach erscheint sie in der Bibliothek unter
„Ordner & Laufwerke“.

Zugangsdaten liegen in `/var/lib/klangstation/settings.json` (nur für den Dienstbenutzer lesbar) und werden nie
über die Oberfläche angezeigt.

### CD rippen

Im Bereich *CD* das Ziel wählen und „CD rippen“ drücken. Jeder Titel wird mit `cdparanoia` fehlerkorrigiert
gelesen und mit `flac` verlustfrei gespeichert, mit Titel, Interpret, Album, Jahr, MusicBrainz-IDs und Cover
(eingebettet und als `cover.jpg`). Ablage: `<Ziel>/<Interpret>/<Album> (<Jahr>)/NN Titel.flac`. Gibt es den
Ordner schon, wird „(2)“ angehängt. Unbekannte CDs landen unter `Unbekannter Interpret/Audio-CD <Disc-ID>`.

* **Interner Speicher:** `/media/klangstation/Lokal`.
* **USB-Stick/-Platte:** wird nur für das Kopieren beschreibbar gemacht und danach wieder lesend eingehängt
  (FAT, exFAT, ext2/3/4, NTFS, Btrfs, XFS, F2FS). Klappt das Speichern dort nicht (Stick voll, abgezogen),
  landet das Album im internen Speicher, und die Oberfläche sagt das.
* Fortschritt und Restzeit stehen im CD-Bereich. Auf Wunsch wirft Klangstation die CD am Ende aus.
* Während des Rippens lassen sich CD-Wiedergabe und Auswerfen nicht nutzen. „Abbrechen“ verwirft alle
  angefangenen Dateien. Zwischengespeichert wird in `/var/lib/klangstation/rip` (pro CD etwa 300–450 MB).

Private Kopien eigener CDs sind in Deutschland erlaubt, solange kein Kopierschutz umgangen wird.

### Zugangsschutz

*Optionen › Zugang*: Passwort für „nur Optionen, Bluetooth-Kopplung und Freigaben“ oder „die gesamte Oberfläche“.
Passwörter werden mit PBKDF2 gespeichert, Sitzungen per signiertem Cookie (30 Tage). Nach mehreren Fehlversuchen
greift eine wachsende Sperre. Zugriffe vom Gerät selbst (Kiosk, interne Hooks) sind immer erlaubt.
Die Verbindung ist unverschlüsseltes HTTP, also nur für das Heimnetz gedacht. Passwort vergessen:

```bash
sudo /opt/klangstation/system/ks-reset-password
```

## Fehlersuche

```bash
journalctl -u klangstation -f       # Hauptdienst
journalctl -u klangstation-tv -b    # "Läuft gerade" ohne Desktop
systemctl status ks-netmount.socket # Hilfsdienst für Freigaben
```

* **Kein Ton:** Unter *Optionen › Ausgabe* den richtigen Ausgang wählen. Hinter HDMI-/DP-Ausgängen steht,
  ob ein Monitor angeschlossen ist. Ob ALSA selbst Ton ausgibt: `speaker-test -D plughw:CARD=<Karte>,DEV=<n> -c 2 -l 1`.
* **Kein Ton über HDMI am Pi:** Monitor muss beim Booten angeschlossen sein. Klangstation verwendet für `vc4hdmi`
  automatisch `default:CARD=…`.
* **Klinke am Pi fehlt:** In `/boot/firmware/config.txt` muss `dtparam=audio=on` stehen.
* **I²S-HAT (HiFiBerry & Co.):** Das passende `dtoverlay=` eintragen. Danach erscheint der HAT unter *Optionen › Ausgabe*.
* **Freigabe lässt sich nicht einhängen:** Die Meldung in *Optionen › Freigaben* nennt den Grund (Server nicht
  erreichbar, Zugangsdaten falsch, Freigabe unbekannt). Auf der Synology muss SMB2/3 aktiv sein.
* **Radio bricht ab oder Freigabe ist weg:** Klangstation verbindet von selbst neu bzw. spielt weiter, sobald der
  Server wieder da ist; bis dahin steht der Grund im Player.
* **NTFS-Stick erscheint nicht:** Unter RHEL-Systemen muss `ntfs-3g` aus EPEL installiert sein (macht der Installer).
* **CD wird nicht erkannt:** `ls -l /dev/sr0` zeigt, ob das Laufwerk da ist. Der Benutzer `klangstation` muss in der
  Gruppe `cdrom` sein.
* **CD lässt sich nicht auswerfen:** Hält ein anderes Programm das Laufwerk (z. B. der Desktop), meldet
  Klangstation das. Manche USB-Laufwerke brauchen einen eigenen Netzteil- bzw. Y-Kabel-Anschluss.
* **„Läuft gerade“ ohne Desktop bleibt schwarz:** `journalctl -u klangstation-tv -b` prüfen; Monitor vor dem Start
  anschließen; unter *Optionen › Fernseher* muss der Bildschirm eingeschaltet sein.
* **CEC reagiert nicht:** Am Fernseher die CEC-Funktion einschalten (Samsung „Anynet+“, LG „SimpLink“, Sony
  „Bravia Sync“, Philips „EasyLink“). PC-Monitore unterstützen CEC meist gar nicht.
  Test: `cec-ctl -d /dev/cec0 --to 0 --give-device-power-status`.
* **Radio-Suche schlägt fehl:** Die Radio-Browser-Server setzen zeitweise Verbindungen zurück; Klangstation versucht
  es automatisch mehrfach über alle Server. Ist der Dienst ganz ausgefallen (Meldung 503), hilft nur abwarten –
  gespeicherte Favoriten spielen weiter, weil sie die Adresse des Senders direkt kennen.
* **AirPlay 2:** Installiert wird klassisches AirPlay (geht mit allen iPhones/Macs). Für AirPlay 2 (Multiroom in der
  Home-App) shairport-sync mit `--with-airplay-2` und `nqptp` bauen.

## Technik

```
Browser ──HTTP/WebSocket──► Klangstation (Python, Starlette, Benutzer "klangstation")
                              ├─ startet & überwacht ─► mpd             (Dateien, Freigaben, Radio, CD)
                              ├─ startet & überwacht ─► shairport-sync  (AirPlay)
                              ├─ startet & überwacht ─► librespot       (Spotify Connect)
                              ├─ startet & überwacht ─► gmediarender    (UPnP/DLNA, Abfrage per SOAP)
                              ├─ startet & überwacht ─► bluealsa-aplay  (Bluetooth; bluealsa läuft als Systemdienst)
                              ├─ startet bei Bedarf  ─► cdparanoia/flac (CD rippen)
                              ├─ Socket (root)       ─► ks-netmount     (Freigaben einhängen, auf USB speichern)
                              ├─ D-Bus: BlueZ + bluealsa (Kopplung, AVRCP, Zustand)
                              ├─ /dev/sr0 ioctl        (CD-Erkennung, Disc-ID, Auswerfen)
                              ├─ /proc/asound, amixer, DRM (Ausgabegeräte, HDMI-Erkennung, stumme Regler)
                              └─ MusicBrainz / Cover Art Archive / Radio Browser / LRCLIB / Open-Meteo
```

* ALSA-`hw`-Geräte sind exklusiv. Startet eine Quelle (z. B. AirPlay vom iPhone), gibt Klangstation das Gerät frei:
  MPD wird gestoppt bzw. die andere Sitzung beendet. AirPlay wartet über `wait_for_completion`, bis das erledigt ist,
  Spotify über das Ausgabeskript `ks-spotify-sink` (librespot selbst würde sich bei belegtem Gerät beenden).
* Beim Wechsel des Ausgabegeräts werden die Konfigurationen neu geschrieben und die Dienste neu gestartet. Lief
  gerade Musik, spielt sie danach weiter (ein Radiosender wird dafür neu verbunden).
* Zwei Wächter halten die Wiedergabe bei Netzproblemen am Laufen: Steht ein Radiosender 20 s still, verbindet
  Klangstation neu (bis zu 30 Minuten lang). Steht ein Titel von einer Netzwerkfreigabe 15 s still und antwortet
  der Server nicht, wird pausiert und nach seiner Rückkehr an derselben Stelle weitergespielt. Ohne das bliebe
  MPD stumm bzw. spränge nach einigen Minuten durch die ganze Warteschlange.
* Auf frisch installierten Systemen ohne Desktop stehen ALSA-Regler oft stumm oder auf 0 %. Klangstation schaltet
  sie beim Wählen eines Ausgangs ein (auf 80 %); bewusst eingestellte Lautstärken bleiben unverändert.
* Ob an einem HDMI-/DP-Ausgang ein Monitor hängt, liest Klangstation bei PC-Grafik (Intel/AMD/NVIDIA) aus den
  ALSA-Jacks, am Raspberry Pi aus DRM (`/sys/class/drm`).
* Ohne „Bit-perfekt“ läuft alles über `plughw` (automatische Format- und Ratenwandlung, Software-Lautstärke).
  Mit „Bit-perfekt“ geht MPD direkt auf `hw`.
* Python-Abhängigkeiten sind ausschließlich reine Python-Pakete. Auf ARM muss also nichts kompiliert werden.

### Netzwerkfreigaben und `ks-netmount`

MPDs eigener SMB-Zugriff (libsmbclient) ist nicht threadsicher und stürzt beim Einlesen ab. Darum hängt das
System die Freigaben ein (`mount.cifs`/`mount.nfs`). Der Dienstbenutzer darf das nicht selbst; das erledigt
der root-Hilfsdienst `ks-netmount` (`ks-netmount.socket`, erreichbar nur für die Gruppe `klangstation`). Er kann
ausschließlich SMB/NFS lesend unter `Netz-*` ein- und aushängen und gerippte CDs auf USB-Medien kopieren. Das
Passwort übergibt er per Datei an `mount.cifs`, die nur während des Einhängens in `/run/ks-netmount` (nur root) liegt.

Die MP3-Decoder `mpg123` und `mad` sind abgeschaltet: Sie lesen beim Einlesen jede MP3 ohne Xing-Header komplett,
was über WLAN Stunden dauert. MP3 spielt `ffmpeg` ab.

### Webradio: warum Radio Browser

* kostenlos, kein API-Key, keine Anmeldung, Open Data (Public Domain)
* etwa 50.000 Sender weltweit mit Land, Genre-Tags, Codec, Bitrate, Logo und geprüften Stream-URLs
* mehrere gespiegelte Server. Klangstation ermittelt sie wie empfohlen per DNS und weicht bei Ausfällen auf andere aus.
* Abrufe werden gemeldet (`/json/url/<uuid>`), damit die Beliebtheitslisten stimmen. Darum bittet das Projekt.

Alternativen wären TuneIn (inoffiziell, Nutzungsbedingungen problematisch), Shoutcast (Key nötig, nur
Shoutcast-Sender) oder laut.fm (nur eigene Sender).

### MusicBrainz: so wird eine Sperre vermieden

* höchstens eine Anfrage pro 1,1 s, global serialisiert
* User-Agent `Klangstation/<Version> ( <Kontakt> )`. Den Kontakt (E-Mail oder URL) unter *Optionen › CD & Metadaten* eintragen.
* HTTP 503/429: `Retry-After` wird beachtet, dann exponentielles Backoff. Nach vier Fehlschlägen werden fünf Minuten lang keine Anfragen gestellt.
* SQLite-Cache: Treffer 30 Tage, Fehlschläge 1 Tag, „kein Cover“ 7 Tage. Cover liegen als Datei auf dem Gerät.
* Gleichzeitige identische Anfragen werden gebündelt. Eingebettete Cover und `cover.jpg` im Ordner haben immer
  Vorrang, das Netz wird nur gefragt, wenn lokal nichts da ist.

### Google Cast

Ist **nicht** enthalten. Einen Cast-*Empfänger* gibt es für Linux nicht als freie Software: Google lässt
nur zertifizierte Geräte mit signierten Gerätezertifikaten zu. Als Ersatz bringt Klangstation einen
UPnP/DLNA-Renderer und einen Bluetooth-Empfänger mit, damit erreicht man praktisch jede App auf Android und Windows.

## API (Auszug)

| Methode | Pfad | Zweck |
|---|---|---|
| GET | `/api/state` | aktueller Zustand (auch per WebSocket `/ws`) |
| POST | `/api/player/{play,pause,toggle,stop,next,prev}` | Transport |
| POST | `/api/player/seek` `{position}` · `/api/player/volume` `{volume}` | Position, Lautstärke |
| GET/POST | `/api/queue` · `/api/queue/add` `{uris, mode}` · `/api/queue/play` `{id}` | Warteschlange |
| GET | `/api/playlists` | gespeicherte Wiedergabelisten |
| GET | `/api/library/albums` · `/api/library/browse?path=` · `/api/library/search?q=` | Bibliothek |
| GET | `/api/art?uri=` · `/api/art?album=&artist=` | Cover |
| GET | `/api/lyrics?artist=&title=&album=&duration=&uri=` | Liedtext (`synced` mit Zeitstempeln, `plain` oder `instrumental`), sonst 404 |
| GET | `/api/radio/search?q=&country=&tag=` · `/api/radio/tags` · `/api/radio/countries` | Radio |
| POST | `/api/radio/play` · `/api/radio/favorites` | Radio abspielen, Favoriten |
| GET/POST | `/api/cd` · `/api/cd/play` `{track}` · `/api/cd/eject` | CD |
| GET/POST | `/api/cd/rip` `{target, eject}` · `/api/cd/rip/cancel` | CD rippen |
| GET/POST | `/api/shares` · `/api/shares/{action}` | Netzwerkfreigaben |
| GET/POST | `/api/tv` · `/api/tv/show` | „Läuft gerade“-Bildschirm |
| POST | `/api/sleep` `{minutes}` | Schlummer-Timer (`0` = aus, `"track"` = Titelende) |
| GET/POST | `/api/alarms` · `/api/alarms/{save,toggle,remove,test}` | Wecker |
| GET/POST | `/api/settings` | Einstellungen, Ausgabegeräte, Dienststatus |
| GET | `/api/silence.wav?s=` | stille Tonspur für den Sperrbildschirm (`s` Sekunden, mit Range) |
| GET/POST | `/api/bluetooth` · `/api/bluetooth/{pairing_on,pairing_off,disconnect,remove}` `{path}` | Bluetooth |
