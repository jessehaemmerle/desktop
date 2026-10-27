"""Categories and pages of the Settings app (shared with the shell's search)."""

from tenwin.i18n import _

# (id, title, subtitle, icon)
CATEGORIES = [
    ("system", "System", "Display, sound, notifications, power", "tenwin-system"),
    ("devices", "Devices", "Bluetooth, printers, mouse", "tenwin-devices"),
    ("network", "Network & Internet", "Wi-Fi, airplane mode, VPN", "tenwin-globe"),
    ("personalization", "Personalization", "Background, lock screen, colors", "tenwin-personalization"),
    ("apps", "Apps", "Uninstall, defaults, optional features", "tenwin-apps"),
    ("accounts", "Accounts", "Your accounts, sign-in options", "tenwin-accounts"),
    ("time", "Time & Language", "Date, region, keyboard", "tenwin-time-language"),
    ("ease", "Ease of Access", "Text size, cursor, animations", "tenwin-ease"),
    ("update", "Update & Security", "Software updates, backup", "tenwin-update"),
]

# (id, category, title, icon, extra search keywords)
PAGES = [
    ("display", "system", "Display", "tenwin-display", "resolution scale screen monitor brightness night light"),
    ("sound", "system", "Sound", "tenwin-sound", "volume speaker microphone audio output input"),
    ("notifications", "system", "Notifications & actions", "tenwin-notifications", "quick actions focus assist"),
    ("power", "system", "Power & sleep", "tenwin-power-plug", "sleep lock screen timeout battery"),
    ("storage", "system", "Storage", "tenwin-storage", "disk space drive"),
    ("about", "system", "About", "tenwin-info", "pc name device specifications version"),
    ("bluetooth", "devices", "Bluetooth & other devices", "tenwin-bluetooth", "pair devices"),
    ("printers", "devices", "Printers & scanners", "tenwin-printer", "printer scanner"),
    ("mouse", "devices", "Mouse & touchpad", "tenwin-mouse", "pointer speed scroll tap touchpad"),
    ("typing", "devices", "Keyboard", "tenwin-keyboard", "repeat delay typing keyboard"),
    ("network-status", "network", "Status", "tenwin-globe", "network connection internet"),
    ("wifi", "network", "Wi-Fi", "tenwin-wifi-3", "wireless wlan"),
    ("airplane", "network", "Airplane mode", "tenwin-airplane", "flight mode"),
    ("vpn", "network", "VPN", "tenwin-shield", "vpn proxy"),
    ("background", "personalization", "Background", "tenwin-image", "wallpaper picture desktop"),
    ("colors", "personalization", "Colors", "tenwin-palette", "dark mode light mode accent color transparency theme"),
    ("lockscreen", "personalization", "Lock screen", "tenwin-lock", "lock screen picture"),
    ("start", "personalization", "Start", "tenwin-tiles", "start menu tiles folders"),
    ("taskbar", "personalization", "Taskbar", "tenwin-taskbar", "taskbar search box small buttons position"),
    ("apps-features", "apps", "Apps & features", "tenwin-apps", "uninstall programs"),
    ("default-apps", "apps", "Default apps", "tenwin-default-apps", "browser email music video photo"),
    ("startup", "apps", "Startup", "tenwin-autostart", "autostart startup apps"),
    ("your-info", "accounts", "Your info", "tenwin-user", "account picture name"),
    ("sign-in", "accounts", "Sign-in options", "tenwin-lock", "password"),
    ("datetime", "time", "Date & time", "tenwin-calendar", "clock time zone 24 hour"),
    ("region", "time", "Region & language", "tenwin-globe", "language region keyboard layout"),
    ("ease-display", "ease", "Display", "tenwin-ease", "text size bigger animations transparency cursor"),
    ("windows-update", "update", "Software update", "tenwin-update", "update upgrade packages"),
    ("desktop-icons", "personalization", "Desktop icons", "tenwin-desktop", "this pc recycle bin desktop icons"),
]


def category_title(cat_id):
    for cid, title, _sub, _icon in CATEGORIES:
        if cid == cat_id:
            return _(title)
    return cat_id


def pages_for(cat_id):
    return [p for p in PAGES if p[1] == cat_id]


def search(query, limit=8):
    """Settings pages matching ``query``: list of (page_id, title, category title, icon)."""
    q = query.casefold().strip()
    if not q:
        return []
    results = []
    for page_id, cat, title, icon, keywords in PAGES:
        local = _(title)
        hay = " ".join([local, title, _(keywords), keywords, category_title(cat)]).casefold()
        if q in local.casefold():
            score = 0 if local.casefold().startswith(q) else 1
        elif all(word in hay for word in q.split()):
            score = 2
        else:
            continue
        results.append((score, page_id, local, category_title(cat), icon))
    results.sort()
    return [r[1:] for r in results[:limit]]
