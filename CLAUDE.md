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
| Raspberry Pi, Raspberry Pi OS (Debian 13 trixie), aarch64, mit Desktop | `ssh pi@raspberrypi.local` | sudo verlangt ein Passwort – Claude hat dort **kein** root |
| PC, AlmaLinux 10.2, x86_64, ohne Desktop, SELinux enforcing | `ssh root@10.0.0.162` (SSH-Key) | Intel-HDA, DP-Monitor an „HDMI 0“ (PCM 3), internes SATA-CD-Laufwerk |
| Synology | `//10.0.0.10/TestMusik` | Zugangsdaten trägt der Nutzer selbst in der Oberfläche ein |

Die SSH-Keys liegen auf dem Windows-PC, auf dem bisher gearbeitet wurde. Auf einem anderen Rechner müssen
die Keys erst eingerichtet werden (oder der Nutzer kopiert sie).

## Einspielen

* **Pi (kein root):** Dateien per scp nach `/tmp/ks-fixN/` bzw. den ganzen Stand nach `~/klangstation`
  kopieren; der Nutzer führt aus: `ssh -t pi@raspberrypi.local "cd ~/klangstation && sudo ./install.sh"`
  (oder ein vorbereitetes `sudo bash /tmp/ks-fixN/deploy.sh`). Danach prüfen.
* **Alma (root):** scp nach `/root/klangstation`, dann `bash install.sh --tv-headless` oder einzelne Dateien
  mit `install -m 0644` nach `/opt/klangstation/...` und `systemctl restart klangstation`.
* Längere Remote-Skripte aus PowerShell als base64 übergeben: `ssh host "echo <b64> | base64 -d | bash"`
  (verschachtelte Anführungszeichen brechen sonst). In PowerShell ist `$args` reserviert.
* Lange Tests (Rippen, Scans, Kopplung) als Hintergrund-Beobachtung starten, die auf das Ereignis wartet;
  der Nutzer bedient dabei Oberfläche bzw. iPhone und meldet, was er hört.

## Git und GitHub

* Repo: `konkred/klangstation` (privat), Branch `main`. Commits mit der noreply-Adresse von GitHub, nicht
  mit der privaten E-Mail.
* Auf dem bisherigen Windows-PC (Windows IoT LTSC, kein winget) liegen MinGit und gh portabel im
  Paketbereich der Claude-App (`%LOCALAPPDATA%\Programs\…` aus Sicht von Claude, real unter
  `…\AppData\Local\Packages\Claude_…\LocalCache\Local\Programs`). gh braucht dort
  `GH_CONFIG_DIR=%USERPROFILE%\.config\gh`, damit Claude und der Nutzer dieselbe Anmeldung sehen.
* PowerShell 5.1 zerlegt Commit-Nachrichten mit Anführungszeichen – Nachricht per Datei (`git commit -F`).

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

## Stand und offene Punkte

Zuletzt getestet: siehe Tabelle „Getestet auf“ in der README.

* **Pi ist nicht auf dem neuesten Stand:** Es fehlen die Korrekturen zu MusicBrainz-Neuversuch und MPD-Update
  nach dem Rippen (`core.py`, `web/js/app.js`). Einspielen über `~/klangstation` + `sudo ./install.sh`.
* Auf AlmaLinux geprüft (26.10.2026): Bluetooth übersteht einen Neustart – SELinux-Modul bleibt geladen,
  Klangstation findet den Adapter beim Start, das iPhone verbindet sich selbst neu und spielt nach ~20 s weiter.
* Auf AlmaLinux noch offen: UPnP mit echter App, Rippen in den internen Speicher, Neuinstallation von null,
  NFS, CEC (braucht Fernseher).
* Pi: `--tv-headless` auf Pi OS Lite ungetestet, CEC-Standby, großer Synology-Scan.
