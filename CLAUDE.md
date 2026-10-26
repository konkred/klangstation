# Klangstation – Arbeitskontext für Claude

Musik-Streaming-Webapp (Python/Starlette + MPD) im WMP-2000er-Stil für headless Debian- und RHEL-Systeme
(ARM und x86). Was das Projekt kann und wie es installiert wird, steht in der README.md. Diese Datei hält fest,
was nicht im Code steht: Testgeräte, Arbeitsweise, Absprachen und Lehren aus der Fehlersuche.

## Sprache und Stil

* Mit dem Nutzer Deutsch sprechen. Oberfläche, Meldungen und README auf Deutsch, mit Umlauten.
* Code-Kommentare und Log-Meldungen auf Deutsch **ohne** Umlaute (ae/oe/ue/ss), wie im bestehenden Code.
* Zeilenenden LF (siehe .gitattributes) – Skripte laufen auf Linux.
* Python-Abhängigkeiten nur reine Python-Pakete (kein Kompilieren auf ARM).

## Aufbau

* `backend/klangstation/` – App. `core.py` ist die Zentrale (Quellen, Ausgabe, CD, Rippen, Freigaben),
  `main.py` die HTTP-/WebSocket-Routen, `audio.py` ALSA-Erkennung und Konfigurationen für mpd/shairport/
  librespot/gmediarender/bluealsa-aplay.
* `web/` – Oberfläche (`index.html`, `js/app.js`, `css/style.css`), `/tv` = „Läuft gerade“-Bildschirm.
* `system/` – systemd-Units, udev-Regel, Hilfsskripte, SELinux-Modul. `ks-netmount` ist ein root-Hilfsdienst
  (Socket nur für Gruppe klangstation): SMB/NFS lesend einhängen, gerippte CDs auf USB speichern.
* `install.sh` – Installer und Updater (Optionen: `--help`). Unter RHEL baut er mpd, shairport-sync,
  gmediarender, bluez-alsa und librespot aus dem Quellcode.

Auf den Geräten: App in `/opt/klangstation`, Daten in `/var/lib/klangstation`, Medien unter `/media/klangstation`.

## Testgeräte

| Gerät | Zugang | Hinweise |
|---|---|---|
| Raspberry Pi (Hostname `raspberrypi`), Raspberry Pi OS (Debian 13 trixie), aarch64, mit Desktop | `ssh pi@raspberrypi` (SSH-Key) | sudo ohne Passwort |
| PC (Hostname `KlangStationAlma`), AlmaLinux 10.2, x86_64, ohne Desktop, SELinux enforcing | `ssh root@10.0.0.162` (SSH-Key) | Intel-HDA, DP-Monitor an „HDMI 0“ (PCM 3), internes SATA-CD-Laufwerk |
| Synology | `//10.0.0.10/TestMusik` | Zugangsdaten trägt der Nutzer selbst in der Oberfläche ein |

Gearbeitet wird auf einem Laptop mit AlmaLinux 10.2 (`konnis-Latitude`, Bash). Dessen SSH-Key ist auf beiden
Testgeräten hinterlegt. Der Laptop löst keine `.local`-Namen auf (kein nss-mdns) – den Pi darum über
`raspberrypi` ansprechen (Router-DNS, nur IPv6-Adressen).

## Einspielen

* **Pi (sudo):** scp nach `~/klangstation`, dann `ssh pi@raspberrypi "cd ~/klangstation && sudo ./install.sh"`
  oder einzelne Dateien mit `sudo install -m 0644` nach `/opt/klangstation/...` und
  `sudo systemctl restart klangstation`. Danach prüfen.
* **Alma (root):** scp nach `/root/klangstation`, dann `bash install.sh --tv-headless` oder einzelne Dateien
  mit `install -m 0644` nach `/opt/klangstation/...` und `systemctl restart klangstation`.
* Lange Tests (Rippen, Scans, Kopplung) als Hintergrund-Beobachtung starten, die auf das Ereignis wartet;
  der Nutzer bedient dabei Oberfläche bzw. iPhone und meldet, was er hört.

## Git und GitHub

* Repo: `konkred/klangstation` (privat), Branch `main`. Commits mit der noreply-Adresse von GitHub, nicht
  mit der privaten E-Mail (auf dem Laptop in der Repo-Konfiguration gesetzt).
* Zugriff auf GitHub per SSH (`ssh.github.com:443`). gh ist auf dem Laptop nicht installiert.

## Absprachen mit dem Nutzer

