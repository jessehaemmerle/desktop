# ADR-0002: Fensteraktionen ohne IPC (virtuelle Tastatur)

**Status:** Akzeptiert
**Datum:** 2026-10-28
**Entscheider:** Projektinhaber (Jesse Hämmerle)

## Kontext

Snap Assist, Viertel-Snap mit Win+↑/↓, „Fenster überlappend/gestapelt/nebeneinander
anzeigen“ und die Bildschirmtastatur brauchen Fensteraktionen, die die Shell
auslösen kann. labwc 0.7.1 (Ubuntu 24.04) hat aber **keine IPC-Schnittstelle**.
`wlr-foreign-toplevel` kann Fenster nur aktivieren, minimieren, maximieren und
schließen; Position und Größe sind von außen weder les- noch setzbar.

labwc führt Tastenkürzel jedoch auch für **virtuelle Tastaturen**
(`zwp_virtual_keyboard_v1`) aus und vergleicht dabei Keysyms
(`src/input/keyboard.c`, `match_keybinding`).

## Entscheidung

1. Der C-Helfer **`tenwin-vkbd`** sendet Tastenkombinationen über eine
   virtuelle Tastatur (`tenwin-vkbd combo C-A-S-XF86Launch1`) bzw. tippt im
   `--stdin`-Modus für die Bildschirmtastatur mit dem Tastaturlayout des
   Benutzers.
2. `rc.xml` enthält **versteckte Tastenkürzel**: drei bis vier Modifikatoren
   plus selten vorhandene Keysyms (`XF86Launch1…B`, `XF86Tools`), die auf jeder
   evdev-Tastaturbelegung existieren. Sie lösen `SnapToEdge`, `SnapToRegion`
   und – für Anordnungen – `MoveRelative 0 0` (entkoppelt ein angedocktes
   Fenster) + `MoveTo` + `ResizeTo` aus. Die Tabellen stehen in `tenwin/wm.py`.
3. Ablauf in der Shell (`WindowManager.run_action`): Zielfenster per
   foreign-toplevel aktivieren, auf das `activated`-Ereignis warten, dann die
   Kombination senden. Aktionen laufen nacheinander in einer Warteschlange.
4. **Regionen** `tw-tl`, `tw-tr`, `tw-bl`, `tw-br`, `tw-left`, `tw-right` sind
   immer definiert. labwc wählt beim Ziehen mit gedrückter Modifikatortaste die
   Region mit dem nächstgelegenen Mittelpunkt – Ecken ergeben also Viertel, die
   Mitte einer Seite eine Hälfte.
5. Für Anordnungen werden die Pixel-Geometrien der „Slot“-Tastenkürzel vor jeder
   Anordnung neu in `rc.xml` geschrieben (`labwc --reconfigure`). Temporäre
   Regionen scheiden aus: Entfernt man eine Region, setzt labwc alle darin
   angedockten Fenster auf ihre ursprüngliche Größe zurück.
6. Weil die Geometrie unsichtbar bleibt, merkt sich die Shell, wie sie ein
   Fenster angedockt hat (`tenwin/shell/snap.py`). Win+←/→ sind weiterhin
   direkte labwc-Kürzel (`SnapToEdge`) und melden sich anschließend mit
   `tenwin-ctl snapped left|right`.

## Konsequenzen

- Funktioniert mit dem labwc aus Ubuntu 24.04, ohne labwc zu patchen.
- Zieht der Benutzer ein angedocktes Fenster von Hand weg, kennt die Shell das
  nicht; der nächste Win+↑/↓ geht vom gemerkten Zustand aus.
- Fenster auf anderen virtuellen Desktops werden beim Anordnen mit erfasst,
  weil foreign-toplevel keine Desktop-Zuordnung liefert.
- Physische Tastaturen mit XF86Launch-Tasten könnten die versteckten Kürzel nur
  zusammen mit drei Modifikatoren auslösen.
- Ab labwc 0.8 sind die eingebaute Bildschirmlupe und weitere Aktionen
  verfügbar; Tenwin nutzt die Lupe dann direkt (`session.labwc_version()`).
