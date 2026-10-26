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

## Stand und offene Punkte

Zuletzt getestet: siehe Tabelle „Getestet auf“ in der README.

* Pi auf dem neuesten Stand (26.10.2026). Dort geprüft: MusicBrainz-Neuversuch (Sperre per `/etc/hosts`,
  Titel kommen nach Aufheben von selbst), Rippen in den internen Speicher mit neuem Interpreten-Ordner →
  sofort in der Bibliothek.
* **Offener Fehler:** `Core._cd_lookup` gibt nach 16 Neuversuchen (~16 min) auf, `lookup` bleibt „offline“ und die
  Oberfläche zeigt weiter „wird jede Minute erneut versucht“. Neuversuch sollte laufen, solange die CD drin ist.
* Zugangsschutz am Pi geprüft (beide Stufen, Sperre, lokale Zugriffe, Kiosk, `ks-reset-password`). **Offene
  Fehler:** `AuthMiddleware` lehnt den WebSocket vor dem Accept ab → Browser sieht 1006 statt 4401; offene Seiten
  zeigen dann nur „Verbindung getrennt…“ statt Anmeldefenster, `/tv` auf fremden Geräten nie „Anmeldung nötig“.
  Kleinigkeiten: `--reset-password` lässt `auth_scope` stehen (Entfernen über die Oberfläche setzt „settings“);
  `GET /api/bluetooth` (Geräteliste) ist bei Stufe „settings“ ohne Anmeldung lesbar.
* Update per `install.sh` am Pi geprüft: Einstellungen, Freigabe mit Passwort, Favoriten, Wiedergabelisten,
  Musik, Sitzungsgeheimnis und Spotify-Anmeldung bleiben erhalten. Vorher fehlte im Repo das Ausführungsrecht
  aller Skripte (Windows) → `sudo ./install.sh` brach mit „Befehl nicht gefunden“ ab; behoben.
* Quellenwechsel am Pi geprüft (Bibliothek → AirPlay → Spotify → Bluetooth → Radio). **Offene Fehler:**
  * Bluetooth reißt die Quelle an sich: Nach jedem `apply_audio` (Ausgabe-/Bit-perfekt-Wechsel) startet
    bluealsa-aplay neu, die PCM des verbundenen, aber pausierten iPhones meldet kurz `Running` → `_bt_loop` ruft
    `take_over("bluetooth")` und stoppt das laufende Radio (10–20 s nach dem Wechsel, reproduzierbar).
    Idee: nur übernehmen, wenn AVRCP „play“ meldet oder kein AVRCP-Status da ist.
  * Spotify bei laufendem AirPlay: librespot stirbt beim Übernehmen mit Code 1 (Gerät belegt), erst der Neustart
    klappt – Übernahme dauert spürbar. Für Spotify fehlt ein Freigeben vor dem Öffnen wie bei AirPlay.
* Ausgabewechsel am Pi (ohne verbundenes Bluetooth) geprüft: HDMI 0 ↔ Klinke, Bit-perfekt an/aus – Radio spielt
  jeweils nach wenigen Sekunden weiter. Bei `vc4hdmi` greift Bit-perfekt bewusst nicht (immer `default:CARD=`),
  die Oberfläche sagt das aber nicht.
* **Offener Fehler – Radio hängt nach Netzausfall:** Internet am Pi per Blackhole-Route gesperrt → MPD bleibt
  auf „play“, `elapsed` steht still, kein Fehler, kein Neuversuch; auch nach Rückkehr des Netzes (> 2 min) nicht.
  Die Oberfläche zeigt „spielt“, es ist stumm. Braucht einen Wächter (Stream, „play“, `elapsed` steht → neu
  verbinden bzw. Meldung). „Stop“ funktioniert.
* **Synology-Ausfall** (Blackhole auf 10.0.0.10, Titel von der Freigabe läuft): erst ~3 min stumm bei „play“
  (`elapsed` steht, bis CIFS nach 180 s aufgibt), dann überspringt MPD die ganze Warteschlange mit „Host is down“,
  die Oberfläche zeigt wechselnde Titel bei 0:00, die Freigabe gilt weiter als eingehängt ohne Fehler. API bleibt
  bedienbar (`state` ≤ 2 s dank Timeout, `queue` bis 6 s). Nach Freigabe: Einhängung und Wiedergabe kommen sofort
  von selbst zurück, aber mitten in der übersprungenen Warteschlange. Wünschenswert: Freigabe als „nicht
  erreichbar“ melden und anhalten statt durchzuspringen.
