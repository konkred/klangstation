# Klangstation – Arbeitskontext für Claude

Musik-Streaming-Webapp (Python/Starlette + MPD) im WMP-2000er-Stil für headless Debian- und RHEL-Systeme
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
  librespot/gmediarender/bluealsa-aplay, `lyrics.py` Liedtexte (`.lrc`, LRCLIB), `timers.py` Schlummer-Timer und
  Wecker, `weather.py` Wetter für den Ruhebildschirm (Open-Meteo).
* `web/` – Oberfläche (`index.html`, `js/app.js`, `css/style.css`), `/tv` = „Läuft gerade“-Bildschirm.
* `system/` – systemd-Units, udev-Regel, Hilfsskripte, SELinux-Modul. `ks-netmount` ist ein root-Hilfsdienst
  (Socket nur für Gruppe klangstation): SMB/NFS lesend einhängen, gerippte CDs auf USB speichern.
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
| PC (Hostname `KlangStationAlma`), AlmaLinux 10.2, x86_64, ohne Desktop, SELinux enforcing | `ssh root@10.0.0.162` (SSH-Key, zu Hause) | Intel-HDA, DP-Monitor an „HDMI 0“ (PCM 3), internes SATA-CD-Laufwerk |
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

* **Kiosk (`--tv-headless`):** Chromium startet sonst PipeWire/WirePlumber in der Kiosk-Sitzung, WirePlumber
  setzt die ALSA-Regler zurück (HDMI/DP stumm) → für den Benutzer klangstation maskiert. Dienst an
  `multi-user.target`, nicht `graphical.target`.
* **Chromium auf englischem System** bietet im Kiosk an, die deutsche Seite zu übersetzen →
  `--disable-features=Translate --lang=de` in `ks-tv-kiosk`, `tv.html` mit `translate="no"`.
* **Kiosk lädt neue Oberflächen-Dateien nicht von selbst** → `web_build` im Zustand (Kennung aus Pfad, Größe und
  Änderungszeit der Dateien in `web/`, beim Start berechnet): ändert sie sich, lädt `/tv` neu. Greift also erst nach
  einem Neustart von Klangstation. Einzeln eingespielte Web-Dateien ohne Neustart: Browser beenden und
  `POST /api/tv/show` (erhöht `launch`, `ks-tv-kiosk` startet ihn neu).
* **Browser nahm `js`/`css` nach dem Neuladen ungefragt aus dem Cache** (keine Cache-Vorgabe → heuristische
  Frische) → statische Dateien mit `Cache-Control: no-cache` (`RevalidatedStatic` in `main.py`, sonst 304).
* **Dialog auf dem iPhone ohne „Schließen“:** Im Flex-Dialog braucht der scrollende Inhalt `min-height: 0`, sonst
  wächst die Box über den Bildschirm; `100vh` ist bei Safari höher als sichtbar → `100dvh`. iOS gibt
  `input[type=time]` eine Mindestbreite (ragt aus dem Raster) → `appearance: none; min-width: 0`.
* **MPD `single oneshot`** bleibt nach dem Anhalten stehen → Schlummer-Timer „Titelende“ setzt es danach auf 0.
* **Nicht erreichbarer Sender:** `addid`/`play` gelingen, MPD meldet den Fehler erst danach (`state: stop` + `error`)
  → der Wecker prüft das in der Lautstärke-Rampe und weicht auf die Bibliothek aus.
* **Liedtexte:** eingebettete Texte (Tag `LYRICS`) nicht über MPD `readcomments` lesen – mehrzeilige Werte
  passen nicht ins Zeilenprotokoll. Darum nur `.lrc` neben der Datei und LRCLIB.
* **WebSocket-Ablehnung** erst nach `websocket.accept` schließen, sonst sieht der Browser 1006 statt 4401.

### Python

* **asyncio hält Aufgaben nur schwach** → ohne Referenz räumt der Garbage Collector sie mitten im Lauf weg
  („Task was destroyed but it is pending“). Hintergrundaufgaben immer über `Core._spawn` starten.

## Teststand

Für Nutzer zusammengefasst in der README („Getestet auf“).

### Noch offen

* **CEC unter RHEL:** braucht einen USB-CEC-Adapter (z. B. Pulse-Eight), die Intel-Grafik kann kein CEC.
* **Ganz zum Schluss:** Dauerlauf am Pi (nur auf Wunsch des Nutzers). `ks-dauerlauf.sh` liegt in `/home/pi`
  (Pi zu Hause), läuft als transienter Dienst per `systemd-run` und schreibt 24 h lang alle 5 min nach
  `/home/pi/ks-dauerlauf.csv` (RSS Python/MPD, FDs, CLOSE-WAIT, Dienst-Neustarts, Warnungen, Zustand, Temperatur,
  `vcgencmd get_throttled`). Erster Lauf am 26.10.2026 nach 35 min abgebrochen (unauffällig).
* Entfällt: Scan einer noch größeren Bibliothek.
* Hardware: Das USB-CD-Laufwerk (Samsung SE-218GN) löst am Pi „over-current“ aus → Y-Kabel oder aktiver Hub.
  CD-/USB-Tests darum am Alma.

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
  (librespot liefert keinen).

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
