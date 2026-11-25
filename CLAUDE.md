# Klangstation – Arbeitskontext für Claude

Musik-Streaming-Webapp (Python/Starlette + MPD) im Stil der 2000er (WMP-Skin, wahlweise Frutiger Aero) für
headless Debian 13 und Raspberry Pi OS Lite, jeweils **ohne Desktop** (ARM und x86). Was das Projekt kann und wie es installiert wird, steht in der README.md. Diese Datei hält fest,
was nicht im Code steht: Absprachen, Testgeräte, Arbeitsweise, Lehren aus der Fehlersuche und den Teststand.

## Absprachen mit dem Nutzer

* Mit dem Nutzer Deutsch sprechen.
* Nie selbst Passwörter oder Zugangsdaten eingeben; kein Auth-Passwort in Klangstation gesetzt lassen.
* Die E-Mail des Nutzers nicht an Dienste senden; den MusicBrainz-Kontakt trägt der Nutzer selbst ein.
* Vor größeren Systemänderungen auf dem Pi fragen (Systempakete, config.txt, Reboot, Firewall).
* Auf dem zentralen Test-PC (Thin Client) darf Claude als root bzw. per sudo arbeiten und neu starten; Herunterfahren nur mit dem Nutzer.
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
* `system/` – systemd-Units, udev-Regel, Hilfsskripte. `ks-netmount` ist ein root-Hilfsdienst
  (Socket nur für Gruppe klangstation): SMB/NFS lesend einhängen, gerippte CDs auf USB speichern. `ks-netadmin`
  ebenso für Netzwerk: WLAN, IPv4 mit Rücknahme-Zeitgeber, SSH, Port der Weboberfläche.
  `ks-automount` hängt USB/SD ein und aus, `ks-tv-kiosk` startet den Kiosk-Browser.
* `install.sh` – Installer und Updater (Optionen: `--help`), nur Debian/Pi OS; lehnt Ubuntu und RHEL-Systeme ab.
  Aus dem Quellcode baut er nur noch librespot (ohne Raspotify-Paket) und shairport-sync (falls kein Paket).

Auf den Geräten: App in `/opt/klangstation`, Daten in `/var/lib/klangstation`, Medien unter `/media/klangstation`.

### Git und GitHub

* Repo: `konkred/klangstation` (öffentlich, seit 04.11.2026), Branch `main`. Bei Änderungen für Nutzer `VERSION` in `config.py`
  erhöhen: Der Update-Hinweis der Geräte liest genau diese Zeile aus `main`. Commits mit der noreply-Adresse von GitHub, nicht
  mit der privaten E-Mail (auf dem Laptop in der Repo-Konfiguration gesetzt).
* Zugriff auf GitHub per SSH (`ssh.github.com:443`). gh ist auf dem Laptop nicht installiert.

## Testgeräte

Entwickelt und getestet wird nur am **Thin Client** (alle Tests für PCs) und am **Pi**; der Dell-Laptop nur ausnahmsweise, wenn
laptop-spezifische Neuerungen kommen (Deckel, Akku, eingebautes Display, Laptop-WLAN). Andere Geräte gibt es nicht mehr
(Entscheidung des Nutzers, 25.11.2026).

| Gerät | Zugang | Hinweise |
|---|---|---|
| **Test-PC**: Thin Client 10ZiG 6000q-1 (Hostname `KlangStation`), Celeron J4125 (4 Kerne, ohne AVX), 8 GB, SSD 512 GB, **Debian 13 ohne Desktop** | `ssh root@10.0.0.190` bzw. `KlangStation.fritz.box` (SSH-Key, zu Hause, Kabel unter ifupdown; IPv6 `fd20:fb6d:4793:0:2e0:c5ff:fe2b:4050` mit `-o HostKeyAlias=10.0.0.190`) | root erlaubt, Neustart ja, Herunterfahren nur mit dem Nutzer; kein `sudo` installiert (in Skripten `runuser -u klangstation`); eingebaute Lautsprecher (ALC888-VD), Intel-HDMI/DP (Monitor an DP-1 = HDMI 0); kein WLAN, kein Bluetooth-Adapter; Testskripte `t_*.py`, `t_sec.sh` in `/root` |
| Raspberry Pi zu Hause (Hostname `raspberrypi`), Raspberry Pi OS (Debian 13 trixie) mit Desktop, aarch64 | `ssh pi@raspberrypi` (SSH-Key) | sudo ohne Passwort; Fernseher mit CEC an HDMI 0; **Desktop: Installer lehnt seit 0.2.18 ab** – für weitere Tests Pi OS Lite neu aufsetzen (mit dem Nutzer) |
| Raspberry Pi 4 (4 GB) unterwegs (Hostname `KlangStation-PiLite`), Pi OS Lite (Debian 13), aarch64 | `ssh pi@192.168.8.170` (SSH-Key, mobiler Reise-Router) | sudo ohne Passwort; Fernseher an HDMI 0; Synology dort nicht erreichbar |
| Dell Latitude 5501 (Hostname `Dell-Latitude-KlangTest`, i5-9400H, 32 GB), Debian 13.7 ohne Desktop, x86_64 – **nur für laptop-spezifische Neuerungen** | `ssh debiandell@10.0.0.174` (SSH-Key, zu Hause, nur WLAN) | sudo ohne Passwort; WLAN (Intel CNVi) über ifupdown/wpa_supplicant, nicht NetworkManager; HDA-Treiber (ALC3204 + Intel-HDMI), kein SOF |
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
* **Thin Client:** wie am Pi (`git archive HEAD | ssh … tar -x`, dann `install.sh --tv-headless`).
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
* **Stopp per API nur mit POST** (`/api/player/stop`, GET gibt 404). Am 25.11. lief deshalb nach einem Test ~22 s Rauschen hörbar
  über den Monitor: Das Aufräumen stoppte nicht und schaltete `IEC958` danach wieder ein. `iec("on")` in `t_vol.py` stoppt jetzt
  vorher selbst und lässt stumm, solange MPD spielt. Erst wieder hörbar machen, wenn sicher nichts mehr spielt.
