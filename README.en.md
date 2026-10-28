# Tenwin

[Deutsch](README.md) | **English**

A desktop environment for Ubuntu-based Linux distributions that looks and works like the **Windows 10** desktop, built on Wayland and the [labwc](https://labwc.github.io/) compositor.

![Tenwin](docs/screenshots/01-desktop.png)

## Features

| Area | What's included |
|---|---|
| **Taskbar** | Start button, "Type here to search" box, Task View, pinned and running apps (underline, grouping, jump list on right-click), notification area with tray icons (StatusNotifierItem), network, volume, battery, clock with calendar, action center button with counter, "Show desktop" strip. Customizable via right-click or Settings: search as a box, as an icon only or hidden; Task View and "Show desktop" buttons on/off; combine buttons always, when the taskbar is full or never (then with window titles); small buttons; top or bottom; Aero Peek. With several displays a taskbar on each, showing all windows or only those on that display. Reorder pinned apps by drag and drop, or drag apps from Start onto the taskbar. Right-click: cascade windows, show them stacked or side by side |
| **Start menu** | Left rail (account, Documents, Pictures, Settings, Power), alphabetical app list with letter jump grid, "Recently added", "Most used", tiles in groups/categories (small/medium/wide/large, live calendar tile, drag and drop between groups, "New group" drop target, rename/move/unpin groups, "Sort all tiles into categories" by Office, Internet, Media, Graphics, Development, Games, System, Accessories). Apps, folders and files can be pinned straight into a group via "Pin to Start ▸" (also in File Explorer and on the desktop). Tile folders (drop a tile on another one), tile colors, live tiles (calendar, slideshow from Pictures, recent files on the File Explorer tile). Resizable by dragging its edge or corner; more tile columns appear automatically. Typing starts a search |
| **Search** | Apps, settings pages, files and folders in the home directory, tabs, "Best match" with a detail pane |
| **Action center** | Notifications grouped by app, quick actions (network, Bluetooth, night light, airplane mode, focus assist, screen snip, battery saver, VPN, lock), brightness slider |
| **Notifications** | Own `org.freedesktop.Notifications` service with toasts in the bottom right corner, actions, focus assist |
| **Windows** | Win10-style title bars (red close button), Aero Snap (drag to edges, Win+arrow keys) with **Snap Assist** (after Win+←/→ pick the window for the other half) and **quarter snapping** (Win+↑/↓ on a half, or drag into a corner while holding Win, Ctrl, Alt or Shift), Alt+Tab, Task View (Win+Tab), virtual desktops (Ctrl+Win+←/→) |
| **Desktop** | Picture or solid color background (fill/fit/stretch/tile/center), desktop icons (Recycle Bin, This PC, files), context menu, rename, copy/paste, drag and drop |
| **File Explorer** | Ribbon (File, Home, Share, View, Recycle Bin Tools), address bar with breadcrumb navigation, search, navigation pane, preview pane (Alt+P, pictures and text) and details pane (Alt+Shift+P), "Quick access", "This PC" with usage bars and network locations, "Map network drive" (`\\server\share`, SMB, SFTP, FTP, WebDAV through GVfs, asks for a password when needed), mount ISO/IMG disc images, burn disc images (Brasero/Xfburn), six views, properties (including permissions), create/extract ZIP files, Recycle Bin with restore |
| **Task Manager** | Ctrl+Shift+Esc: "Fewer details" and "More details", Processes (apps and background processes with CPU, memory and disk, heat-map colored), Performance (history graphs for CPU, memory, disks, network), Startup (enable/disable), Details (PID, status, user, command line), End task |
| **Tablet mode** | Quick action in the Action Center: Start fills the screen, apps open maximized, bigger taskbar buttons. **Touch keyboard** (Ctrl+Win+O or the taskbar button) with QWERTZ/QWERTY, Shift, Caps lock and a symbols view |
| **Game Bar** | Win+G: screenshot, screen recording (wf-recorder) with timer, volume and microphone, CPU and RAM. Game Mode starts games with Feral GameMode |
| **Settings** | 11 categories and 43 pages as in Windows 10: Display, Sound, Notifications, Power, Storage, Tablet mode, Multitasking, About, Bluetooth, Printers, Mouse, Typing, Network, Background, Colors (light/dark, choose an accent color yourself, pick it automatically from the background picture, or neutral "Dark", colors in Qt/Firefox/Flatpak apps), Lock screen, Themes (save and switch, mouse cursor), Fonts (preview, install by drag and drop), Start, Taskbar, Apps, Default apps, Startup, Account, Date & time, Region & language, Gaming (Game Bar, captures, Game Mode), Ease of Access (display, magnifier, high contrast with four contrast themes, Narrator with Orca, touch keyboard), Privacy (location, camera, microphone), Update |
| **Other apps** | Qt/KDE apps take the colors, accent and font through qt5ct (otherwise the GTK theme), Firefox and Thunderbird optionally get square tabs with an accent line and a red close button (userChrome.css), Flatpak apps optionally the Tenwin GTK theme |
| **Lock screen** | Win+L: clock and date in the bottom left, after a key press the profile picture and password field on a blurred background. Uses `ext-session-lock-v1`: even if the lock screen crashes, the session stays locked |
| **Sign-in screen** | Own LightDM greeter in the same style, with user list, session choice and power menu (optional) |
| **Other** | Win+X menu, Run dialog (Win+R), volume/brightness OSD, screenshots (Print, Win+Shift+S), welcome dialog to choose light or dark mode, German and English |

### Keyboard shortcuts

| Shortcut | Action |
|---|---|
| Win | Start menu |
| Win+E / Win+R / Win+I | File Explorer / Run / Settings |
| Win+A / Win+S | Action center / Search |
| Win+D / Win+M | Show desktop / minimize all |
| Win+L | Lock |
| Win+X | Win+X menu |
| Win+Tab / Alt+Tab | Task View / switch windows |
| Win+←/→/↑/↓ | Snap, maximize, restore/minimize |
| Ctrl+Win+←/→ | Switch virtual desktop |
| Win+1…0 | App at position 1…10 on the taskbar |
| Win+Space | Switch input language (with several layouts) |
| Ctrl+Shift+Esc | Task Manager |
| Win+G / Win+Alt+R / Win+Alt+Print | Game Bar / start or stop recording / screenshot to Captures |
| Win+Plus / Win+Minus / Win+Esc | Magnifier on or zoom in / zoom out / off |
| Ctrl+Win+Enter | Narrator on/off |
| Ctrl+Win+O | Touch keyboard |
| Print / Win+Shift+S | Screenshot / screen snip |
| Alt+F4 | Close window |

## Installation

Requirement: **Ubuntu 24.04 LTS** or newer (or a derivative such as Linux Mint 22, Pop!_OS 24.04, Zorin OS 18). Older releases don't ship a recent enough labwc.

```bash
git clone https://github.com/jessehaemmerle/desktop.git tenwin
```

```bash
cd tenwin && ./install.sh
```

The script installs the build dependencies, builds the `tenwin-desktop` and `tenwin-greeter` packages and installs them with `apt`, which pulls in all runtime dependencies. It also asks whether to set up the Win10-style sign-in screen. That switches the display manager from GDM to LightDM, which affects all users of the computer.

Options: `--with-greeter`, `--no-greeter`, `--yes`.

Then sign out and choose the **Tenwin** session on the sign-in screen. On first start, Tenwin asks whether you want light or dark mode.

### Building the packages only

```bash
make deb
```

The `.deb` files are written to the parent directory.

### Uninstalling

```bash
./uninstall.sh
```

The script restores a display manager that `install.sh` switched. With `--purge` it also deletes the current user's Tenwin settings.

## Trying it without installing

Inside a running desktop session (X11 or Wayland), Tenwin starts in a window:

```bash
sudo apt install labwc gir1.2-gtklayershell-0.1 python3-gi swayidle grim slurp wl-clipboard wlr-randr pulseaudio-utils build-essential libwayland-dev wayland-protocols libxkbcommon-dev libcairo2-dev libpango1.0-dev libgdk-pixbuf-2.0-dev libpam0g-dev gettext
```

```bash
tools/dev-session.sh
```

The test session uses its own settings file (`~/.config/tenwin-dev`) and its own D-Bus and doesn't touch the running desktop. In the test session, the lock screen needs the PAM file from `data/pam/tenwin-lock` in `/etc/pam.d/`.

## Structure

The architecture decisions are recorded (in German) in [docs/adr/0001-architektur.md](docs/adr/0001-architektur.md) and [docs/adr/0002-fensterverwaltung.md](docs/adr/0002-fensterverwaltung.md) (window actions through a virtual keyboard, because labwc 0.7 has no IPC).

```
bin/          Launch scripts (tenwin-session, tenwin-ctl, tenwin-shell, …)
helpers/      C programs: tenwin-lock (lock screen), tenwin-toplevel (window list),
              tenwin-vkbd (virtual keyboard for window actions and the touch keyboard)
src/tenwin/   Python package
  shell/      Taskbar, Start menu, search, action center, notifications, tray, Alt+Tab …
  desktop/    Background and desktop icons
  explorer/   File manager
  settings/   Settings app
  taskmgr/    Task Manager
  greeter/    LightDM sign-in screen
  services/   Audio, network, power, Bluetooth, display, session
data/         CSS, themes (GTK + labwc), icons, wallpapers, font, session, PAM, LightDM
po/           Translations (de)
tools/        Asset generators, headless tests, dev session
tests/        Unit tests (pytest)
debian/       Packaging
```

Settings are stored in `~/.config/tenwin/settings.json`. All Tenwin programs watch this file. The labwc configuration in `~/.config/tenwin/labwc/` is generated from it and reloaded on changes. GTK settings of the Tenwin session live in a separate dconf database, so a GNOME session on the same account stays unchanged.

## Development

```bash
make            # build C helpers and translations
make check      # unit tests
make smoke      # start a full session headless, screenshots in build/screenshots/
make pot        # update the translation template
```

The graphics (title bar buttons, icons, wallpapers, GTK themes) are generated by `tools/gen_assets.py` and `tools/gen_gtk_theme.py`.

## Known limitations

These come from labwc 0.7.1, which ships with Ubuntu 24.04:

- **No window previews** in Alt+Tab, Task View or when hovering over the taskbar. Large app icons and window titles are shown instead.
- **Virtual desktops** can only be switched with keyboard shortcuts, not from Task View. The taskbar shows the windows of all desktops.
- The **Win key on its own** is detected through a workaround (see the ADR). It was not verified in the test environment because there were no input devices.
- **Quarter snapping by dragging** needs Win, Ctrl, Alt or Shift held down; without a key labwc only snaps to halves.
- Tenwin can't see window geometry. If you drag a snapped window away by hand, Win+↑/↓ still assume the old state. Arranging windows also includes windows on other virtual desktops.
- With labwc 0.7 the **magnifier** shows an enlarged still picture that follows the mouse (Win+Plus refreshes it). With labwc 0.8 or newer Tenwin uses labwc's live magnifier.
- The **touch keyboard** doesn't open automatically for text fields (labwc 0.7 has no text-input protocol).
- **Camera** and **location** can only be blocked for apps that ask through xdg-desktop-portal (for example Flatpak apps). Linux has no per-app **microphone** permission; turning it off mutes the microphone.
- Qt 6 apps follow the theme only through the gtk3 platform theme, not through qt5ct.

## Legal

Tenwin is licensed under the **GPL-3.0** (see `LICENSE`). It is an independent project and not affiliated with Microsoft. "Windows" is a trademark of Microsoft Corporation. All graphics in this repository are original work. The bundled **Selawik** font is by Microsoft and licensed under the SIL Open Font License 1.1 (`data/fonts/OFL-Selawik.txt`). The protocol files `wlr-foreign-toplevel-management-unstable-v1.xml` (wlr-protocols) and `virtual-keyboard-unstable-v1.xml` (wlroots) are under MIT-style licenses.
