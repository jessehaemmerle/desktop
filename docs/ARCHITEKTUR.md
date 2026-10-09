# Prisma – Architektur

## Leitentscheidungen

| Entscheidung | Begründung |
|---|---|
| **labwc als Compositor** | Ein eigener Compositor wäre ein Mehrjahresprojekt. labwc ist ein schlanker, stabiler wlroots-Compositor (Standard in Raspberry Pi OS), liegt in Ubuntu ab 24.04 im Archiv und bietet alle Protokolle, die eine Shell braucht: `wlr-layer-shell`, `wlr-foreign-toplevel-management`, `virtual-keyboard`, Screencopy. Prisma liefert eine eigene labwc-Konfiguration aus. |
| **GTK 3 + gtk-layer-shell für die Shell** | `gir1.2-gtklayershell-0.1` ist in Ubuntu 24.04 paketiert (das GTK-4-Pendant erst ab 24.10). So läuft Prisma auf der LTS-Basis von Mint, Pop!_OS, Zorin & Co. |
| **GTK 4 + libadwaita für die Einstellungen** | Normale App-Fenster profitieren von den modernen libadwaita-Bausteinen. |
| **Eigener Wayland-Client in reinem Python** | `python3-pywayland` ist in Ubuntu 24.04 nicht paketiert. Das Wire-Protokoll ist einfach (`prisma/wayland/wire.py`); für die Fensterliste braucht es nur `wl_registry`, `wl_seat` und den Toplevel-Manager. |
| **Facetten über Minimieren statt über Arbeitsflächen** | Funktioniert mit jedem Compositor, der `foreign-toplevel` unterstützt, und benötigt keine Compositor-IPC. Prisma merkt sich, welche Fenster *es selbst* versteckt hat – manuell minimierte Fenster bleiben minimiert. |
| **Logik strikt ohne GTK** | `prisma/core/` und `prisma/wayland/` importieren kein `gi` und sind vollständig mit pytest getestet. |

## Prozesse

```
Display-Manager ─► prisma-session ─► labwc -C ~/.config/prisma/labwc
                                        └─ autostart ─► prisma-shell
                                                        polkit-Agent, swayidle(→ prisma-lock), kanshi
Tastenkürzel (rc.xml) ─► prisma-msg <aktion> ─D-Bus─► prisma-shell (org.gtk.Actions)
prisma-settings ─schreibt─► ~/.config/prisma/config.json ─Gio.FileMonitor─► prisma-shell
```

## Die Shell (`prisma/shell/`)

* **`app.py`** – `Gtk.Application` (`at.haemmerle.Prisma.Shell`), registriert alle Aktionen, die
  `prisma-msg` aufruft, baut die Oberflächen und verwaltet Overlays (immer nur eins offen).
* **`hub.py`** – zentraler Zustand mit GObject-Signalen: `facet-changed`, `theme-changed`,
  `focus-changed`, `dnd-changed`, `config-changed`, `toast`. Zählt die Zeit pro Facette, prüft
  alle 30 s Tageslicht-Modus und Zeitregeln (flankengesteuert) und speichert den Zustand in
  `~/.local/state/prisma/state.json`.
* **`windows.py`** – verbindet den Wayland-Client mit der `FacetWindowPolicy`. Wird ein Fenster einer
  anderen Facette aktiviert (Alt+Tab, App holt sich den Fokus), folgt Prisma dorthin – außer in den
  ersten 0,8 s nach einem eigenen Wechsel, damit sich Minimieren und Fokuswechsel nicht aufschaukeln.
* **`styling.py`** – erzeugt aus Facettenfarbe + Hell/Dunkel eine Palette (`core/theme.py`), lädt das
  Shell-CSS, schreibt `~/.local/share/themes/Prisma/openbox-3/themerc` und ruft
  `labwc --reconfigure` auf. Zusätzlich werden `color-scheme` und das passende `-dark`-GTK-Thema
  gesetzt, damit Apps dem Tageslicht folgen.
* **`notifications.py`** – Benachrichtigungsdienst nach freedesktop-Spezifikation 1.2. Jede Meldung
  läuft durch `core.policy.notification_route()`: kritisch → immer Popup; Nicht stören, Fokus oder
  Facettenregel → still sammeln. Während einer Fokus-Session gesammelte Meldungen bilden den Rückblick.
* **`overlay.py`** – Vollflächige, transparente Layer-Oberflächen. Klick außerhalb der Karte oder
  Escape schließt. Bewusst ohne `Gtk.Revealer`, der den Kartenschatten abschneiden würde; die
  Animation läuft über CSS-Übergänge.
* **`providers.py`** – Ergebnisquellen des Kompass. Die Rangfolge kombiniert unscharfe Suche
  (`core/fuzzy.py`, mit Umlaut-Faltung und Initialen) mit Frecency (`core/frecency.py`,
  Halbwertszeit 7 Tage). Der Dateiindex wird in einem Hintergrund-Thread aufgebaut.

## Datenablage

| Pfad | Inhalt |
|---|---|
| `~/.config/prisma/config.json` | Einstellungen (Facetten, Regeln, Darstellung, Fokus, Kompass) |
| `~/.config/prisma/labwc/` | labwc-Konfiguration (beim ersten Start kopiert, danach dir) |
| `~/.local/state/prisma/state.json` | aktive Facette, Nicht stören, Zeitstatistik (14 Tage) |
| `~/.local/state/prisma/frecency.json` | Nutzungshistorie des Kompass |
| `~/.local/share/themes/Prisma/` | live erzeugtes labwc-Thema |
| `$XDG_RUNTIME_DIR/prisma-shell.log` | Log der Shell |

## Erweitern

* **Neue Kompass-Quelle:** Methode in `Providers` ergänzen und in `query()` einhängen; Ergebnisse sind
  `Result`-Objekte mit `title`, `subtitle`, `icon`, `score` und `action`.
* **Neue Aktion für Tastenkürzel:** in `PrismaShell._add_actions()` registrieren, in `msg.py`
  dokumentieren, in `data/labwc/rc.xml` binden – `tests/test_data.py` prüft, dass alles zusammenpasst.