* Nie selbst Passwörter oder Zugangsdaten eingeben; kein Auth-Passwort in Klangstation gesetzt lassen.
* Die E-Mail des Nutzers nicht an Dienste senden; den MusicBrainz-Kontakt trägt der Nutzer selbst ein.
* Vor größeren Systemänderungen auf dem Pi fragen (Systempakete, config.txt, Reboot, Firewall).
* Auf dem Alma-PC (Testsystem) darf Claude als root arbeiten und neu starten.
* Nicht unvermittelt Ton abspielen – Wiedergabetests startet der Nutzer.

## Lehren aus der Fehlersuche (nicht wieder einbauen)

* **libsmbclient** in MPD ist nicht threadsicher und stürzt ab → Freigaben hängt das System ein (`ks-netmount`).
  CIFS-Optionen: `cache=none,rsize=131072` (rasize muss 1–8 MB sein).
* **mpg123/mad** lesen beim Einlesen jede MP3 ohne Xing-Header komplett → abgeschaltet, MP3 über ffmpeg.
* **MPD `update <Pfad>`** scheitert, wenn MPD den Elternordner noch nicht kennt → nach dem Rippen den
  Interpreten-Ordner einlesen.
* **cdparanoia `-e`** meldet absolute Positionen ab CD-Anfang → relativ zum ersten Wert rechnen.
* **Auswerfen:** erst CDROMSTOP, dann LOCKDOOR 0, EJECT, Status prüfen; Desktop (gvfs/udisks) per udev
  `UDISKS_IGNORE` fernhalten. USB-Brenner trennen sich sonst beim Auswerfen bei drehender CD.
* **Headless-Mixer:** Regler stehen auf frischen Systemen stumm/0 % → `audio.prepare_mixer`.
* **Kiosk (`--tv-headless`):** Chromium startet sonst PipeWire/WirePlumber in der Kiosk-Sitzung, WirePlumber
  setzt die ALSA-Regler zurück (HDMI/DP stumm) → für den Benutzer klangstation maskiert. Dienst an
  `multi-user.target`, nicht `graphical.target`.
* **SELinux + bluez-alsa:** Als Dienst darf bluealsa die PCM-Pipe nicht über D-Bus weiterreichen (stummes
  dontaudit) → dbus-broker trennt bluealsa, bluetoothd kann mit abstürzen → Modul `system/klangstation-bluealsa.cil`.
* **BlueZ hostname-Plugin** macht aus dem Gehäusetyp „Desktop-Computer“ → `bluetoothd -P hostname`.
* **MusicBrainz** drosselt (503), Pi und PC teilen eine IP → CD-Abfrage wird bei „offline“ jede Minute wiederholt.
* **shairport-sync 5.6** verlangt `session_timeout` ≥ 60; schickt `prgr` (Position) normal.
* **libcdio (MPD-Archiv-Plugin „iso“)** beendet bei einem Lesefehler den ganzen MPD-Prozess per `exit()` →
  ISO-Abbilder auf Sticks werden nicht als Archiv eingelesen (`archive_plugin iso` aus).
* **ntfs-3g** kann kein `remount` → zum Schreiben aus- und `rw` neu einhängen, danach wieder über
  `ks-automount` (systemd-mount, ans Gerät gebunden). Nach `umount` hält ntfs-3g das Gerät noch kurz exklusiv.
* **udev hat einen eigenen Mount-Namensraum** → Aus-/Einhängen aus udev-Regeln nur über `systemd-run`/`systemd-mount`.
* **USB-Stick abgezogen, Datei noch offen** → systemd kann nicht aushängen, versucht es nicht wieder, der Ordner
  bleibt belegt → udev-`remove`-Regel hängt lazy aus und entfernt den Ordner.
* **WebSocket-Ablehnung** erst nach `websocket.accept` schließen, sonst sieht der Browser 1006 statt 4401.
* **MPD/curl** verbindet bei stillem Netzausfall nie neu (bleibt auf „play“) → Webradio-Wächter in `core`.

## Stand und offene Punkte

Zuletzt getestet: siehe Tabelle „Getestet auf“ in der README.

### Testergebnisse (26.10.2026)

* **Pi bestanden:** MusicBrainz-Neuversuch (Sperre per `/etc/hosts`), Rippen in den internen Speicher (sofort in
  der Bibliothek), Rippen abbrechen, Zugangsschutz (beide Stufen, Sperre, lokale Zugriffe, Kiosk,
  `ks-reset-password`), Update per `install.sh` (alles bleibt erhalten), Quellenwechsel, Ausgabewechsel ohne
  Bluetooth, Neustart während Spotify (Web nach 32 s, alles wieder da, kein ungefragtes Weiterspielen).
