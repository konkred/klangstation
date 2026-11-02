# Klangstation – Arbeitskontext für Claude

Musik-Streaming-Webapp (Python/Starlette + MPD) im Stil der 2000er (WMP-Skin, wahlweise Frutiger Aero) für
headless Debian- und RHEL-Systeme
(ARM und x86). Was das Projekt kann und wie es installiert wird, steht in der README.md. Diese Datei hält fest,
was nicht im Code steht: Absprachen, Testgeräte, Arbeitsweise, Lehren aus der Fehlersuche und den Teststand.

## Absprachen mit dem Nutzer

* Mit dem Nutzer Deutsch sprechen.
* Nie selbst Passwörter oder Zugangsdaten eingeben; kein Auth-Passwort in Klangstation gesetzt lassen.
* Die E-Mail des Nutzers nicht an Dienste senden; den MusicBrainz-Kontakt trägt der Nutzer selbst ein.
* Vor größeren Systemänderungen auf dem Pi fragen (Systempakete, config.txt, Reboot, Firewall).
* Auf dem Alma-PC (Testsystem) darf Claude als root arbeiten und neu starten.
* Nicht unvermittelt Ton abspielen – Wiedergabetests startet der Nutzer. Eigene Tests stumm (siehe Testtechniken).

## Code und Stil

* Oberfläche, Meldungen und README auf Deutsch, mit Umlauten.
* Code-Kommentare und Log-Meldungen auf Deutsch **ohne** Umlaute (ae/oe/ue/ss), wie im bestehenden Code.
* Zeilenenden LF (siehe .gitattributes) – Skripte laufen auf Linux.
* Python-Abhängigkeiten nur reine Python-Pakete (kein Kompilieren auf ARM).

### Aufbau

* `backend/klangstation/` – App. `core.py` ist die Zentrale (Quellen, Ausgabe, CD, Rippen, Freigaben, Wächter),
  `main.py` die HTTP-/WebSocket-Routen, `audio.py` ALSA-Erkennung und Konfigurationen für mpd/shairport/
  librespot/gmediarender/bluealsa-aplay, `network.py` Netzwerk (liest per nmcli/ip/ss), `lyrics.py` Liedtexte (`.lrc`, LRCLIB), `timers.py` Schlummer-Timer und
  Wecker, `weather.py` Wetter für den Ruhebildschirm (Open-Meteo), `sysinfo.py` Hardware und OS für Optionen › Info.
* `web/` – Oberfläche (`index.html`, `js/app.js`, `css/style.css`) und „Läuft gerade“ unter `/tv` (`tv.html`,
  `js/tv.js`, `css/tv.css`). Themes liegen je in einer eigenen Datei (`css/theme-<name>.css`, `css/tv-<name>.css`) und
  greifen nur unter `html[data-theme=…]`: die Oberfläche merkt sich das Theme pro Browser (localStorage, „auto“ =
  Nacht bei dunklem System), `/tv` folgt der Einstellung `tv_theme` (Liste in `config.TV_THEMES`).
  `theme-dunkel.css` macht für Nacht, Winamp und Hi-Fi die hellen Listen und Dialoge dunkel (über Variablen wie
  `--card`, `--btn-top`). Eigene Bilder je Theme: `VIS_PAL`/VU-Meter in `app.js`, `draw()` in `tv.js`.
* `system/` – systemd-Units, udev-Regel, Hilfsskripte, SELinux-Modul. `ks-netmount` ist ein root-Hilfsdienst
  (Socket nur für Gruppe klangstation): SMB/NFS lesend einhängen, gerippte CDs auf USB speichern. `ks-netadmin`
  ebenso für Netzwerk: WLAN, IPv4 mit Rücknahme-Zeitgeber, SSH, Port der Weboberfläche.
  `ks-automount` hängt USB/SD ein und aus, `ks-tv-kiosk` startet den Kiosk-Browser.
* `install.sh` – Installer und Updater (Optionen: `--help`). Unter RHEL baut er mpd, shairport-sync,
  gmediarender, bluez-alsa und librespot aus dem Quellcode.

Auf den Geräten: App in `/opt/klangstation`, Daten in `/var/lib/klangstation`, Medien unter `/media/klangstation`.

### Git und GitHub

* Repo: `konkred/klangstation` (privat), Branch `main`. Commits mit der noreply-Adresse von GitHub, nicht
  mit der privaten E-Mail (auf dem Laptop in der Repo-Konfiguration gesetzt).
* Zugriff auf GitHub per SSH (`ssh.github.com:443`). gh ist auf dem Laptop nicht installiert.

## Testgeräte

| Gerät | Zugang | Hinweise |
|---|---|---|
| Raspberry Pi zu Hause (Hostname `raspberrypi`), Raspberry Pi OS (Debian 13 trixie) mit Desktop, aarch64 | `ssh pi@raspberrypi` (SSH-Key) | sudo ohne Passwort; Fernseher mit CEC an HDMI 0 |
| Raspberry Pi 4 (4 GB) unterwegs (Hostname `KlangStation-PiLite`), Pi OS Lite (Debian 13), aarch64 | `ssh pi@192.168.8.170` (SSH-Key, mobiler Reise-Router) | sudo ohne Passwort; Fernseher an HDMI 0; Synology dort nicht erreichbar |
| HP ProDesk 400 G5 (Hostname `HP-KlangStation`, i7-8700), Ubuntu 26.04.1 Desktop, x86_64 (seit 02.11., vorher AlmaLinux 10.2 als `KlangStationAlma`; soll neu aufgesetzt werden, `install.sh` lehnt Ubuntu jetzt ab) | `ssh ubuntu@10.0.0.162` (SSH-Key, zu Hause) | sudo ohne Passwort; Intel-HDA, DP-Monitor an „HDMI 0“ (PCM 3), internes SATA-CD-Laufwerk |
| Dell OptiPlex 3060 unterwegs (Hostname `DellOptiPlex3060`), AlmaLinux 10.2 **x86_64_v2** mit GNOME, SELinux enforcing | `ssh root@192.168.8.177` (SSH-Key, Reise-Router) | Celeron G4900T ohne AVX; Intel-HDA, Philips-TV an HDMI 0 (kein CEC); USB-CD-Laufwerk SE-218GN (`sr0`), Bluetooth-Stick RTL8761BU, Stick „MUSIKSTICK“ (FAT32) |
| NFS auf dem Laptop | `192.168.8.155:/mnt/nfsshare` (vom Nutzer angelegt, Adresse im Reise-Netz per DHCP) | Testalben von Claude nach den Tests gelöscht, Freigabe ist leer |
| Synology | `//10.0.0.15/Musik` (am Pi als „Synology Test2“, ~930 Titel); früher `//10.0.0.10/TestMusik` | Zugangsdaten trägt der Nutzer selbst in der Oberfläche ein |