* **Belegter Ausgang (stumm):** MPD per `setvol 0`, dann `pw-cat -p --target <node.name> --volume 0 <wav>`. Eine Zahl als Ziel ignoriert
  pw-cat und nimmt den Standardausgang → per `/proc/asound/card<n>/pcm0p/sub0/status` prüfen, wer das Gerät hält.
* **USB abziehen:** `echo 0 > /sys/bus/usb/devices/<port>/authorized` (wieder 1 = anstecken).
* **USB-Stick ohne Hardware:** `modprobe dummy_hcd`, dann `modprobe g_mass_storage file=<abbild> removable=1` – meldet sich als
  echtes USB-Gerät („Mass Storage Gadget“), udev und `ks-automount` greifen. Skript `t_usb.sh` in `/root` am Thin Client.
* **Oberfläche testen:** Nie Schalter oder Knöpfe betätigen, die Netz, WLAN, SSH oder Port abschalten – auch nicht mit
  abgefangenem `confirm`. Am 01.11. lief nach `navigate` auf dieselbe URL (nur `#` anders) noch das alte Skript ohne
  Rückfrage → WLAN am Pi aus, Pi nur noch per Kabel erreichbar. Neue Logik direkt aufrufen (Funktion im Konsolen-
  Kontext), Seite vorher mit geänderter Query (`?r=…`) neu laden.
* Beobachtungsskripte mit `setsid nohup` starten und per PID beenden. `pgrep -f`/`pkill -f` treffen sonst die
  eigene SSH-Shell – stattdessen `ps -eo pid,comm,args | awk '$2=="python3"'`.
* **`ss -K`** nur mit genauem Ziel (`dst <IP> dport = :<Port>`): `dst any` trennt auch die eigene SSH-Sitzung, gesetzte
  Sperrrouten bleiben dann stehen. Sperrrouten immer per `trap … EXIT` entfernen.
* **AirPlay ohne Ton untersuchen:** Klangstation gibt die Ausgabe von shairport-sync nur auf Debug-Stufe aus → zweiten,
  stummen Empfänger daneben starten (`general = { name = "KS-Diag"; output_backend = "stdout"; port = 5100; udp_port_base = 6101; }`,
  `shairport-sync -c … -vv > /dev/null`). Ohne tcpdump: Mitschnitt mit Python über `AF_PACKET` (zeigt auch die Ziel-MAC).
* **Kanäle prüfen:** `S24_LE` belegt 4 Byte je Wert → mit `S32_LE` aufnehmen und als `array('i')` auswerten. Prüfdatei
  nur links: Der rechte Kanal muss 0 sein, sonst taugt die Messung nicht.
* **Screenshots für die README** (`docs/img/`): Firefox ohne Fenster mit `--remote-debugging-port` und WebDriver BiDi
  (`browsingContext.setViewport` mit `devicePixelRatio`, `captureScreenshot`); das Bild der Browser-Leiste taugt nicht (800x500).
  Theme per localStorage `ks-theme`, Ansicht per `#now`/`#library`/`#settings`. Gerätenamen per Skript durch „Wohnzimmer“
  ersetzen, Reiter Freigaben und Netzwerk (IP, Benutzer) nicht zeigen, keine echten Liedtexte (urheberrechtlich geschützt).

## Lehren aus der Fehlersuche (nicht wieder einbauen)

### MPD und Audio

* **libsmbclient** in MPD ist nicht threadsicher und stürzt ab → Freigaben hängt das System ein (`ks-netmount`).
  CIFS-Optionen: `cache=none,rsize=131072` (rasize muss 1–8 MB sein).