* Rippen abbrechen am Pi geprüft: Zwischenspeicher leer, kein „(2)“-Ordner, keine Prozesse übrig.
* **Offener Fehler – USB-Stick weg während MPD ihn einliest:** MPD (`auto_update`) hält Dateien auf dem Stick
  offen → systemd kann den Mount nach dem Abziehen nicht lösen (Status 32, „busy“), der Einhängeordner bleibt
  stehen und der wieder eingesteckte Stick (neuer Gerätename) wird nicht eingehängt – bis MPD neu startet bzw.
  zum Neustart. Gesehen am Pi, als der Stick durch Überstrom getrennt wurde (NTFS, Easy2Boot-Stick).
  Am Alma nachgestellt (`rescan` + `/sys/block/sdb/device/delete`): Mount hängt ~10 s, dann gibt MPD auf und
  systemd hängt beim Neuversuch aus. Kommt der Stick in diesem Fenster wieder (Pi: Wackler), scheitert sein
  Einhängen endgültig. Außerdem bleibt nach jedem Abziehen der leere Einhängeordner stehen (so entstand
  `5C63-D696`), und MPD liest ISO-Abbilder auf Sticks als Archiv ein (`DPMS.ISO`).
  Idee: bei `remove` lazy aushängen (`umount -l`) und Ordner entfernen; `ks-automount` bei belegtem Ziel warten.
  **Mit echtem Musik-Stick (FAT32) am Alma bestätigt:** Titel vom Stick läuft, Stick ab- und gleich wieder
  angesteckt → Klangstation stoppt die Wiedergabe und leert die Warteschlange korrekt, aber der alte Mount
  (`sdb1`) hängt („busy“ beim Abziehen, systemd versucht es danach wegen Ratenbegrenzung nicht mehr), und der
  Stick als `sdc1` wird nicht eingehängt (`ks-automount` Exit 1). Erst `systemctl stop <mount>` + `udevadm
  trigger` half. Normale Bedienung reicht also, um den Stick bis zum Neustart unbrauchbar zu machen.
  Umlaute auf FAT32 ok (`utf8` greift).
* Alma: Auswerfen per Taste während des Rippens geprüft – Laufwerk wirft aus, Job endet mit „Die CD ließ sich
  nicht mehr lesen (ausgeworfen?)“, kein halber Ordner, Zwischenspeicher leer.
* Am Pi weitere CD-/USB-Tests wegen Überstrom des Laufwerks nicht sinnvoll → am Alma-PC (SATA-Laufwerk).
* Alma: Rippen in den internen Speicher geprüft (3 min 15 s, Tags/Cover ok, sofort in der Bibliothek).
* **Offene Fehler – NTFS-USB-Medien:**
  * Installer installiert unter RHEL kein `ntfs-3g` (EPEL) → NTFS-Sticks werden gar nicht eingehängt
    („unknown filesystem type 'ntfs'“). Auf Alma von Hand nachinstalliert. Weder Pi- noch Alma-Kernel haben `ntfs3`.
  * `ks-netmount` kennt nur `ntfs3`, nicht `fuseblk` (ntfs-3g) → Rippen auf NTFS-Stick läuft 3 min durch und
    scheitert dann mit irreführendem „Ziel-Datentraeger ist nicht eingehaengt“; die gerippten Dateien werden
    verworfen. `remount,rw` geht bei ntfs-3g ohnehin nicht (aushängen + `ntfs-3g` rw einhängen). Ziel sollte
    vorher geprüft bzw. gar nicht erst angeboten werden.
* Pi-Hardware: Das USB-CD-Laufwerk (Samsung SE-218GN) löst am Pi „over-current“ aus und trennt sich beim
  Anlaufen kurz – Y-Kabel oder aktiver Hub. Leerer Einhängeordner `/media/klangstation/5C63-D696` von einem
  früheren USB-Stick wurde nicht aufgeräumt (beim USB-Test prüfen).
* Auf AlmaLinux geprüft (26.10.2026): Bluetooth übersteht einen Neustart – SELinux-Modul bleibt geladen,
  Klangstation findet den Adapter beim Start, das iPhone verbindet sich selbst neu und spielt nach ~20 s weiter.
* Auf AlmaLinux noch offen: UPnP mit echter App, Rippen in den internen Speicher, Neuinstallation von null,
  NFS, CEC (braucht Fernseher).
* Pi: `--tv-headless` auf Pi OS Lite ungetestet, CEC-Standby, großer Synology-Scan.