Gearbeitet wird auf einem Laptop mit AlmaLinux 10.2 (`konnis-Latitude`, Bash). Dessen SSH-Key ist auf den
Testgeräten hinterlegt. Der Laptop löst keine `.local`-Namen auf (kein nss-mdns) – zu Hause den Pi darum über
`raspberrypi` ansprechen (Router-DNS, nur IPv6-Adressen), unterwegs über die IP.

### Einspielen

* **Pi (sudo):** Stand per `git archive HEAD | ssh … tar -x` oder scp nach `~/klangstation`, dann
  `ssh pi@<pi> "cd ~/klangstation && sudo ./install.sh"` (ggf. `--tv-headless`) oder einzelne Dateien mit
  `sudo install -m 0644` nach `/opt/klangstation/...` und `sudo systemctl restart klangstation`. Danach prüfen.
  `ks-tv-kiosk` enthält `@PORT@` – beim Einzeleinspielen per `sed` ersetzen.
* **Alma (root):** scp nach `/root/klangstation`, dann `bash install.sh --tv-headless` oder einzelne Dateien
  mit `install -m 0644` nach `/opt/klangstation/...` und `systemctl restart klangstation`.
* **Vor jedem Neustart von Klangstation** (oder Ausgabewechsel) in einem eigenen Schritt prüfen, ob etwas spielt
  (`/api/state` → `source`, `now.state`), und bei laufender Musik fragen – nicht im selben Befehl wie den Neustart.
* Nur Web-Dateien geändert: kein Neustart nötig (`no-cache`), Browser neu laden; den Kiosk (headless) per
  `systemctl restart klangstation-tv` – das unterbricht die Wiedergabe nicht.

### Testtechniken

* Lange Tests (Rippen, Scans, Kopplung, Installer) als Hintergrund-Beobachtung starten, die auf das Ereignis
  wartet; der Nutzer bedient dabei Oberfläche bzw. iPhone und meldet, was er hört.
* **Stumm testen:** MPD-Lautstärke per `setvol 0` auf Port 6600, danach wieder auf den alten Wert. Die
  Lautstärke-API lehnt ab, solange Spotify o. Ä. Quelle ist. CEC-Einschalten vorher in den Einstellungen aus
  (`cec_tv_on`), danach wieder an. `GET /api/settings` liefert die Werte unter `settings`.
* **Ausfall testen mit Rauschen**, nicht mit Sinus: Ein Sinus-FLAC ist winzig und liegt nach dem Start ganz im
  Seiten-Cache, dann spielt er ohne Server einfach weiter.
* Sperrt die Blackhole-Route den Rechner, von dem aus per SSH gearbeitet wird (NFS auf dem Laptop), den Test
  per `sudo setsid nohup …` losgelöst starten und das Protokoll danach lesen.
* **Netzausfall:** `ip route add blackhole <IP>` (Radio: alle IPs des Stream-Hosts plus die verbundene aus `ss`;
  Synology: `<IP>/32`), im `finally` wieder entfernen.
* **Mit Lautstärke, aber ohne Ton** (z. B. Ausblenden prüfen): MPD hat einen Software-Mixer, also die
  HDMI-Schalter per `amixer -c 0 sset IEC958,<n> off` stumm schalten und danach wieder `on`.
  `disableoutput` taugt nicht – dann spielt MPD gar nicht („All audio outputs are disabled“).
* **USB abziehen:** `echo 0 > /sys/bus/usb/devices/<port>/authorized` (wieder 1 = anstecken).
* **Oberfläche testen:** Nie Schalter oder Knöpfe betätigen, die Netz, WLAN, SSH oder Port abschalten – auch nicht mit
  abgefangenem `confirm`. Am 01.11. lief nach `navigate` auf dieselbe URL (nur `#` anders) noch das alte Skript ohne
  Rückfrage → WLAN am Pi aus, Pi nur noch per Kabel erreichbar. Neue Logik direkt aufrufen (Funktion im Konsolen-
  Kontext), Seite vorher mit geänderter Query (`?r=…`) neu laden.
* Beobachtungsskripte mit `setsid nohup` starten und per PID beenden. `pgrep -f`/`pkill -f` treffen sonst die
  eigene SSH-Shell – stattdessen `ps -eo pid,comm,args | awk '$2=="python3"'`.

## Lehren aus der Fehlersuche (nicht wieder einbauen)

### MPD und Audio

* **libsmbclient** in MPD ist nicht threadsicher und stürzt ab → Freigaben hängt das System ein (`ks-netmount`).
  CIFS-Optionen: `cache=none,rsize=131072` (rasize muss 1–8 MB sein).
* **mpg123/mad** lesen beim Einlesen jede MP3 ohne Xing-Header komplett → abgeschaltet, MP3 über ffmpeg.
* **MPD `update <Pfad>`** scheitert, wenn MPD den Elternordner noch nicht kennt → nach dem Rippen den
  Interpreten-Ordner einlesen.
* **libcdio (MPD-Archiv-Plugin „iso“)** beendet bei einem Lesefehler den ganzen MPD-Prozess per `exit()` →
  ISO-Abbilder auf Sticks werden nicht als Archiv eingelesen (`archive_plugin iso` aus).
* **MPD/curl** verbindet bei stillem Netzausfall nie neu (bleibt auf „play“) → Webradio-Wächter in `core`.
* **MPD stellt einen gemerkten Sender pausiert wieder her** und versucht beim Start, darin zu springen – so lange
  nimmt er keine Verbindung an (am Pi bis über 25 s) → vor dem MPD-Neustart Radio stoppen, danach `play <Nr>`.
* **Freigabe-Server weg:** MPD bleibt ~3 min stumm und springt dann durch die Warteschlange. `pause` kehrt im
  Hänger sofort zurück, `stop` blockiert → Freigabe-Wächter pausiert und setzt per `seekid` fort.
* **RPM Fusion baut für EL10 nur x86-64-v3** (AVX2) → auf CPUs ohne AVX (AlmaLinux x86_64_v2) stürzen mpd und
  shairport-sync beim Laden von `libx265` mit SIGILL ab (Code -4) → Installer bindet RPM Fusion dort nicht ein,
  ffmpeg-free aus EPEL (MP3/AAC/WMA/APE/WV/DSF gehen).
* **Headless-Mixer:** Regler stehen auf frischen Systemen stumm/0 % → `audio.prepare_mixer`.
* **vc4hdmi (Pi)** hat keinen Jack-Regler → Anschlussstatus aus `/sys/class/drm/card*-HDMI-A-<n+1>/status`.
* **Dynamische Lautstärke (`volume_normalization`)** gibt es in MPD nur als Startoption → MPD-Neustart wie beim
  Ausgabewechsel; ReplayGain und Überblenden gehen zur Laufzeit (`replay_gain_mode`, `crossfade`).