* **Cover über MPD (`readpicture`/`albumart`)** kommen ohne `binarylimit` in 8-KB-Stücken, MPD öffnet die Datei je Stück
  neu → auf SMB mit `cache=none` 15,6 s für ein Cover (17 Abfragen). `binarylimit 1048576` beim Verbinden (ab MPD 0.22.4): 0,3 s.
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
### CD

* **cdparanoia `-e`** meldet absolute Positionen ab CD-Anfang → relativ zum ersten Wert rechnen.
* **Auswerfen:** erst CDROMSTOP, dann LOCKDOOR 0, EJECT, Status prüfen; Desktop (gvfs/udisks) per udev
  `UDISKS_IGNORE` fernhalten. USB-Brenner trennen sich sonst beim Auswerfen bei drehender CD.
* **Speichern auf USB:** `os.sync()` meldet keine Schreibfehler. Abgezogen, solange die Daten noch im Seiten-Cache lagen →
  Helfer meldete „ok“, auf dem Stick lagen 0-Byte-Dateien, die Arbeitsdateien wurden gelöscht → `ks-netmount` ruft `fsync` je
  Datei und für den Ordner auf; scheitert es, greift der Rückfall in den internen Speicher.
* **Ripper:** Alles, was scheitern kann, gehört in `_run` ins `try` – sonst stirbt die Aufgabe still und der Auftrag bleibt
  für immer auf „running“ (am Thin Client: Rip-Ordner gehörte root, weil `t_sec.sh` ihn mit `mkdir -p` angelegt hatte).
* **MusicBrainz** drosselt (503), Pi und PC teilen eine IP → CD-Abfrage wird bei „offline“ wiederholt, solange
  die CD drin ist.

### USB und Dateisysteme

* **ntfs-3g** kann kein `remount` → zum Schreiben aus- und `rw` neu einhängen, danach wieder über
  `ks-automount` (systemd-mount, ans Gerät gebunden). Nach `umount` hält ntfs-3g das Gerät noch kurz exklusiv.
* **udev hat einen eigenen Mount-Namensraum** → Aus-/Einhängen aus udev-Regeln nur über `systemd-run`/`systemd-mount`.
* **USB-Stick abgezogen, Datei noch offen** → systemd kann nicht aushängen, versucht es nicht wieder, der Ordner
  bleibt belegt → udev-`remove`-Regel hängt lazy aus und entfernt den Ordner.

### Bluetooth, AirPlay, Spotify

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
* **Debian setzt `LANG=de_DE`** (Thin Client): aplay, bluealsa, GStreamer und MPD melden dann „Das Gerät oder die Ressource ist
  belegt“ statt „busy“ → `ks-spotify-sink` brach sofort ab statt zu warten, Spotify sprang nach wenigen Sekunden zum nächsten
  Titel, ohne Ton. Dienst läuft mit `LC_ALL=C.UTF-8` (0.2.21). Meldungen nie ohne englische Locale auswerten.
* **gmediarender hält das ALSA-Gerät auch nach Stop** (GStreamer-Pipeline bleibt in READY) → bei Übernahme durch eine andere
  Quelle gmediarender neu starten, sobald UPnP einen Titel geladen hat (`uri`), nicht nur beim Spielen.
* Beendet sich ein Dienst unerwartet, schreibt `daemons.py` seine letzten Zeilen ins Journal.
* **Bluetooth-Position nach dem Springen:** Das iPhone schickt beim Springen im Titel nichts über AVRCP (btmon: nur der
  Audiostrom), BlueZ meldet `Position` nur beim Statuswechsel (z. B. auf „playing“), eine Nachfrage gibt die D-Bus-API nicht
  her → Zeit und Liedtext laufen von der alten Stelle weiter; in der README als Grenze vermerkt.

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

* **USB-WLAN-Sticks mit Treiber-CD** (ZeroCD, z. B. AVM) melden sich als CD-Laufwerk → `eject /dev/sr<n>` schaltet um.
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
* **dhcpcd 10 (Debian ohne Desktop, ifupdown)** legt für ein Präfix mit L-Flag keine direkte Route an, wenn der Router es
  zusätzlich als Route Information über sich ankündigt (FRITZ!Box: `2001:…/64` und ULA `fd20:…/64` je als L=1-Präfix und als
  RIO) → nur `<Präfix> via <Router>`, alles ins eigene WLAN geht über den Router. TCP leitet er zurück (RTSP, Titel, Cover),
  die UDP-Zeitpakete von AirPlay nicht → shairport-sync „Sync packet received before we got a timing packet back“, PCM bleibt
  `PREPARED`, das iPhone verbindet immer neu. Kernel und NetworkManager legen beide Routen an. Abhilfe: Hook
  `system/dhcpcd-hook-klangstation` (bei `ROUTERADVERT` je L-Präfix `ip -6 route replace … dev <if> metric 100 expires <vltime>`).