* **Alma bestanden:** Rippen in den internen Speicher (3 min 15 s), Auswerfen per Taste während des Rippens,
  FAT32-Umlaute, Bluetooth übersteht Neustart, Bluetooth-Stick wird im laufenden Betrieb erkannt.
* **Dauerlauf am Pi** seit 26.10.2026 18:32: `ks-dauerlauf.service` (transient, root) schreibt 24 h lang alle
  5 min nach `/home/pi/ks-dauerlauf.csv` (RSS Python/MPD, FDs, CLOSE-WAIT, Dienst-Neustarts, Warnungen, Zustand,
  Temperatur, `vcgencmd get_throttled`). Skript `/home/pi/ks-dauerlauf.sh`. Bis zur Auswertung am Pi nichts ändern.
  Danach: Testplaylist „Test Update“ und Radio-Favorit „Deutschlandfunk“ am Pi entfernen.

### Behoben (im Repo, am Alma eingespielt und geprüft; Pi folgt nach dem Dauerlauf)

* **NTFS-Sticks:** Installer zieht `ntfs-3g` (RHEL aus EPEL); `ks-netmount` schreibt auch auf `fuseblk`;
  Rip-Ziele nur mit beschreibbarem Dateisystem; scheitert das Speichern auf USB, landet das Album im internen
  Speicher (Hinweis in der Oberfläche) statt verworfen zu werden. Geprüft: Speichern auf NTFS und FAT32.
  Ungetestet: der Rückfallweg mit echter CD.
* **USB abziehen/wieder anstecken:** udev-`remove` → lazy aushängen + Ordner entfernen; `ks-automount` räumt einen
  hängenden alten Mount weg. Geprüft per USB-`authorized` mit offener Datei, mit schnellem Wiederanstecken
  (neuer Gerätename), mit ausgeschalteter remove-Regel (Rückfallweg) und echtem Abziehen.
* **MPD-Absturz** beim Aushängen eines Sticks mit ISO-Abbild (libcdio) → Archiv-Plugin aus.
* **Webradio nach Netzausfall:** Wächter erkennt Stillstand nach 20 s, zeigt „Verbindung unterbrochen – neuer
  Versuch …“, verbindet neu (bis 30 min). Geprüft am Alma: spielt 7 s nach Netzrückkehr wieder.
* **MusicBrainz-Neuversuch** läuft, solange die CD drin ist (erst jede Minute, nach 16 Versuchen alle 5 min).
* **WebSocket 4401** statt 1006 (geprüft per TestClient); `--reset-password` setzt auch `auth_scope` zurück.
* Bei `vc4hdmi` steht „Bit-perfekt hier nicht möglich“ am Ausgang. Dienst-Neustart-Wartezeit wird nach
  längerem Lauf zurückgesetzt.
* `GET /api/bluetooth` bleibt bei Stufe „settings“ offen – die Geräteliste steckt ohnehin im Zustand.

### Gebaut, Test mit Nutzer offen

* **Bluetooth reißt die Quelle an sich** (pausiertes iPhone, PCM nach Ausgabewechsel kurz `Running`): Übernahme
  jetzt nie bei AVRCP „paused“, sofort bei „playing“, sonst erst nach 3 s laufender PCM. iPhone meldet nach
  frischem Verbinden „stopped“, nicht „paused“ – darum die 3 s. Test: Radio läuft, iPhone verbunden und
  pausiert, Ausgabe/Bit-perfekt wechseln → Radio muss weiterlaufen; danach am iPhone Play → Übernahme.
* **Spotify bei laufendem AirPlay:** meldet librespot „Busy“ beim Öffnen der Sink, gibt Klangstation das Gerät
  frei (wie Bluetooth/UPnP). Test: AirPlay läuft, in Spotify Klangstation wählen.

### Noch offen

* **Synology-Ausfall:** ~3 min stumm bei „play“ (bis CIFS nach 180 s aufgibt), dann überspringt MPD die ganze
  Warteschlange mit „Host is down“, die Freigabe gilt weiter als eingehängt. Wünschenswert: Stillstand bei
  Titeln von `Netz-*` erkennen, anhalten und Freigabe als „nicht erreichbar“ melden. Vorsicht: `stop` blockiert
  in MPD, solange der Decoder im CIFS-Lesen hängt.
* Pi-Hardware: Das USB-CD-Laufwerk (Samsung SE-218GN) löst „over-current“ aus → Y-Kabel oder aktiver Hub.
  CD-/USB-Tests darum am Alma.
* Tests Pi: CEC-Standby, großer Synology-Scan (beide nach dem Dauerlauf), `--tv-headless` auf Pi OS Lite, NFS.
* Tests Alma: UPnP mit echter App, Neuinstallation von null, NFS, CEC (braucht Fernseher).