* **MPD `single oneshot`** bleibt nach dem Anhalten stehen → Schlummer-Timer „Titelende“ setzt es danach auf 0.
* **5.1/7.1 hochmischen:** eigenes ALSA-Gerät `ks_surround` (plug + ttable) in `~/.asoundrc` des Dienstnutzers
  (HOME = `/var/lib/klangstation`); eine fremde `.asoundrc` (ohne Kopfzeile von Klangstation) wird nicht
  überschrieben. `aplay`-Meldungen sind lokalisiert → mit `LC_ALL=C` aufrufen. Stumm testen mit `snd-aloop`
  (bis 32 Kanäle; Aufnahme an `DEV=1` in S24_LE, plug wählt das beste Format); zum Entladen erst `alsa-state`
  stoppen (alsactl hält die Karte).
* **Nicht erreichbarer Sender:** `addid`/`play` gelingen, MPD meldet den Fehler erst danach (`state: stop` + `error`)
  → der Wecker prüft das in der Lautstärke-Rampe und weicht auf die Bibliothek aus.

### CD

* **cdparanoia `-e`** meldet absolute Positionen ab CD-Anfang → relativ zum ersten Wert rechnen.
* **Auswerfen:** erst CDROMSTOP, dann LOCKDOOR 0, EJECT, Status prüfen; Desktop (gvfs/udisks) per udev
  `UDISKS_IGNORE` fernhalten. USB-Brenner trennen sich sonst beim Auswerfen bei drehender CD.
* **MusicBrainz** drosselt (503), Pi und PC teilen eine IP → CD-Abfrage wird bei „offline“ wiederholt, solange
  die CD drin ist.

### USB und Dateisysteme

* **ntfs-3g** kann kein `remount` → zum Schreiben aus- und `rw` neu einhängen, danach wieder über
  `ks-automount` (systemd-mount, ans Gerät gebunden). Nach `umount` hält ntfs-3g das Gerät noch kurz exklusiv.
* **udev hat einen eigenen Mount-Namensraum** → Aus-/Einhängen aus udev-Regeln nur über `systemd-run`/`systemd-mount`.
* **USB-Stick abgezogen, Datei noch offen** → systemd kann nicht aushängen, versucht es nicht wieder, der Ordner
  bleibt belegt → udev-`remove`-Regel hängt lazy aus und entfernt den Ordner.

### Bluetooth, AirPlay, Spotify

* **SELinux + bluez-alsa:** Als Dienst darf bluealsa die PCM-Pipe nicht über D-Bus weiterreichen (stummes
  dontaudit) → dbus-broker trennt bluealsa, bluetoothd kann mit abstürzen → Modul `system/klangstation-bluealsa.cil`.
* **BlueZ hostname-Plugin** macht aus dem Gehäusetyp „Desktop-Computer“ → `bluetoothd -P hostname`.
* **Bluetooth-PCM meldet am Pi nach Ausgabewechsel kurz `Running`**, obwohl das iPhone pausiert ist → Übernahme
  nie bei AVRCP „paused“, sofort bei „playing“, sonst erst nach 3 s laufender PCM (iPhone meldet nach frischem
  Verbinden „stopped“).
* **shairport-sync 5.6** verlangt `session_timeout` ≥ 60; schickt `prgr` (Position) normal.
* **Gerätename bei AirPlay 2:** das iPhone schickt kein `snam`, nur `clip` (oft link-lokales IPv6, Router-DNS kennt
  es nicht) → Name per `avahi-resolve -a` (mDNS). `pend` darf Name/Adresse nicht löschen (kommen nur beim
  Verbinden). Spotify (librespot 0.8): `session_client_changed` kommt, `CLIENT_NAME` ist beim iPhone aber leer.
* **librespot beendet sich ganz**, wenn sein ALSA-Gerät beim Abspielen belegt ist (z. B. noch von AirPlay); die
  App findet das Gerät erst nach 30–60 s wieder. Die Hook-Ereignisse kommen zu spät (am Pi ~0,4 s je Aufruf,
  „loading“ erst nach ~4 s) → Backend `subprocess` mit `system/ks-spotify-sink`: wartet bis 10 s auf das Gerät,
  meldet „sink busy“, Klangstation gibt es frei.
* Beendet sich ein Dienst unerwartet, schreibt `daemons.py` seine letzten Zeilen ins Journal.

### Kiosk und Oberfläche

* **Handy-Layout (≤ 700 px):** `.frame` ist `display: contents`, Navigation als Leiste unten (Zeile 4 im Raster von
  `.wmp`); auf „Wiedergabe“ (`body[data-view]`) großes Cover ohne Visualisierung, Mini-Player nur in den anderen
  Ansichten.
* **Kiosk (`--tv-headless`):** Chromium startet sonst PipeWire/WirePlumber in der Kiosk-Sitzung, WirePlumber
  setzt die ALSA-Regler zurück (HDMI/DP stumm) → für den Benutzer klangstation maskiert. Dienst an
  `multi-user.target`, nicht `graphical.target`.
* **Chromium auf englischem System** bietet im Kiosk an, die deutsche Seite zu übersetzen →
  `--disable-features=Translate --lang=de` in `ks-tv-kiosk`, `tv.html` mit `translate="no"`.
* **Kiosk lädt neue Oberflächen-Dateien nicht von selbst** → `web_build` im Zustand (Kennung aus Pfad, Größe und
  Änderungszeit der Dateien in `web/`, beim Start berechnet): ändert sie sich, lädt `/tv` neu. Greift also erst nach
  einem Neustart von Klangstation. Einzeln eingespielte Web-Dateien ohne Neustart: `klangstation-tv` neu starten
  oder Browser beenden und `POST /api/tv/show` (erhöht `launch`, `ks-tv-kiosk` startet ihn neu).
* **Browser nahm `js`/`css` nach dem Neuladen ungefragt aus dem Cache** (keine Cache-Vorgabe → heuristische
  Frische) → statische Dateien mit `Cache-Control: no-cache` (`RevalidatedStatic` in `main.py`, sonst 304).
* **Dialog auf dem iPhone ohne „Schließen“:** Im Flex-Dialog braucht der scrollende Inhalt `min-height: 0`, sonst
  wächst die Box über den Bildschirm; `100vh` ist bei Safari höher als sichtbar → `100dvh`. iOS gibt
  `input[type=time]` eine Mindestbreite (ragt aus dem Raster) → `appearance: none; min-width: 0`.
* **Sperrbildschirm (Media Session):** iOS/Android zeigen die Steuerung nur, wenn die Seite selbst Ton spielt →
  stille Tonspur, nur bei Bibliothek/Radio/CD. Freischalten beim Antippen **stumm** (`muted` play/pause): eine
  hörbare Tonspur würde AirPlay/Bluetooth vom selben iPhone unterbrechen.
* **Zeit im Sperrbildschirm** nimmt iOS von der Tonspur, nicht aus `setPositionState` (mit 5-s-Schleife sprang sie
  nach dem Spulen auf 0:00) → `/api/silence.wav?s=<Titellänge>` (8 kHz, 8 bit, Range-fähig, erzeugt nur den
  angefragten Ausschnitt), die Tonspur läuft an derselben Stelle mit.
