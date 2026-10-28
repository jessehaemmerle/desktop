# Tenwin

**Deutsch** | [English](README.en.md)

Ein Desktop-Environment für Ubuntu-basierte Linux-Distributionen, das aussieht und sich bedient wie der Desktop von **Windows 10**, auf Basis von Wayland und dem Compositor [labwc](https://labwc.github.io/).

![Tenwin](docs/screenshots/01-desktop.png)

## Funktionen

| Bereich | Was dabei ist |
|---|---|
| **Taskleiste** | Start-Button, Suchfeld „Zur Suche Text hier eingeben“, Aktivitätsansicht, angeheftete und laufende Apps (Unterstrich, Gruppierung, Sprungliste per Rechtsklick), Infobereich mit Tray-Symbolen (StatusNotifierItem), Netzwerk, Lautstärke, Akku, Uhr mit Kalender, Info-Center-Button mit Zähler, „Desktop anzeigen“-Leiste. Anpassbar per Rechtsklick oder in den Einstellungen: Suche als Feld, nur als Symbol oder ausgeblendet; Aktivitätsansicht- und „Desktop anzeigen“-Schaltfläche ein/aus; Schaltflächen immer, bei Überfüllung oder nie gruppieren (dann mit Fenstertitel); kleine Schaltflächen; oben oder unten; Aero Peek. Bei mehreren Bildschirmen auf jedem eine Taskleiste, wahlweise mit allen Fenstern oder nur denen des jeweiligen Bildschirms. Angeheftete Apps per Drag & Drop umsortieren oder aus dem Startmenü auf die Taskleiste ziehen. Rechtsklick: Fenster überlappend, gestapelt oder nebeneinander anzeigen |
| **Startmenü** | Linke Leiste (Konto, Dokumente, Bilder, Einstellungen, Ein/Aus), alphabetische App-Liste mit Buchstaben-Sprungraster, „Zuletzt hinzugefügt“, „Meistverwendet“, Kacheln in Gruppen/Kategorien (Klein/Mittel/Breit/Groß, Live-Kalenderkachel, Drag & Drop zwischen Gruppen, „Neue Gruppe“-Ablage, Gruppen umbenennen/verschieben/lösen, „Alle Kacheln nach Kategorien ordnen“ nach Büro, Internet, Medien, Grafik, Entwicklung, Spiele, System, Zubehör). Apps, Ordner und Dateien lassen sich über „An Start anheften ▸“ (auch im Explorer und auf dem Desktop) direkt in eine Gruppe heften. Kachelordner (Kachel auf Kachel ziehen), Kachelfarben, Live-Kacheln (Kalender, Diashow aus „Bilder“, zuletzt verwendete Dateien im Explorer). Größe per Ziehen an Rand oder Ecke änderbar, weitere Kachelspalten erscheinen automatisch. Tippen startet die Suche |
| **Suche** | Apps, Einstellungsseiten, Dateien und Ordner im Home-Verzeichnis, Tabs, „Höchste Übereinstimmung“ mit Detailbereich |
| **Info-Center** | Benachrichtigungen nach App gruppiert, schnelle Aktionen (Netzwerk, Bluetooth, Nachtmodus, Flugzeugmodus, Ruhezeiten, Bildschirmausschnitt, Stromsparmodus, VPN, Sperren), Helligkeitsregler |
| **Benachrichtigungen** | Eigener `org.freedesktop.Notifications`-Dienst mit Toasts unten rechts, Aktionen, Ruhezeiten |
| **Fenster** | Titelleisten im Win10-Stil (rote Schließen-Schaltfläche), Aero Snap (an Ränder ziehen, Win+Pfeiltasten) mit **Snap Assist** (nach Win+←/→ das Fenster für die andere Hälfte auswählen) und **Viertel-Snap** (Win+↑/↓ auf einer Hälfte, Ziehen mit gedrückter Win-/Strg-/Alt-/Umschalt-Taste in eine Ecke), Alt+Tab, Aktivitätsansicht (Win+Tab), virtuelle Desktops (Strg+Win+←/→) |
| **Desktop** | Hintergrundbild oder Volltonfarbe (Füllen/Anpassen/Strecken/Kacheln/Zentriert), Desktopsymbole (Papierkorb, Dieser PC, Dateien), Kontextmenü, Umbenennen, Kopieren/Einfügen, Drag & Drop |
| **Explorer** | Menüband (Datei, Start, Freigeben, Ansicht, Papierkorbtools), Adressleiste mit Pfadnavigation, Suche, Navigationsbereich, Vorschaufenster (Alt+P, Bilder und Text) und Detailbereich (Alt+Umschalt+P), „Schnellzugriff“, „Dieser PC“ mit Speicherbalken und Netzwerkadressen, „Netzlaufwerk verbinden“ (`\\server\freigabe`, SMB, SFTP, FTP, WebDAV über GVfs, Anmeldung bei Bedarf), ISO-/IMG-Abbilder bereitstellen, Abbilder brennen (Brasero/Xfburn), sechs Ansichten, Eigenschaften (inkl. Berechtigungen), ZIP packen/entpacken, Papierkorb mit Wiederherstellen |
| **Task-Manager** | Strg+Umschalt+Esc: „Weniger Details“ und „Mehr Details“, Prozesse (Apps und Hintergrundprozesse mit CPU, Arbeitsspeicher, Datenträger, farbig hinterlegt), Leistung (Verlaufsgrafen für CPU, Arbeitsspeicher, Datenträger, Netzwerk), Autostart (aktivieren/deaktivieren), Details (PID, Status, Benutzer, Befehlszeile), Task beenden |
| **Tablet-Modus** | Schnelle Aktion im Info-Center: Start im Vollbild, Apps maximiert, größere Taskleisten-Schaltflächen. **Bildschirmtastatur** (Strg+Win+O oder Taskleisten-Schaltfläche) mit QWERTZ/QWERTY, Umschalt, Feststelltaste und Sonderzeichen-Ansicht |
| **Spieleleiste** | Win+G: Screenshot, Bildschirmaufzeichnung (wf-recorder) mit Timer, Lautstärke und Mikrofon, CPU- und RAM-Anzeige. Spielmodus startet Spiele mit Feral GameMode |
| **Einstellungen** | 11 Kategorien und 43 Seiten wie bei Windows 10: Bildschirm, Sound, Benachrichtigungen, Netzbetrieb, Speicher, Tablet-Modus, Multitasking, Info, Bluetooth, Drucker, Maus, Tastatur, Netzwerk, Hintergrund, Farben (Hell/Dunkel, Akzentfarbe selbst wählen, automatisch aus dem Hintergrundbild oder neutral „Dunkel“, Farben in Qt-/Firefox-/Flatpak-Apps), Sperrbildschirm, Designs (speichern und wechseln, Mauszeiger), Schriftarten (Vorschau, installieren per Drag & Drop), Start, Taskleiste, Apps, Standard-Apps, Autostart, Konto, Datum/Uhrzeit, Region/Sprache, Spielen (Spieleleiste, Aufzeichnungen, Spielmodus), Erleichterte Bedienung (Anzeige, Bildschirmlupe, hoher Kontrast mit vier Kontrastdesigns, Sprachausgabe mit Orca, Bildschirmtastatur), Datenschutz (Position, Kamera, Mikrofon), Update |
| **Andere Apps** | Qt-/KDE-Apps übernehmen Farben, Akzent und Schrift über qt5ct (sonst das GTK-Design), Firefox und Thunderbird auf Wunsch eckige Tabs mit Akzentlinie und roter Schließen-Schaltfläche (userChrome.css), Flatpak-Apps auf Wunsch das Tenwin-GTK-Design |
| **Sperrbildschirm** | Win+L: Uhr und Datum unten links, nach Tastendruck Profilbild und Kennwortfeld auf weichgezeichnetem Hintergrund. Nutzt `ext-session-lock-v1`: Auch wenn der Sperrbildschirm abstürzt, bleibt die Sitzung gesperrt |
| **Anmeldebildschirm** | Eigener LightDM-Greeter im selben Stil, mit Benutzerliste, Sitzungswahl und Ein/Aus-Menü (optional) |
| **Sonstiges** | Win+X-Menü, Ausführen-Dialog (Win+R), Lautstärke-/Helligkeits-OSD, Screenshots (Druck, Win+Umschalt+S), Willkommensdialog zur Wahl von Hell oder Dunkel, Deutsch und Englisch |

### Tastenkürzel

| Kürzel | Aktion |
|---|---|
| Win | Startmenü |
| Win+E / Win+R / Win+I | Explorer / Ausführen / Einstellungen |
| Win+A / Win+S | Info-Center / Suche |
| Win+D / Win+M | Desktop anzeigen / alle minimieren |
| Win+L | Sperren |
| Win+X | Win+X-Menü |
| Win+Tab / Alt+Tab | Aktivitätsansicht / Fenster wechseln |
| Win+←/→/↑/↓ | Andocken, maximieren, wiederherstellen/minimieren |
| Strg+Win+←/→ | Virtuellen Desktop wechseln |
| Win+1…0 | App an Position 1…10 der Taskleiste |
| Win+Leertaste | Eingabesprache wechseln (bei mehreren Layouts) |
| Strg+Umschalt+Esc | Task-Manager |
| Win+G / Win+Alt+R / Win+Alt+Druck | Spieleleiste / Aufzeichnung starten/beenden / Screenshot nach „Aufzeichnungen“ |
| Win+Plus / Win+Minus / Win+Esc | Bildschirmlupe ein bzw. vergrößern / verkleinern / aus |
| Strg+Win+Eingabe | Sprachausgabe ein/aus |
| Strg+Win+O | Bildschirmtastatur |
| Druck / Win+Umschalt+S | Screenshot / Bildschirmausschnitt |
| Alt+F4 | Fenster schließen |

## Installation

Voraussetzung: **Ubuntu 24.04 LTS** oder neuer (oder eine Ableitung wie Linux Mint 22, Pop!_OS 24.04, Zorin OS 18). Ältere Versionen haben kein ausreichend neues labwc.

```bash
git clone https://github.com/jessehaemmerle/desktop.git tenwin
```

```bash
cd tenwin && ./install.sh
```

Das Skript installiert die Build-Abhängigkeiten, baut die Pakete `tenwin-desktop` und `tenwin-greeter` und installiert sie mit `apt`. Dabei werden alle Laufzeit-Abhängigkeiten nachgeladen. Es fragt außerdem, ob der Anmeldebildschirm im Win10-Stil eingerichtet werden soll. Dafür wird der Anmeldemanager von GDM auf LightDM umgestellt; das betrifft alle Benutzer des Rechners.

Optionen: `--with-greeter`, `--no-greeter`, `--yes`.

Danach abmelden und im Anmeldebildschirm die Sitzung **Tenwin** wählen. Beim ersten Start fragt Tenwin, ob Sie den hellen oder dunklen Modus möchten.

### Nur die Pakete bauen

```bash
make deb
```

Die `.deb`-Dateien landen im übergeordneten Verzeichnis.

### Entfernen

```bash
./uninstall.sh
```

Das Skript stellt einen von `install.sh` umgestellten Anmeldemanager wieder her. Mit `--purge` werden zusätzlich die Tenwin-Einstellungen des aktuellen Benutzers gelöscht.

## Ausprobieren ohne Installation

Innerhalb einer laufenden Desktop-Sitzung (X11 oder Wayland) startet Tenwin in einem Fenster:

```bash
sudo apt install labwc gir1.2-gtklayershell-0.1 python3-gi swayidle grim slurp wl-clipboard wlr-randr pulseaudio-utils build-essential libwayland-dev wayland-protocols libxkbcommon-dev libcairo2-dev libpango1.0-dev libgdk-pixbuf-2.0-dev libpam0g-dev gettext
```

```bash
tools/dev-session.sh
```

Die Testsitzung nutzt eine eigene Einstellungsdatei (`~/.config/tenwin-dev`) und einen eigenen D-Bus und verändert den laufenden Desktop nicht. Der Sperrbildschirm braucht im Testbetrieb die PAM-Datei aus `data/pam/tenwin-lock` unter `/etc/pam.d/`.

## Aufbau

Die Architekturentscheidungen stehen in [docs/adr/0001-architektur.md](docs/adr/0001-architektur.md) und [docs/adr/0002-fensterverwaltung.md](docs/adr/0002-fensterverwaltung.md) (Fensteraktionen über eine virtuelle Tastatur, weil labwc 0.7 keine IPC hat).

```
bin/          Startskripte (tenwin-session, tenwin-ctl, tenwin-shell, …)
helpers/      C-Programme: tenwin-lock (Sperrbildschirm), tenwin-toplevel (Fensterliste),
              tenwin-vkbd (virtuelle Tastatur für Fensteraktionen und Bildschirmtastatur)
src/tenwin/   Python-Paket
  shell/      Taskleiste, Startmenü, Suche, Info-Center, Benachrichtigungen, Tray, Alt+Tab …
  desktop/    Hintergrund und Desktopsymbole
  explorer/   Dateimanager
  settings/   Einstellungen-App
  taskmgr/    Task-Manager
  greeter/    LightDM-Anmeldebildschirm
  services/   Audio, Netzwerk, Energie, Bluetooth, Anzeige, Sitzung
data/         CSS, Themes (GTK + labwc), Icons, Hintergründe, Schrift, Sitzung, PAM, LightDM
po/           Übersetzungen (de)
tools/        Asset-Generatoren, Headless-Tests, Dev-Sitzung
tests/        Unit-Tests (pytest)
debian/       Paketierung
```

Die Einstellungen liegen in `~/.config/tenwin/settings.json`. Alle Tenwin-Programme beobachten diese Datei. Die labwc-Konfiguration in `~/.config/tenwin/labwc/` wird daraus erzeugt und bei Änderungen neu geladen. GTK-Einstellungen der Tenwin-Sitzung stehen in einer eigenen dconf-Datenbank, damit eine GNOME-Sitzung auf demselben Konto unverändert bleibt.

## Entwicklung

```bash
make            # C-Helfer und Übersetzungen bauen
make check      # Unit-Tests
make smoke      # komplette Sitzung headless starten, Screenshots nach build/screenshots/
make pot        # Übersetzungsvorlage aktualisieren
```

Die Grafiken (Titelleisten-Buttons, Symbole, Hintergründe, GTK-Themes) werden von `tools/gen_assets.py` und `tools/gen_gtk_theme.py` erzeugt.

## Bekannte Grenzen

Diese Punkte hängen an labwc 0.7.1, das Ubuntu 24.04 mitliefert:

- **Keine Fenstervorschau** in Alt+Tab, Aktivitätsansicht und beim Überfahren der Taskleiste. Angezeigt werden große App-Symbole und Fenstertitel.
- **Virtuelle Desktops** lassen sich nur per Tastenkürzel wechseln, nicht aus der Aktivitätsansicht. Die Taskleiste zeigt die Fenster aller Desktops.
- Die **Win-Taste allein** wird über einen Umweg erkannt (siehe ADR). Wurde sie in der Testumgebung nicht verifiziert, weil es dort keine Eingabegeräte gab.
- **Viertel-Snap per Ziehen** klappt nur mit gedrückter Win-, Strg-, Alt- oder Umschalt-Taste; ohne Taste dockt labwc nur an Hälften an.
- Tenwin sieht die Fenstergeometrie nicht. Wird ein angedocktes Fenster von Hand weggezogen, geht Win+↑/↓ noch vom alten Zustand aus. „Fenster anordnen“ erfasst auch Fenster anderer virtueller Desktops.
- Die **Bildschirmlupe** zeigt mit labwc 0.7 ein vergrößertes Standbild, das der Maus folgt (Win+Plus aktualisiert es). Ab labwc 0.8 nutzt Tenwin die eingebaute Live-Lupe.
- Die **Bildschirmtastatur** öffnet sich nicht automatisch bei Texteingaben (labwc 0.7 unterstützt kein text-input-Protokoll).
- **Kamera** und **Position** lassen sich nur für Apps sperren, die über xdg-desktop-portal fragen (z. B. Flatpak). Für das **Mikrofon** gibt es unter Linux keine App-Berechtigung; „aus“ schaltet es stumm.
- Qt-6-Apps übernehmen das Design nur über das gtk3-Plattformdesign, nicht über qt5ct.

## Rechtliches

Tenwin steht unter der **GPL-3.0** (siehe `LICENSE`). Es ist ein unabhängiges Projekt und nicht mit Microsoft verbunden. „Windows“ ist eine Marke der Microsoft Corporation. Alle Grafiken in diesem Repository sind eigene Arbeiten. Die mitgelieferte Schrift **Selawik** stammt von Microsoft und steht unter der SIL Open Font License 1.1 (`data/fonts/OFL-Selawik.txt`). Die Protokolldateien `wlr-foreign-toplevel-management-unstable-v1.xml` (wlr-protocols) und `virtual-keyboard-unstable-v1.xml` (wlroots) stehen unter MIT-ähnlichen Lizenzen.