* **cage `-m extend`** (Voreinstellung) verteilt eine Fläche über alle Bildschirme → Laptop mit Fernseher zeigte „Läuft gerade“
  halb auf dem Display, halb am Fernseher. `-m last`: nur der zuletzt angeschlossene; cage kennt den Deckel nicht.
* **ARP-Flux bei Kabel und WLAN im selben Netz:** Linux beantwortet ARP standardmäßig auf jeder Schnittstelle für jede eigene
  Adresse. Nach dem WLAN-Verbinden meldete dhcpcd am Kabel „08:be:ac:… claims 10.0.0.189“, „10 second defence failed“ und holte
  eine neue Adresse (Gerät unter der alten IP weg; die FRITZ!Box vergab danach dauerhaft .190) → Installer setzt
  `arp_ignore=1`, `arp_announce=2` (`/etc/sysctl.d/90-klangstation.conf`).
* **Port-Probe** vor dem Wechsel mit `SO_REUSEADDR` (wie uvicorn), sonst gilt der alte Port wegen TIME_WAIT als belegt.

### Installer

* **Nur ohne Desktop** (Entscheidung des Nutzers, 25.11.2026, ab 0.2.18): Installer bricht ab, wenn ein Display-Manager aktiviert
  ist (`/etc/systemd/system/display-manager.service`) und das System grafisch startet. `graphical.target` allein taugt nicht:
  Debian ohne Desktop (Thin Client) startet es auch. Entfernt: WirePlumber-Bluetooth- und `pro-audio`-Profil, XDG-Autostart
  (`klangstation-tv.desktop`) samt Start in laufenden Sitzungen, GNOME-`gsettings` und Firefox in `ks-tv-kiosk`, Regler-Wächter
  nach WirePlumber-Start (`_mixer_loop`). Geblieben: Sperre von Ruhezustand und Deckel (Laptop ohne Desktop), PipeWire-Sperre für
  die Kiosk-Sitzung, `_busy_loop` (jedes andere Programm auf derselben Karte). Gründe: PipeWire/WirePlumber und die Sitzung
  griffen in Regler, Anschlüsse und Bluetooth ein, GNOME schlief ein oder sperrte.

* **Nur Debian/Pi OS** (Entscheidung des Nutzers, 25.11.2026, ab 0.2.14): AlmaLinux/RHEL fallen weg. Gründe: Pi braucht ohnehin
  Debian; unter EL10 mussten mpd, shairport-sync, gmediarender, bluez-alsa gebaut werden (Thin Client 15 min statt ~1 min), es
  fehlten `alsaequal`/`caps` (Equalizer), `usb_modeswitch`, RPM Fusion für CPUs ohne AVX. Entfernt: RHEL-Zweig im Installer,
  Build-Funktionen, SELinux-Modul. openSUSE ebenfalls verworfen.
* **Ubuntu nicht unterstützen** (Entscheidung des Nutzers, 02.11.): Der Installer lehnt Ubuntu und Ableger ab. Browser gibt
  es nur als Snap: AppArmor sperrt Profile außerhalb von `~/snap/`, `chromium`/`--tv-headless` geht nicht, dazu andere
  Firmware-Pakete.
* **`pipefail` und `| grep -q`:** grep beendet sich beim ersten Treffer, der Befehl davor bekommt SIGPIPE, die Pipe endet mit 141
  → die Prüfung „scheitert“ immer. So installierte der Installer die WLAN-Firmware (`apt-cache policy … | grep -q`) nie, auch die
  ufw-Prüfung war betroffen → Ausgabe erst in eine Variable, dann vergleichen.
* **`set -euo pipefail`:** Ein Befehl, der in einer Pipe in `$(...)` scheitert darf (z. B. `sed` auf eine noch fehlende
  Datei, Code 2), beendet das Skript still → `|| true`. Fällt bei Updates nicht auf, nur auf frischen Systemen.
* **`apt-cache show`** findet auch Paketnamen ohne Kandidat → `apt-cache policy` prüfen.
* **`/etc/debian_version`** kann `forky/sid` enthalten → nur verwenden, wenn es mit einer Ziffer beginnt.
* **Anderes Programm spielt auf demselben Ausgang:** MPD bleibt mit „Device or resource busy“ auf Pause und versucht es nicht
  wieder → `_busy_loop` zeigt den Hinweis und versucht es alle 3 s, höchstens 2 min. Pause/Stopp beenden das Warten
  (samt `clearerror`), sonst startet die Wiedergabe später ungefragt. Aus einer Pause heraus nur `pause 0`: `seek` löscht den Fehler
  und MPD bleibt ohne Hinweis pausiert. `pause 0` lässt den Fehler nach dem Erfolg stehen → bei `state: play` `clearerror`.

### Sicherheit