* **Pausierte Seite im Hintergrund:** iOS trennt nach ~10 s den WebSocket; die Seite verbindet beim Zurückkehren
  in 2 s neu, Play im Sperrbildschirm weckt sie. Ein Service Worker (Offline-Hülle) ginge nur über HTTPS.
* **Liedtexte:** eingebettete Texte (Tag `LYRICS`) nicht über MPD `readcomments` lesen – mehrzeilige Werte
  passen nicht ins Zeilenprotokoll. Darum nur `.lrc` neben der Datei und LRCLIB.
* **Einstellungen am Handy zu breit:** `fieldset` hat standardmäßig `min-width: min-content` und wächst mit dem
  breitesten Inhalt aus dem Raster → `fieldset { min-width: 0 }`.
* **WebSocket-Ablehnung** erst nach `websocket.accept` schließen, sonst sieht der Browser 1006 statt 4401.

### Netzwerk und systemd

* **USB-WLAN-Sticks mit Treiber-CD** (ZeroCD, z. B. AVM) melden sich als CD-Laufwerk; `usb_modeswitch` gibt es für
  EL10 nicht → `eject /dev/sr<n>` schaltet um.
* **Ein WLAN, mehrere Zugangspunkte/Bänder:** `nmcli dev wifi list` liefert je BSSID eine Zeile → Liste nach SSID
  zusammenfassen, Bänder sammeln („2,4 + 5 GHz“).

* **`nmcli -g a,b,c`** gibt jedes Feld in einer eigenen Zeile aus, leere Felder als Leerzeile → nur den letzten
  Zeilenumbruch abschneiden, nicht `rstrip("\n")`.
* **`ip -j addr`** enthält die DHCP-Restlaufzeiten → als Änderungs-Signatur nur Name, Zustand und Adressen nehmen,
  sonst „ändert“ sich das Netz alle paar Sekunden.
* **`systemd-run --on-active`** ohne `AccuracySec` feuert bis zu 1 min später; ein abgelaufener transienter Zeitgeber
  bleibt geladen und blockiert seinen Namen → eindeutige Namen bzw. vorher `stop` + `reset-failed`.
* **cage** blockiert SIGTERM/SIGINT (signalfd) und vererbt die Sperre an das Kiosk-Skript; nach SIGTERM wartet cage
  auf das Skript → `klangstation-tv` hing beim Stoppen 90 s. Abhilfe: `ExecStop=-pkill -KILL -x ks-tv-kiosk`.
* **Port-Probe** vor dem Wechsel mit `SO_REUSEADDR` (wie uvicorn), sonst gilt der alte Port wegen TIME_WAIT als belegt.

### Installer und PipeWire

* **Ubuntu nicht unterstützen** (Entscheidung des Nutzers, 02.11.): Der Installer lehnt Ubuntu und Ableger ab. Browser gibt
  es nur als Snap: AppArmor sperrt Profile außerhalb von `~/snap/`, `chromium`/`--tv-headless` geht nicht, dazu andere
  Firmware-Pakete. Der Test vom 02.11. (siehe Bestanden) lief mit Snap-Sonderfall in `ks-tv-kiosk` (b575f4b, wieder entfernt).
* **`set -euo pipefail`:** Ein Befehl, der in einer Pipe in `$(...)` scheitert darf (z. B. `sed` auf eine noch fehlende
  Datei, Code 2), beendet das Skript still → `|| true`. Fällt bei Updates nicht auf, nur auf frischen Systemen.
* **`apt-cache show`** findet auch Paketnamen ohne Kandidat → `apt-cache policy` prüfen.
* **`/etc/debian_version`** kann `forky/sid` enthalten → nur verwenden, wenn es mit einer Ziffer beginnt.
* **WirePlumber setzt bei jedem Start** (Anmeldung, Neustart von PipeWire) HDMI und Kopfhörer auf stumm/0 %, MPD spielt
  dann lautlos → `_mixer_loop` holt die Regler 30 s lang zurück, wenn ein neuer wireplumber-Prozess auftaucht. Nur dann,
  damit Stummschalten von Hand (auch die Testtechnik `IEC958 off`) bestehen bleibt.
* **PipeWire spielt auf demselben Ausgang:** MPD bleibt mit „Device or resource busy“ auf Pause und versucht es nicht
  wieder → `_busy_loop` zeigt den Hinweis und versucht es alle 3 s, höchstens 2 min. Pause/Stopp beenden das Warten
  (samt `clearerror`), sonst startet die Wiedergabe später ungefragt.

### Python

* **asyncio hält Aufgaben nur schwach** → ohne Referenz räumt der Garbage Collector sie mitten im Lauf weg
  („Task was destroyed but it is pending“). Hintergrundaufgaben immer über `Core._spawn` starten.

## Teststand

Für Nutzer zusammengefasst in der README (Unterstützte Systeme: Betriebssysteme, Hardware, getestete Kombinationen).

### Noch offen

* **Debian 13 pur:** noch nie getestet, nur das darauf aufbauende Pi OS (siehe Testplan).
* **Belegter Ausgang:** Fortsetzen an der alten Position nicht getestet; Spotify/AirPlay fängt der Wächter nicht ab.
* **Pi zu Hause** (seit 01.11. aktueller Stand): Wecker mit CEC (Fernseher an?) und Ruhebildschirm am Fernseher;
  WLAN verbinden/trennen am eingebauten WLAN (der Pi hängt sonst nur daran – nur mit Kabel testen).
* Mit Ton im Alltag (Nutzer): echter Wecker über Nacht mit Radiosender; Radio im Sperrbildschirm (am 30.10. war
  Radio Browser gestört).
* **5.1/7.1 mit echter Karte** (USB, CM6206): Kanalreihenfolge an den Buchsen; der Nutzer hört.
* **CEC unter RHEL:** braucht einen USB-CEC-Adapter (z. B. Pulse-Eight), die Intel-Grafik kann kein CEC.
* **Ganz zum Schluss:** Dauerlauf am Pi (nur auf Wunsch des Nutzers). `ks-dauerlauf.sh` liegt in `/home/pi`
  (Pi zu Hause), läuft als transienter Dienst per `systemd-run` und schreibt 24 h lang alle 5 min nach
  `/home/pi/ks-dauerlauf.csv` (RSS Python/MPD, FDs, CLOSE-WAIT, Dienst-Neustarts, Warnungen, Zustand, Temperatur,
  `vcgencmd get_throttled`). Erster Lauf am 26.10.2026 nach 35 min abgebrochen (unauffällig).
* Hardware: Das USB-CD-Laufwerk (Samsung SE-218GN) löst am Pi „over-current“ aus → Y-Kabel oder aktiver Hub.
  CD-/USB-Tests darum am Alma.

### Testplan weitere Geräte (mit dem Nutzer abgestimmt am 01.11.2026, am 02.11. auf Debian/AlmaLinux umgestellt)

