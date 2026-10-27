# ADR-0001: Architektur von Tenwin

**Status:** Akzeptiert
**Datum:** 2026-10-27
**Entscheider:** Projektinhaber (Jesse Hämmerle)

## Kontext

Tenwin soll ein Linux-Desktop sein, der sich wie der Desktop von Windows 10
anfühlt und so aussieht. Vorgaben:

- Zielplattform: Ubuntu 24.04 LTS und neuer (inkl. Ableitungen), **Wayland**.
- Umfang der ersten Version: Taskleiste, Startmenü mit Kacheln, Suche
  (Apps, Einstellungen, Dateien), Info-Center mit Benachrichtigungen,
  Fensterverwaltung im Win10-Stil (Snap, Alt+Tab, Win+Tab, Win-Tastenkürzel),
  Desktop-Symbole, Sperr- und Anmeldebildschirm, Einstellungen-App, eigener
  Explorer mit Menüband.
- Hell- und Dunkelmodus frei wählbar, Oberfläche auf Deutsch und Englisch.
- Installation per `.deb` und `install.sh`.
- Keine Original-Assets von Microsoft (Logo, Segoe UI, Icons, Hintergründe).

## Entscheidung

Eine **eigene Shell in Python 3 + GTK 3 + gtk-layer-shell** auf dem
Wayland-Compositor **labwc** (0.7.1 in Ubuntu 24.04), ergänzt um zwei
kleine **C-Helfer**:

| Komponente | Technik | Aufgabe |
|---|---|---|
| `labwc` | Fremdpaket | Fensterverwaltung, Titelleisten (Tenwin-Theme), Snap, virtuelle Desktops, Tastenkürzel |
| `tenwin-shell` | Python/GTK3, layer-shell | Taskleiste, Startmenü, Suche, Info-Center, Benachrichtigungs-Daemon, Infobereich (SNI), Alt+Tab, Aktivitätsansicht, Flyouts, OSD, Win+X, Ausführen |
| `tenwin-desktop` | Python/GTK3, layer-shell (Hintergrund-Ebene) | Hintergrundbild, Desktop-Symbole, Kontextmenü |
| `tenwin-explorer` | Python/GTK3 | Dateimanager mit Menüband, Navigationsbereich, „Dieser PC“ |
| `tenwin-settings` | Python/GTK3 | Einstellungen-App, Willkommensdialog (Hell/Dunkel) |
| `tenwin-greeter` | Python/GTK3, LightDM-GI | Anmeldebildschirm (eigenes Paket) |
| `tenwin-toplevel` | C, `wlr-foreign-toplevel-management` | Fensterliste als JSON-Zeilen für die Shell |
| `tenwin-lock` | C, `ext-session-lock-v1`, PAM, Cairo/Pango | Sperrbildschirm |
| `tenwin-ctl` | sh + `gdbus` | schnelle Befehle von labwc-Tastenkürzeln an die Shell |

Prozesse kommunizieren über D-Bus (`org.tenwin.Shell`) und eine gemeinsame
Konfigurationsdatei `~/.config/tenwin/settings.json`, die per Dateimonitor
beobachtet wird. Die labwc-Konfiguration wird aus dieser Datei erzeugt
(`~/.config/tenwin/labwc/`) und per `labwc --reconfigure` neu geladen.

## Betrachtete Optionen

### Option A: Eigene Shell + labwc (gewählt)

| Dimension | Bewertung |
|---|---|
| Komplexität | Mittel |
| Originaltreue | Hoch (alle sichtbaren Shell-Teile selbst gezeichnet) |
| Stabilität | Hoch (labwc ist ausgereift und schlank) |
| Wartbarkeit | Gut, Python für die UI, nur zwei kleine C-Programme |

**Vorteile:** Volle Kontrolle über Aussehen und Verhalten; labwc-Titelleisten
lassen sich per SVG-Buttons exakt im Win10-Stil gestalten (rote
Schließen-Schaltfläche beim Überfahren); Session-Lock und Layer-Shell werden
unterstützt.
**Nachteile:** labwc 0.7.1 hat keine IPC-Schnittstelle, keine
`onRelease`-Tastenbindungen und kein Protokoll für Fenstervorschauen.