* **CSRF ohne Passwort:** Starlette liest `request.json()` auch bei `text/plain` → jede im Heimnetz geöffnete Webseite konnte per
  `fetch(…, {mode: "no-cors"})` Einstellungen ändern (SSH aus, Port, Freigaben, Hochladen). Abhilfe: `AuthMiddleware` lehnt POST und
  WebSocket ab, wenn `Origin` nicht zu `Host` passt (ohne `Origin`, z. B. curl und Hooks, erlaubt), `body()` verlangt
  `application/json`. DNS-Rebinding (fremder Name zeigt aufs Gerät, Origin = Host) fängt das nicht ab.
* **MPD-Protokoll:** Ein Zeilenumbruch im Argument beendet den Befehl → `mpd.quote()` lehnt `\n`, `\r`, `\0` ab.
* **Root-Helfer:** Dateien des Dienstnutzers nur mit `O_NOFOLLOW` öffnen (sonst Symlink-Tausch zwischen Prüfung und Öffnen);
  Zielordner auf Datenträgern per `realpath` prüfen (Symlink-Ordner auf ext4-Sticks).
* TestClient schickt beim WebSocket immer `host: testserver` – Origin im Test entsprechend setzen.

### Python

* **asyncio hält Aufgaben nur schwach** → ohne Referenz räumt der Garbage Collector sie mitten im Lauf weg
  („Task was destroyed but it is pending“). Hintergrundaufgaben immer über `Core._spawn` starten.

## Teststand

Für Nutzer zusammengefasst in der README (Unterstützte Systeme: Übersicht und Tabelle „Was womit getestet ist“).

### Noch offen

* **Pi** (zu Hause, erst mit dem Nutzer Pi OS Lite neu aufsetzen): Installation mit `--tv-headless`; Wecker mit CEC (Fernseher
  an?) und Ruhebildschirm am Fernseher; Equalizer an vc4hdmi (`default:CARD=…` als slave); Synology/SMB samt Ausfall und „Neu“ bei
  großer Bibliothek (Dauer von `sort -Last-Modified`); Obergrenze bei UPnP/Bluetooth; eingebautes WLAN verbinden/trennen (nur mit
  Kabel testen).
* **Thin Client:** Equalizer mit 7.1 an echter Karte (USB-Karte CM106 des Nutzers); AirPlay (unter Debian bisher nur Spotify).
  Bluetooth geht dort nicht (kein Adapter).
* **Belegter Ausgang:** Spotify/AirPlay fängt der Wächter nicht ab.
* Mit Ton im Alltag (Nutzer): echter Wecker über Nacht mit Radiosender; Radio im Sperrbildschirm; Hochladen vom iPhone und
  Ordnerwahl mit echtem Dateidialog.
* **Ganz zum Schluss:** Dauerlauf am Pi (nur auf Wunsch des Nutzers). `ks-dauerlauf.sh` liegt in `/home/pi`
  (Pi zu Hause), läuft als transienter Dienst per `systemd-run` und schreibt 24 h lang alle 5 min nach
  `/home/pi/ks-dauerlauf.csv` (RSS Python/MPD, FDs, CLOSE-WAIT, Dienst-Neustarts, Warnungen, Zustand, Temperatur,
  `vcgencmd get_throttled`). Nach dem Neuaufsetzen erst wieder hinlegen.
* Hardware: Das USB-CD-Laufwerk (Samsung SE-218GN) löst am Pi „over-current“ aus → Y-Kabel oder aktiver Hub.
  CD-/USB-Tests darum am Thin Client.

### Laptop (Dell, nur bei laptop-spezifischen Neuerungen)

* **Deckel:** Installer setzt `HandleLidSwitch=ignore` (auch ExternalPower/Docked) in
  `/etc/systemd/logind.conf.d/90-klangstation.conf`.
* **Display:** cage mit `-m last` nutzt den Fernseher, sobald er steckt, sonst das eingebaute Display.
* **SOF:** Der Dell läuft über `snd_hda_intel`. Andere Laptops brauchen evtl. `firmware-sof-signed`, bringt der Installer bisher
  nicht mit; Kartenname dann `sof-hda-dsp`, PCMs „HDA Analog“, „HDMI1–3“.
* Akkustand: oben rechts auf „Läuft gerade“ (`sysinfo.battery`, alle 5 s); unter Info mit Kapazität vom Neuzustand.
* Noch offen: Kopfhörer.

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

**Dell Latitude 5501 (i5-9400H), Debian 13.7 ohne Desktop frisch, nur WLAN über ifupdown, 07.11.2026**

* `install.sh --tv-headless` von null: 144 s, EXIT 0, keine Warnungen. NetworkManager kam dazu und lässt `wlo1` in Ruhe
  (`unmanaged`), das WLAN unter ifupdown blieb bestehen (Installer losgelöst per `setsid nohup` gestartet, falls es abreißt).
* Alle Dienste und Kiosk (cage + Chromium auf eDP) laufen, Paketdienste aus. Ausgabe automatisch „ALC3204 Analog“, Master,
  Speaker, Headphone 100 %, Auto-Mute an. Akku im Zustand (100 %, Netzteil). Laut Nutzer: Display zeigt „Läuft gerade“, Radio
  aus den Lautsprechern.