| Gerät | System | Deckt ab |
|---|---|---|
| ASUS-Laptop, Ryzen 5 5500U | Debian 13 mit Desktop | AMD-Sound/-Grafik, eingebaute Lautsprecher und Display, eingebautes WLAN, Desktop mit PipeWire |
| Dell Latitude 5501, i5-9400H | Debian 13 ohne Desktop, `--tv-headless` | Kiosk (cage) auf dem Laptop-Display, Intel-WLAN, Sound evtl. über SOF |
| Wincor Nixdorf Beetle, Core 2 Quad | Debian 13 ohne Desktop | ifupdown statt NetworkManager, CPU nur x86-64-v1 (EL9/EL10 starten nicht), wenig Leistung |
| OptiPlex 3060 (Celeron) | später Rocky/AlmaLinux 9 | EL9: ältere Pakete, Quellcode-Builds (Python 3.9) |
| HP i7 (`HP-KlangStation`) | offen: läuft noch mit Ubuntu, neu aufsetzen mit Debian 13 oder AlmaLinux 10 (Nutzer entscheidet) | 5.1 mit CM6206 + Soundbird |
| Pi 4 zu Hause | bleibt Pi OS | CEC, Fernseher |

Reihenfolge: zuerst ASUS (Debian Desktop), dann Dell, Beetle, OptiPlex. Zugang jeweils per SSH mit sudo wie am Pi.

Vorher bzw. dabei bedenken:

* **Laptop-Deckel:** logind versetzt beim Zuklappen in den Ruhezustand → Installer soll `HandleLidSwitch=ignore`
  (eigene Datei unter `/etc/systemd/logind.conf.d/`) setzen. Vor dem ASUS-Test einbauen.
* **Laptop-Display:** Kiosk bei offenem Deckel auf dem eingebauten Display; bei geschlossenem Deckel auf den
  Fernseher wechseln oder aus.
* **Lautsprecher/Kopfhörer:** Der Codec schaltet beim Einstecken selbst um – unter Optionen › Ausgabe nicht als zwei
  verwirrende Geräte zeigen.
* **SOF (Dell, evtl. ASUS):** Debian braucht `firmware-sof-signed`, bringt der Installer bisher nicht mit → wahrscheinlich
  kein Ton ohne; Kartenname dann `sof-hda-dsp`, PCMs „HDA Analog“, „HDMI1–3“.
* **PipeWire auf Debian Desktop** belegt die Karte im Betrieb (gibt sie nach ~5 s Leerlauf frei) – prüfen, ob MPD
  `hw:` bekommt und Regler- und Ausgabe-Wächter greifen (unter Ubuntu getestet, siehe Bestanden).
* **Beetle:** vorher RAM und Tonausgang klären (Kassensysteme haben teils nur Lautsprecher- oder keinen Ausgang);
  Chromium-Kiosk auf alter Intel-Grafik evtl. langsam.
* Optional: Akkustand auf der Info-Seite.

### Bestanden

**Pi zu Hause (Desktop), 26.10.2026**

* Installation und Update per `install.sh` (Daten erhalten; apt hob nur `ntfs-3g` auf deb13u3).
* Neustart während Spotify: Web nach 32 s, alles wieder da, kein ungefragtes Weiterspielen.
* CD: MusicBrainz-Neuversuch (Sperre per `/etc/hosts`), Rippen in den internen Speicher (sofort in der
  Bibliothek), Rippen abbrechen.
* Zugangsschutz: beide Stufen, Sperre, lokale Zugriffe, Kiosk, `ks-reset-password`.
* Quellenwechsel; Ausgabewechsel mit Radio (8 Wechsel Klinke ↔ HDMI, spielt jeweils nach 6–7 s weiter).
* CEC: Abspielen schaltet den Fernseher ein, Ausschalten per TV-Fernbedienung pausiert Radio (Spotify/AirPlay
  bewusst nicht), nach 5 min Stille schaltet Klangstation ihn aus.
* Bluetooth mit iPhone: Ausgabewechsel bei pausiertem iPhone ohne Übernahme, Play am iPhone übernimmt sofort.
* Synology-Scan über WLAN: 928 Titel in 2 min 10 s (≈ 7 Titel/s), Last bis 3,5, 49 °C, nicht gedrosselt,
  Speicher stabil, `/api/state` meist 0,01 s (einmal 3,5 s).
* Störfälle (stumm): Webradio-Netzausfall 60 s → spielt 8 s nach Rückkehr wieder; Synology-Ausfall 90 s →
  nach 15 s pausiert mit Hinweis, danach selber Titel an derselben Stelle (bis wieder Ton kommt ~22 s, davon
  ~15 s CIFS-Wiederverbindung über WLAN).
* Aufgeräumt: Testdateien, Testplaylist „Test Update“ und Radio-Favorit entfernt; Wiedergabeliste „SynoTest“
  ist geblieben.

**Alma, 26.10.2026**

* Update per `install.sh --tv-headless` (1 min 47 s; Einstellungen, Geheimnis, Spotify-Anmeldung, Freigabe mit
  Passwort unverändert, keine Paketänderung).
* Neustart während Radio: Web nach 65 s (davon 39 s Firmware), alle Dienste, Freigabe, Stick, Bluetooth,
  SELinux-Modul da, kein ungefragtes Weiterspielen.
* CD: Rippen in den internen Speicher (3 min 15 s), Auswerfen per Taste während des Rippens.
* USB: FAT32-Umlaute; Speichern auf NTFS und FAT32; Abziehen/Anstecken per USB-`authorized` mit offener Datei,
  schnelles Wiederanstecken (neuer Gerätename), ausgeschaltete remove-Regel (Rückfallweg) und echtes Abziehen.
* Bluetooth: übersteht Neustart, Stick wird im laufenden Betrieb erkannt; mit iPhone keine Übernahme bei
  Bit-perfekt-Wechseln (pausiert und frisch verbunden), Play übernimmt sofort.
* Spotify übernimmt von AirPlay ohne Absturz von librespot.
* Störfälle: Webradio spielt 7 s nach Netzrückkehr wieder; Synology-Ausfall 40 s und 210 s → setzt an derselben
  Stelle fort.
* WebSocket 4401 statt 1006 (per TestClient).

**Pi OS Lite frisch (unterwegs), 27.10.2026**

* `install.sh --tv-headless` von null: 8 min über mobiles Netz (pip-Aussetzer abgefangen), alle Dienste und
  Kiosk (cage + Chromium) laufen, `raspotify` vom Paket bleibt aus.
* Neustart: Boot 24 s, Web nach 26 s, alles wieder da, kein ungefragtes Weiterspielen; Spotify vom Handy spielt.
* AirPlay ↔ Spotify mit iPhone: vorher 30–60 s bis Spotify spielte, beim zweiten Mal gar nicht; mit
  `ks-spotify-sink` je ~3 s in beide Richtungen, auch beim zweiten Wechsel, Pause/Weiter sofort.