### Option B: Wayfire

**Vorteile:** Live-Vorschau in der Aktivitätsansicht, Animationen.
**Nachteile:** In Ubuntu 24.04 nur als Git-Snapshot, Titelleisten kaum im
Win10-Stil gestaltbar. Verworfen (Entscheidung des Projektinhabers).

### Option C: Theming eines vorhandenen Desktops (Cinnamon, Plasma)

**Vorteile:** Geringer Aufwand.
**Nachteile:** Deutlich weniger Originaltreue, kaum Einfluss auf Startmenü
und Info-Center. Verworfen.

## Abwägungen und Lösungen für Lücken in labwc 0.7.1

- **Win-Taste allein öffnet das Startmenü:** labwc bindet `Super_L` auf
  `tenwin-ctl super`. Die Shell öffnet daraufhin eine unsichtbare
  Layer-Fläche mit exklusivem Tastaturfokus und wartet, bis die Win-Taste
  losgelassen wird (Modifikator-Status über `Gdk.Keymap::state-changed`).
  Kommt vorher ein anderes Win-Kürzel (jedes ruft `tenwin-ctl` auf) oder
  eine andere Taste, wird das Öffnen abgebrochen. So gibt es kein Flackern
  bei Win+E usw.
- **Alt+Tab im Win10-Stil:** dasselbe Prinzip. Jedes Alt+Tab schaltet weiter,
  das Loslassen von Alt aktiviert das gewählte Fenster.
- **Keine Fenstervorschau:** Aktivitätsansicht und Alt+Tab zeigen große
  App-Symbole und Fenstertitel statt Live-Bildern.
- **Virtuelle Desktops:** labwc-eigene Desktops mit den Win10-Kürzeln
  Strg+Win+←/→. Die Aktivitätsansicht kann sie mangels IPC nicht steuern.
- **Sperrbildschirm:** eigener C-Helfer mit `ext-session-lock-v1`. Stürzt er
  ab, bleibt die Sitzung trotzdem gesperrt (Garantie des Protokolls). Das
  ist der Grund, warum wir nicht `gtklock` (nutzt `wlr-input-inhibitor`)
  verwenden.
- **Anmeldebildschirm:** LightDM-Greeter (läuft unter X11, startet danach die
  Wayland-Sitzung). Er ist ein eigenes Paket, weil der Wechsel von GDM zu
  LightDM das ganze System betrifft.
- **Einstellungsisolation:** Die Sitzung nutzt ein eigenes dconf-Profil
  (`DCONF_PROFILE`), damit GTK-Theme, Schrift usw. eine parallel genutzte
  GNOME-Sitzung nicht verändern.
- **Schrift:** Selawik (Microsoft, SIL OFL 1.1) als metrisch kompatibler,
  frei lizenzierter Ersatz für Segoe UI, mit Rückfall auf Noto Sans.

## Konsequenzen

- Leichter: Anpassungen am Aussehen (nur CSS/SVG), Übersetzungen (gettext),
  Tests der Python-Logik ohne Compositor.
- Schwerer: Funktionen, die Compositor-Unterstützung brauchen (Vorschauen,
  Desktop-Steuerung aus der Aktivitätsansicht), bis labwc ≥ 0.8 verfügbar
  ist.
- Neu bewerten, sobald Ubuntu labwc ≥ 0.8 ausliefert (`onRelease`,
  `ext-workspace`, Fenster-Icons in Titelleisten).

## Umsetzungsschritte

1. [x] Grundgerüst, Session, labwc-Konfiguration, Themes
2. [x] C-Helfer `tenwin-toplevel`, `tenwin-lock`
3. [x] Shell
4. [x] Desktop, Explorer, Einstellungen
5. [x] Greeter, Paketierung, Tests