* Neustart: System 10,6 s, SSH und Web nach 49 s, WLAN wieder unter ifupdown, alle Dienste und Kiosk da, kein PipeWire, Regler
  100 %, kein ungefragtes Weiterspielen.
* Stumm über `snd-aloop`: FLAC, MP3, OGG, Opus, M4A, WMA, WAV mit Pegel; Umlaute und „&“ in Bibliothek, Suche, Warteschlange,
  Wiedergabeliste; Ausgabewechsel beim Spielen; Überblenden, ReplayGain, „Dynamisch“ (spielt weiter); Schlummer-Timer blendet aus
  (Anhalten nicht belegt, die Testtitel endeten vorher), Titelende; Wecker-Rampe; kaputter Sender → Bibliothek + 60-min-Timer.
  Webradio-Netzausfall 60 s über WLAN (v4 und v6): Hinweis nach 30 s, 19 s nach Rückkehr spielt er wieder.
* Spotify mit iPhone (laut Nutzer, Protokoll): Titel, Cover, Pause/Weiter, Titelsprung. AirPlay zuerst stumm (siehe Lehren, dhcpcd):
  Titel, Cover und Gerätename kamen, kein Ton. Mit dem Hook (0.2.9): Ton, Spulen, nächster Titel, Pause/Weiter (laut Nutzer); nach
  einem Neustart setzt der Hook die Routen von selbst (SSH nach 50 s), AirPlay spielt über ULA- und globale IPv6-Adresse.
* Bluetooth (eingebaut) mit iPhone: gekoppelt, Kopplungsfenster schließt, Wiedergabe und Tasten laut Nutzer in Ordnung.
* Deckel zu und auf ohne Fernseher: Spotify spielt weiter, Kiosk läuft (cage lässt eDP an). Fernseher an DP-3 (Docking-/USB-C-
  bzw. HDMI-Anschluss): erst „Läuft gerade“ über beide Bildschirme verteilt, mit `-m last` (0.2.9) ganz am Fernseher, Display aus;
  Deckel zu → bleibt am Fernseher; Abziehen → zurück aufs Display (laut Nutzer, DRM-Status). Ton über HDMI (laut Nutzer).
* Ausgabe „Automatisch“ folgt dem Anstecken (0.2.10, `_autoout_loop`, Fingerabdruck `audio.output_signature` alle 3 s, zwei
  gleiche Durchläufe): Radio am Fernseher, DP abgezogen → Analog, angesteckt → zurück auf HDMI 0, Radio spielt weiter (laut Nutzer,
  Protokoll). Info zeigt den Akku („100 %, Netzteil, voll“, Kapazität 59 % vom Neuzustand).
* Noch offen: Kopfhörer am Dell.

**Thin Client 10ZiG (Celeron J4125), Debian 13 ohne Desktop frisch, 25.11.2026 – ohne Ton**

* `install.sh --tv-headless` von null (0.2.14): 128 s, EXIT 0, keine Warnungen. MPD 0.24.4, shairport-sync
  4.3.7, librespot 0.8.0 (Raspotify), gmediarender 0.3, Chromium 156, cage 0.2.0, alsaequal 0.6 + caps 0.9.26. Alle Dienste und
  Kiosk laufen, keine fehlgeschlagenen Units; Automatik wählt HDMI 0 (Monitor). Kabel bleibt unter ifupdown.
* Installer lehnt AlmaLinux, Fedora, Ubuntu, Mint und Arch ab (Fallprüfung mit gestellter `os-release`).
* Equalizer stumm über snd-aloop: zehn Regler in richtiger Reihenfolge (numid 1–10 = 31 Hz…16 kHz, 0–100), jedes Band wirkt auf
  seine Frequenz, vor 5.1 auf allen sechs Kanälen gleich. „Flach“ hob um +3,2 dB an → korrigiert (0.2.15, siehe Lehren), jetzt
  −0,4 dB bei 1 kHz. Oberfläche mit Reglern in allen Themes bei 390 px ohne Überlauf.
* Formate nur links (L ≈ 1760–1950, R 0), Ausgabewechsel beim Spielen, Überblenden,
  ReplayGain, „Dynamisch“, Schlummer-Timer (60 → 3, Pause, 60 zurück), Titelende, echter Wecker mit kaputtem Sender (Bibliothek,
  15-min-Timer, Wecker aus); Obergrenze 50 (Regler, fremdes `setvol` nach ~1 s, Wecker-Rampe endet bei 50, neue Grenze nach 0,5 s),
  Startlautstärke 30 nach Neustart 30, mit Grenze 20 → 20; Origin/JSON/Zeilenumbruch/Typ, gleichzeitige Uploads (einer 409, keine
  Reste); `ks-netmount` (Symlink-Ordner abgelehnt, Symlink-Datei nicht kopiert, `..` und Ziel Lokal abgelehnt, danach `ro`).