* NFS (Laptop, NFS 4.2, `soft,timeo=50,retrans=2`): einhängen, 7 Titel in 6 s eingelesen, Umlaute und „&“ in
  Pfaden und Tags; Ausfall 90 s (stumm): Puffer reicht ~27 s, nach 15 s Stillstand pausiert, 4 s nach Rückkehr
  an derselben Stelle weiter.

**OptiPlex 3060, AlmaLinux 10.2 x86_64_v2 mit GNOME (unterwegs), 27.10.2026**

* Installation auf frischem System (ohne `--tv-headless`): erster Lauf 16 min 21 s, mpd/shairport-sync stürzten ab
  (RPM Fusion, siehe Behobene Fehler); nach dem Fix Neubau in 8 min 33 s, alle Dienste laufen.
* Neustart: Web nach 48 s, alle Dienste, kein ungefragtes Weiterspielen, keine AVCs. GNOME meldet root automatisch
  an, `ks-tv-kiosk` startet Firefox im Kiosk (kein Chromium installiert), PipeWire läuft nicht mit.
* AirPlay ↔ Spotify mit iPhone: je 1–2 s bis zum Titel (laut Nutzer höchstens 3 s), zweimal hin und her,
  Pause/Weiter/Spulen bei Spotify gehen.
* NFS (Laptop, NFS 4.2, `soft,timeo=50,retrans=2`, per API eingetragen): 8 Titel in 7 s, Umlaute und „&“, MP3 über
  ffmpeg-free mit richtiger Länge; Ausfall 90 s (stumm): Puffer ~23 s, nach 15 s Stillstand pausiert, 9 s nach
  Rückkehr an derselben Stelle weiter, keine AVCs. Cover-Suche bei MusicBrainz im mobilen Netz gedrosselt (503) →
  nach vier Versuchen 5 min Pause, wie vorgesehen.
* CD (USB-Laufwerk, kein over-current): 4 Titel erkannt; MusicBrainz per `/etc/hosts` gesperrt → Abfrage beim
  Einlegen, 16 Wiederholungen im Minutentakt, danach alle 5 min; nach Freigabe beim nächsten Versuch gefunden.
* Rippen auf USB-Stick (FAT32) mit Rückfall: Stick bei „Wird gespeichert …“ per `authorized` getrennt → „Input/output
  error“, Album im internen Speicher mit Hinweis, in der Bibliothek; Stick nach Wiederanstecken nach 3 s wieder da,
  ohne halben Ordner, fsck sauber. Normales Rippen auf den Stick: 224 s, danach wieder `ro`.
* Bluetooth (Stick im Betrieb eingesteckt): nach 5 s erkannt, Name DellOptiPlex3060, Klasse Lautsprecher; iPhone
  gekoppelt, übernimmt von Spotify, Pause/Weiter; keine AVCs, GNOME stört nicht.
* UPnP mit echter App (mconnect, iPhone): Titel, Interpret, Cover, Länge, Pause/Weiter, Spulen.
* Aufgeräumt: Test-Rips, NFS-Freigabe, Testskripte, `/etc/hosts`; Testalben auf dem Laptop gelöscht.
* Schlummer-Timer und Wecker (stumm per `IEC958 off`, Lautstärke 60): Timer 1 min blendet ab 30 s vorher von 60 auf
  9 aus, pausiert, stellt 60 wieder her; „Titelende“ hält nach dem Titel an, `single` danach wieder 0; Abbrechen
  setzt `single` zurück. Wecker-Test wird über 2 min von 6 auf 40 lauter; echter einmaliger Wecker mit kaputtem
  Sender → nach 2 s Bibliothek im Zufall, 15-min-Timer gesetzt, Wecker danach aus; bei laufender Musik bleibt er
  still. Wetter (Open-Meteo) und unbekannter Ort, Verlauf, Ruhebildschirm mit Coverband, Ersatzbild, Uhr weicht
  dem Band aus.

**Alma, 30.10.2026**

* Update vom Stand 26.10. per `install.sh --tv-headless` (2 min 2 s, keine Paketänderung, RPM Fusion bleibt – CPU
  kann x86-64-v3): Daten und Spotify-Anmeldung erhalten, Kiosk (cage + Chromium) läuft, statische Dateien mit
  `no-cache`, keine AVCs. Spotify vom Handy verbindet sich direkt nach dem Neustart.
* Laut Nutzer: Ruhebildschirm am Monitor passt, AirPlay zeigt den Gerätenamen des iPhones, Spotify ohne Namen
  (librespot liefert keinen). Wecker-Dialog auf dem iPhone (nach Korrektur) bedienbar, Wecker-Test mit Ton: spielt
  und wird hörbar lauter.
* Bluetooth (Stick im Betrieb eingesteckt, nach 5 s erkannt): iPhone neu gekoppelt, verbunden ohne Übernahme (MPD
  spielt weiter), Play übernimmt nach ~1 s (bluealsa-aplay gibt belegtes Gerät frei, Neustart), Pause/Weiter/
  Titelsprung sofort, Trennen → Leerlauf ohne ungefragtes Weiterspielen von MPD; keine AVCs.
* Lautstärke angleichen und Überblenden (stumm per `IEC958 off`): Überblenden und ReplayGain sofort zur Laufzeit,
  „Dynamisch“ startet MPD neu und spielt nach 2 s an derselben Stelle weiter. Die Bibliothek am Alma hat keine
  ReplayGain-Tags.
* Sperrbildschirm: in Chromium Titel, Cover, Pause/Weiter/Nächster, bei Stopp leer; am iPhone (laut Nutzer)
  Pause/Weiter und Spulen mit richtiger Zeit, Play weckt die pausierte Seite. Homescreen-App ohne Browserleiste.
* Themes: Frutiger Aero (gedämpft) für Oberfläche und `/tv` im Browser (Desktop, 320–390 px) und am Monitor
  (Kiosk); laut Nutzer angenehm. Knopfreihe passt ab 320 px.
* Themes Nacht, Winamp, Aqua, Hi-Fi und Luna (Oberfläche: Wiedergabe, Bibliothek, Optionen, Wecker-Dialog bei 1280 und
  390 px ohne Überlauf; `/tv` mit Wiedergabe und Ruhebildschirm im Browser). Noch nicht am Monitor und am iPhone.

**Alma, 31.10.2026**

* Update per `install.sh --tv-headless` mit WLAN-Unterstützung (NetworkManager-wifi nachinstalliert, NM neu
  gestartet, Kabelverbindung blieb), `ks-netadmin.socket` läuft, keine AVCs.
* Netzwerk (per API, über die eigene Verbindung): feste IPv4 statt DHCP → „Behalten?“ in der Oberfläche, ohne
  Bestätigung nach 120 s zurück auf DHCP; mit Bestätigung bleibt sie; „Zurücknehmen“ stellt sofort zurück.
  Prüfungen (Gateway außerhalb, Broadcast-Adresse, falsche UUID, kurzes WLAN-Passwort, Port 22/belegt) greifen.