* Webradio-Netzausfall 60 s (v4 und v6): Hinweis nach 27 s, 12 s nach Rückkehr spielt er wieder.
* Neustart über `POST /api/system/power`: Web nach 36 s (Boot 21 s), alle Dienste und Kiosk, nichts spielt, IPv6-Routen per Hook.
* Update per `install.sh --tv-headless`: 30 s, EXIT 0, `settings.json` unverändert.
* Netzwerk-Reiter (per API): Port 8080 → 8082 (erreichbar nach 6 s) → 8080 (4 s), Kiosk zieht mit; belegter Port (6600) und 22
  abgelehnt. SSH aus → neue Verbindungen abgelehnt, laufende Sitzung bleibt; SSH wieder an. Feste IPv4 auf dem Kabel unter ifupdown
  richtig abgelehnt („Ungültige Verbindung“); Rücknahme auf der WLAN-Verbindung geprüft (siehe unten).
* USB emuliert (`dummy_hcd` + `g_mass_storage`, echtes USB-Gerät für udev), je FAT32 und NTFS: nach 3 s `ro` eingehängt (FAT32 mit
  `utf8`), Umlaute und „&“ in Ordner und Datei in der Bibliothek; Speichern per `ks-netmount` (wie nach dem Rippen, Ordner mit Umlaut)
  → Datei auf dem Stick, danach wieder `ro` (NTFS über Aus- und neu Einhängen); Abziehen per `authorized=0` mit offener Datei →
  nach ≤ 1 s ausgehängt, Ordner entfernt; Wiederanstecken nach 1 s eingehängt; fsck/ntfsfix sauber.
* Echter Stick (exFAT, 58,6 GB, USB 3, Stick des Nutzers mit eigenen Dateien), während Spotify spielte: `ro` eingehängt
  (`iocharset=utf8`); Speichern per `ks-netmount` in Testordner mit Umlauten und „&“ → Datei gleich (cmp), danach wieder `ro`,
  in der Bibliothek; Abziehen per `authorized=0` mit offener Datei → nach 1 s ausgehängt, Ordner entfernt, Mount-Wächter liest
  binnen 3 s neu ein; Wiederanstecken nach 2 s. Spotify lief ungestört weiter. Testordner danach gelöscht. `fsck.exfat` fehlte
  (wie `fsck.vfat`) → systemd prüfte exFAT/FAT beim Einhängen nicht, der Kernel meldete „not properly unmounted“. Installer bringt
  seit 0.2.16 `exfatprogs` und `dosfstools` mit; per apt nachinstalliert: beim Wiederanstecken „clean“, Warnung weg.
* Herunterfahren über `POST /api/system/power` (wie die Oberfläche, mit dem Nutzer, 0.2.16): Web nach 4 s weg, Ping nach 5 s;
  nach dem Einschalten Boot 22 s, Web zugleich mit dem ersten Ping, alle Dienste und Kiosk da, keine fehlgeschlagenen Units,
  Ausgabe HDMI 0, Stick wieder eingehängt, nichts spielt.
* CD (USB-Laufwerk SE-218GN am Thin Client, kein Überstrom; Autoplay aus): No Doubt „It’s My Life“, 4 Titel, MusicBrainz nach
  12 s. Rippen auf den echten exFAT-Stick (0.2.17): 3 min 40 s für 18 min Musik, Speichern 3 s, FLAC mit Tags und `cover.jpg`
  (`flac -t` ok), danach `ro`, sofort in der Bibliothek. Rückfall: Stick 0,3 s nach „Wird gespeichert …“ per `authorized=0`
  getrennt → erst 0-Byte-Dateien mit „ok“ (siehe Behobene Fehler), nach dem Fix „Kopieren fehlgeschlagen: No such device“,
  Album vollständig in `Lokal` mit Hinweis, auf dem Stick kein neuer Ordner, beim Wiederanstecken „clean“. Wiedergabe vom Stick
  stoppt beim Abziehen.
* Ohne Desktop-Unterstützung (0.2.18): Update per `install.sh --tv-headless` 31 s, EXIT 0, alle Dienste und Kiosk; mit
  gestelltem `display-manager.service` bricht der Installer sofort ab (EXIT 1, Meldung), ohne etwas zu ändern.
* Erscheinungsbilder (0.2.18, eingebauter Browser, per Skript): Oberfläche in allen sieben Themes bei 1280 und 390 px, je 22 Ansichten
  und Reiter (Wiedergabe, Bibliothek ×8, Radio ×3, CD, Optionen ×9) → keine Seite scrollt quer, nichts ragt heraus (Gegenprobe mit
  2000 px breitem Element schlägt an). `/tv` Ruhebildschirm in allen Themes bei 1920×1080, 1280×720, 1024×768, 800×600 und 390 px:
  nichts ragt heraus, kleinste Schrift 11 px. „Läuft gerade“ mit Titel nicht geprüft (nichts spielte).