* Port der Weboberfläche 8080 → 8082 → 8080: je 4 s, Kiosk zieht mit, firewalld angepasst.
* SSH aus (neue Verbindung abgelehnt, laufende Sitzung bleibt) und wieder an.
* Oberfläche (Reiter Netzwerk) bei 390 px im Klassisch- und Nacht-Theme ohne Überlauf.
* WLAN noch nicht getestet (kein Adapter am Alma).

**Alma, 01.11.2026 – fünf USB-WLAN-Sticks**

* Edimax N150 (7392:b811, RTL8188EU, rtl8xxxu, 2,4 GHz): sofort erkannt, Suche, Verbinden in der Oberfläche
  (Nutzer), DHCP, Weboberfläche bei getrenntem Kabel über die WLAN-MAC erreichbar, „Vergessen“ löscht Profil und
  Datei, Abziehen erkennt die Oberfläche („Kein WLAN-Adapter gefunden“).
* Netgear WNDA3100v3 (0846:9014, MT7632U, mt76x2u): nach 2 s erkannt (dreimal „MCU resp evt:9“ beim Laden,
  folgenlos), verbunden auf 5 GHz mit 300 Mbit/s, ohne Kabel Weboberfläche (4,8 MB in 0,4 s) und Internet.
* AVM FRITZ!WLAN USB Stick N v2 (057c:62ff → nach `eject` 057c:8501, RT5572, rt2800usb): findet Netze, trennt sich
  ~6 s nach der Suche (-71) und kommt im CD-Modus zurück, vorne wie hinten, auch ohne NetworkManager und ohne
  USB-Autosuspend. Während der Tests startete der Alma dreimal ohne Herunterfahren neu (09:15, 09:38, 09:40, kein
  Überstrom/MCE im Protokoll, Watchdog inaktiv), nach dem Abziehen 10 min stabil → **Stick nicht mehr an
  Testgeräte stecken.** Journal am Alma seitdem dauerhaft (`/var/log/journal`).
* Sharp „Remote Download Wireless Adapter“ (04dd:941f, BCM43236 rev 2): brcmfmac kennt nur rev 3
  („Unknown chip“), auch per `new_id` → unter Linux nicht nutzbar.
* Ein Stick ohne Kennung: meldet sich vorne und hinten nicht an (-71, „not accepting address“) → defekt.

**Pi zu Hause, 01.11.2026 – Update vom Stand 26.10.**

* Erreichbar unter 10.0.0.142 (WLAN) bzw. per Kabel; Host-Key per `-o HostKeyAlias=raspberrypi` geprüft.
* `install.sh` (Desktop, ohne `--tv-headless`): 3 min 32 s, EXIT 0, `ks-netadmin.socket` neu, alle Dienste laufen.
  apt hob dabei die vorhandenen Firmware-Pakete (auch `firmware-brcm80211`) auf 20260519 (bpo13+rpt1) → Installer
  installiert seitdem nur fehlende Firmware. Neustart danach: SSH nach 38 s, Web nach 41 s, WLAN-Firmware des Pi
  unverändert (7.45.265, kommt über `/etc/alternatives`, nicht aus dem angehobenen Paket), WLAN auf 5 GHz verbunden,
  alle Dienste laufen, kein ungefragtes Weiterspielen.
* Optionen › Info: Pi 4 Rev 1.5, Cortex-A72 4 Kerne 1,8 GHz, 4 GB, SD64G 59,5 GB ext4, Raspberry Pi OS 13.5, 64 Bit.
* Netzwerk-Reiter unter Pi OS: Adapter, WLAN-Liste (2,4 + 5 GHz), gespeichertes WLAN, SSH (`ssh`), Ports.
* Pi-Klinke meldete 8 Kanäle (bcm2835) → von 5.1/7.1 ausgenommen.

**Alma, 01.11.2026 – Lautsprecher 5.1/7.1 (stumm über snd-aloop)**

* Kanalzahl per aplay: Analog 2, DP 2/8, Loopback 32; belegtes Gerät = unbekannt, später erneut.
* Links-only-Rauschen über MPD: 5.1 → FL/RL voll, FC/LFE halb, rechts 0; 7.1 zusätzlich SL voll, SR 0. MPD gibt
  44100:16:2 aus, shairport-sync nutzt `ks_surround`, `ks-spotify-sink` öffnet es. Zurück auf Stereo entfernt
  `.asoundrc`. Oberfläche: Auswahl nur bei ≥ 6 Kanälen, bei Bit-perfekt gesperrt.
* Noch offen: USB-Kanalreihenfolge mit echter Karte (CM6206) und Lautsprechern.

**HP, Ubuntu 26.04.1 Desktop frisch, 02.11.2026 – ohne Ton** (Ubuntu seitdem nicht mehr unterstützt, gilt nur als Beleg für PipeWire und Python 3.14)

* `install.sh` von null: 126 s, EXIT 0 (erst nach Korrektur, siehe Behobene Fehler), danach Update in 11 s. Alle Dienste
  laufen, Pakete aus Ubuntu, raspotify und die Paketdienste bleiben aus; Weboberfläche vom Laptop erreichbar.
* Python 3.14.4 mit den festen Versionen (starlette 0.41.3, uvicorn 0.32.1, websockets 13.1): Start ohne Warnungen.
* MPD neben aktivem PipeWire (Lautstärke 0): bekommt `hw:` für HDMI 0 und Analog direkt, Regler bleiben an.
* Snap-Firefox als Kiosk per `ks-tv-kiosk` (von Hand in der Sitzung gestartet): lädt `/tv`, keine AppArmor-Sperren;
  `tv_enabled` aus schließt das Fenster, an öffnet es wieder.
* Optionen › Info: HP ProDesk 400 G5 MT, i7-8700 6 Kerne/12 Threads, x86-64-v3, 32 GB, NVMe 238 GB, Ubuntu 26.04.
* Stumm über `snd-aloop` (Unterbrechungen durch PipeWire beim Entladen beachten: erst wireplumber/pipewire stoppen):
  Bibliothek mit Umlauten und „&“, Warteschlange, Wiedergabeliste, Überblenden, ReplayGain, „Dynamisch“ (MPD-Neustart,
  spielt an derselben Stelle weiter), Ausgabewechsel beim Spielen, Schlummer-Timer und Titelende, Wecker-Rampe, kaputter
  Sender → Bibliothek + 60-min-Timer, 5.1/7.1-Verteilung wie am Alma, UPnP per SOAP (Titel, Umlaute, Pause; Spulen nicht
  geprüft, der Testserver kann kein Range).
* Webradio-Netzausfall 60 s: Sender läuft hier über IPv6, also v4 **und** v6 sperren (`ip -6 route add blackhole`). Nach
  25 s „Verbindung unterbrochen“, 19 s nach Rückkehr spielt er wieder.
* Spotify (`getInfo` auf Port 4070) und AirPlay (RTSP auf Port 5000) antworten, beide per mDNS gefunden (vom HP aus geprüft).
* MPD und PipeWire auf getrennten Ausgängen nebeneinander; PipeWire gibt die Karte ~5 s nach Ende frei.
* Abmelden und Anmelden (Protokoll, laut Nutzer alles richtig): Der Anmeldebildschirm (gdm-greeter) startet schon ein
  eigenes WirePlumber → HDMI/Kopfhörer stumm, 1 s später vom Regler-Wächter zurückgeholt; bei der Anmeldung erneut. „Läuft
  gerade“ startet 1 s nach dem WirePlumber der Sitzung von selbst, keine AppArmor-Sperren. Spotify vom Handy mit Ton über HDMI.
* Neustart während Spotify: Start 53 s (davon 39 s Firmware), alle Dienste da, Sitzung meldet sich selbst an, Kiosk läuft,
  Regler an, kein ungefragtes Weiterspielen.
* AirPlay mit iPhone (laut Nutzer alles gut): Titel, Interpret, Album, Cover nach ~2 s, Gerätename `konnis-iPhone-16` per
  `avahi-resolve` über link-/ULA-IPv6, Pause/Weiter, Trennen → Leerlauf ohne ungefragtes Weiterspielen.
* Bluetooth (RTL8761BU, 0bda:8771, im Betrieb eingesteckt, Firmware aus `linux-firmware`) mit iPhone (laut Nutzer wie
  erwartet): sofort erkannt, Klasse Lautsprecher, gekoppelt, Kopplungsfenster schließt, Play übernimmt nach 3 s, Titel,
  Interpret, Pause/Weiter/Titelsprung, Trennen → Leerlauf. PipeWire/GNOME greift nicht ein (WirePlumber-Bluetooth aus).
* CD (internes HP-Laufwerk GUD1N, laut Nutzer alles gut): 4 Titel, MusicBrainz 18 s nach dem Einlegen, kein GNOME-Dialog,
  Autoplay spielt (Titelnamen und Cover kommen nach). Rippen in den internen Speicher: 8 min 8 s für 18 min Musik, FLAC
  und `cover.jpg`, Auswurf danach, sofort in der Bibliothek, abspielbar.

### Behobene Fehler

**26.10.2026**

* NTFS-Sticks: Installer zieht `ntfs-3g` (RHEL aus EPEL); `ks-netmount` schreibt auch auf `fuseblk`; Rip-Ziele
  nur mit beschreibbarem Dateisystem; scheitert das Speichern auf USB, landet das Album im internen Speicher
  (Hinweis in der Oberfläche) statt verworfen zu werden.
* USB abziehen/wieder anstecken: udev-`remove` hängt lazy aus und entfernt den Ordner; `ks-automount` räumt einen
  hängenden alten Mount weg.
* MPD-Absturz beim Aushängen eines Sticks mit ISO-Abbild (libcdio) → Archiv-Plugin aus.
* Webradio nach Netzausfall: Wächter erkennt Stillstand nach 20 s, zeigt „Verbindung unterbrochen – neuer
  Versuch …“, verbindet neu (bis 30 min).
* Synology-Ausfall: Freigabe-Wächter (Titel von `Netz-*` 15 s still + Server antwortet nicht → pausieren, Hinweis „nicht
  erreichbar – Wiedergabe angehalten“, nach Rückkehr an derselben Stelle weiter).
* MusicBrainz-Neuversuch läuft, solange die CD drin ist (erst jede Minute, nach 16 Versuchen alle 5 min).
* Bluetooth riss am Pi die Quelle an sich (siehe Lehren); Spotify gibt bei „Busy“ das Gerät frei.
* WebSocket 4401 statt 1006; `--reset-password` setzt auch `auth_scope` zurück.
* Bei `vc4hdmi` steht „Bit-perfekt hier nicht möglich“ am Ausgang; Dienst-Neustart-Wartezeit wird nach längerem
  Lauf zurückgesetzt; `GET /api/bluetooth` bleibt bei Stufe „settings“ offen (Geräteliste steckt im Zustand).
* Freigabe eintragen: Pfad mit Backslashes ergab „mount error(22)“ ohne Erklärung → `\` wird zu `/`, Fehler 22
  bekommt eine Meldung; „Neu einlesen“ bei nicht eingebundener Freigabe bindet jetzt neu ein.
* Radio nach Ausgabewechsel: Wiederaufnahme wurde vom Garbage Collector abgebrochen, MPD hing beim Start am
  wiederhergestellten Sender → `_spawn` hält Referenzen, Radio wird vor dem Neustart gestoppt.

**27.10.2026**

* Alma auf CPU ohne AVX (OptiPlex 3060, x86_64_v2): mpd und shairport-sync stürzten sofort ab (RPM-Fusion-ffmpeg
  ist v3) → Installer prüft per `ld-linux --help` auf x86-64-v3, sonst ohne RPM Fusion. Erster Lauf 16 min 21 s.
* Am Pi erkannte Klangstation nicht, ob an HDMI etwas hängt → DRM-Status. Automatische Ausgabe jetzt:
  USB-DAC/I²S-HAT, dann HDMI mit erkanntem Gerät (Wunsch des Nutzers), dann Klinke, dann HDMI unbekannt.
* Übersetzen-Popup von Chromium im Kiosk abgeschaltet.
* Spotify-Übernahme von AirPlay dauerte 30–60 s oder scheiterte → `ks-spotify-sink` (siehe Lehren).

**30.10.2026**

* Wecker-Dialog auf dem iPhone: „Schließen“ nicht erreichbar, Zeitfeld ragte heraus (siehe Lehren).
* Sperrbildschirm sprang nach dem Spulen auf 0:00 → Tonspur in Titellänge (siehe Lehren).
* Knopfreihe auf schmalen Handys 22 px zu breit → Lautstärkeregler flexibel, Zufall/Wiederholen erst unter 360 px weg.

**01.11.2026**

* „Vergessen“ des aktiven WLANs und „WLAN ausschalten“ ohne Warnung, obwohl das Gerät dann nicht mehr erreichbar
  ist (am Pi passiert, siehe Testtechniken) → Rückfrage mit Hinweis, auch bei Aufruf über den Namen (kein Kabel).

**02.11.2026**

* Jede Erstinstallation brach seit be2f422 (31.10.) sofort und ohne Meldung ab (Port aus fehlender Unit lesen, siehe Lehren).
* Unter Ubuntu: Warnung wegen Firmware-Paketen ohne Kandidat, Kiosk mit Snap-Firefox zeigte nichts, Info zeigte
  „forky/sid“ als Version (siehe Lehren).
* Unter PipeWire: stumme Regler nach WirePlumber-Start, keine Meldung bei belegtem Ausgang (siehe Lehren).
  `avahi-utils`/`avahi-tools` fehlten im Installer (`avahi-resolve` für den AirPlay-Gerätenamen).
  Getestet (stumm): Regler nach WirePlumber-Neustart wieder an, von Hand stumm bleibt stumm; belegt → Hinweis, 7 s nach
  Ende des Desktop-Tons spielt MPD von selbst; Pause, Umschalten und Stopp beenden das Warten; nach 2 min bleibt es aus.