* USB-WLAN (Edimax N150, RTL8188EU, 0.2.19): zuerst ohne Firmware („failed to load rtl8188eufw.bin“, Installer-Fehler, siehe
  Behobene Fehler), danach Firmware 28.0, NetworkManager verwaltet `wlx…`, Oberfläche zeigt das Netz (2,4 GHz), Verbinden durch den
  Nutzer. Dabei verlor das Kabel seine Adresse (ARP-Flux, siehe Lehren); nach dem Fix WLAN getrennt/neu ohne Konflikt.
* Feste IPv4 auf der WLAN-Verbindung (Kabel als Zugang, per API): 10.0.0.230 ohne Bestätigung → nach 120 s zurück auf DHCP (.168);
  mit Bestätigung → bleibt `manual` (130 s geprüft); auf DHCP und „Zurücknehmen“ → wieder fest; DHCP bestätigt → `auto`.
* Sperrbildschirm am iPhone (laut Nutzer): Titel, Cover, Pause/Weiter, Spulen mit richtiger Zeit.
* UPnP mit mconnect (iPhone, Titel vom Handy selbst, laut Nutzer): Titel, Pause/Weiter, Spulen, Lautstärke. Cover fehlte: mconnect
  schickt als `albumArtURI` einen Dateipfad des Handys (`…/private/var/mobile/…/tmp/8.jpg`), der immer 404 gibt → Klangstation prüft
  die Adresse einmal und nimmt sonst MusicBrainz (0.2.20); danach Cover über `/api/art`.
* Spotify nach UPnP (0.2.21, laut Nutzer und Protokoll): mconnect spielt, dann Pause (gmediarender hält HDMI) → Spotify meldet
  „sink busy“, Klangstation startet gmediarender neu (neue PID), HDMI frei, Spotify spielt nach ~1 s mit Ton.

### Behobene Fehler

**26.10.2026**

* NTFS-Sticks: Installer zieht `ntfs-3g`; `ks-netmount` schreibt auch auf `fuseblk`; Rip-Ziele
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
* Keine Meldung bei belegtem Ausgang (siehe Lehren); `avahi-utils` fehlte im Installer (`avahi-resolve` für den
  AirPlay-Gerätenamen).

**04.11.2026**

* Webradio blieb dauerhaft aus, wenn die Verbindung abriss und der Sender dabei nicht erreichbar war → Wächter verbindet neu
  (siehe Lehren). Stopp während des Neuversuchs startete den Sender später ungefragt wieder → beendet ihn jetzt (0.2.2).
* Belegter Ausgang: Play aus einer Pause blieb still stehen, ohne Hinweis und ohne neuen Versuch (siehe Lehren, 0.2.4).

**06.11.2026**

* Cover von Freigaben luden sehr langsam (bis 15 s je Bild) → `binarylimit` (siehe Lehren, 0.2.8).

**07.11.2026**

* AirPlay ohne Ton unter Debian ohne Desktop (dhcpcd, IPv6-Route über den Router) → dhcpcd-Hook (siehe Lehren, 0.2.9).
* Kiosk ohne Desktop am Laptop mit Fernseher über beide Bildschirme verteilt → cage `-m last` (siehe Lehren, 0.2.9).

**17.11.2026** (0.2.11, nur lokal mit TestClient geprüft, noch nicht auf einem Gerät)

* Prüfung auf Sicherheit und Slop: CSRF ohne Passwort, MPD-Befehle über Zeilenumbrüche, Symlinks im root-Helfer (siehe Sicherheit).
  Falscher Datentyp in Anfragen gibt 400 statt 500, Cookie mit Nicht-ASCII, zwei gleichzeitige Uploads derselben Datei.
  Badges der Ausgänge: „ANALOG“ war abgeschnitten, jetzt eine Farbe und normale Schreibung.

**25.11.2026**

* Rippen auf USB: Abziehen beim Speichern ergab „gerippt“ mit leeren Dateien auf dem Stick, Album verloren → `fsync` (0.2.17).
* Rippen blieb ohne Meldung auf „läuft“ stehen, wenn der Arbeitsordner nicht angelegt werden konnte → Fehler im Auftrag (0.2.17).
* WLAN-Firmware wurde unter Debian nie installiert (`| grep -q` mit pipefail) → Ausgabe erst einsammeln (0.2.19).
* WLAN verbunden → Kabel verlor seine Adresse (ARP-Flux) → `arp_ignore`/`arp_announce` (0.2.19).
* UPnP ohne Cover, wenn die App eine nicht abrufbare Bildadresse schickt (mconnect) → prüfen, sonst MusicBrainz (0.2.20).
* Spotify nach UPnP: Titel liefen nur Sekunden, kein Ton (gmediarender hielt HDMI, „belegt“ auf Deutsch) → Locale, Freigabe (0.2.21).
