"""Categories and pages of the Settings app (shared with the shell's search)."""

from tenwin.i18n import N_, _

# (id, title, subtitle, icon)
CATEGORIES = [
    ("system", N_("System"), N_("Display, sound, notifications, power"), "tenwin-system"),
    ("devices", N_("Devices"), N_("Bluetooth, printers, mouse"), "tenwin-devices"),
    ("network", N_("Network & Internet"), N_("Wi-Fi, airplane mode, VPN"), "tenwin-globe"),
    ("personalization", N_("Personalization"), N_("Background, lock screen, colors"), "tenwin-personalization"),
    ("apps", N_("Apps"), N_("Uninstall, defaults, optional features"), "tenwin-apps"),
    ("accounts", N_("Accounts"), N_("Your accounts, sign-in options"), "tenwin-accounts"),
    ("time", N_("Time & Language"), N_("Date, region, keyboard"), "tenwin-time-language"),
    ("ease", N_("Ease of Access"), N_("Text size, cursor, animations"), "tenwin-ease"),
    ("update", N_("Update & Security"), N_("Software updates, backup"), "tenwin-update"),
]

# (id, category, title, icon, extra search keywords)
PAGES = [
    ("display", "system", N_("Display"), "tenwin-display", N_("resolution scale screen monitor brightness night light")),
    ("sound", "system", N_("Sound"), "tenwin-sound", N_("volume speaker microphone audio output input")),
    ("notifications", "system", N_("Notifications & actions"), "tenwin-notifications", N_("quick actions focus assist")),
    ("power", "system", N_("Power & sleep"), "tenwin-power-plug", N_("sleep lock screen timeout battery")),
    ("storage", "system", N_("Storage"), "tenwin-storage", N_("disk space drive")),
    ("about", "system", N_("About"), "tenwin-info", N_("pc name device specifications version")),
    ("bluetooth", "devices", N_("Bluetooth & other devices"), "tenwin-bluetooth", N_("pair devices")),
    ("printers", "devices", N_("Printers & scanners"), "tenwin-printer", N_("printer scanner")),
    ("mouse", "devices", N_("Mouse & touchpad"), "tenwin-mouse", N_("pointer speed scroll tap touchpad")),
    ("typing", "devices", N_("Keyboard"), "tenwin-keyboard", N_("repeat delay typing keyboard")),
    ("network-status", "network", N_("Status"), "tenwin-globe", N_("network connection internet")),
    ("wifi", "network", N_("Wi-Fi"), "tenwin-wifi-3", N_("wireless wlan")),
    ("airplane", "network", N_("Airplane mode"), "tenwin-airplane", N_("flight mode")),
    ("vpn", "network", N_("VPN"), "tenwin-shield", N_("vpn proxy")),
    ("background", "personalization", N_("Background"), "tenwin-image", N_("wallpaper picture desktop")),
    ("colors", "personalization", N_("Colors"), "tenwin-palette", N_("dark mode light mode accent color transparency theme")),
    ("lockscreen", "personalization", N_("Lock screen"), "tenwin-lock", N_("lock screen picture")),
    ("start", "personalization", N_("Start"), "tenwin-tiles", N_("start menu tiles folders")),
    ("taskbar", "personalization", N_("Taskbar"), "tenwin-taskbar", N_("taskbar search box small buttons position")),
    ("apps-features", "apps", N_("Apps & features"), "tenwin-apps", N_("uninstall programs")),
    ("default-apps", "apps", N_("Default apps"), "tenwin-default-apps", N_("browser email music video photo")),
    ("startup", "apps", N_("Startup"), "tenwin-autostart", N_("autostart startup apps")),
    ("your-info", "accounts", N_("Your info"), "tenwin-user", N_("account picture name")),
    ("sign-in", "accounts", N_("Sign-in options"), "tenwin-lock", N_("password")),
    ("datetime", "time", N_("Date & time"), "tenwin-calendar", N_("clock time zone 24 hour")),
    ("region", "time", N_("Region & language"), "tenwin-globe", N_("language region keyboard layout")),
    ("ease-display", "ease", N_("Display"), "tenwin-ease", N_("text size bigger animations transparency cursor")),
    ("windows-update", "update", N_("Software update"), "tenwin-update", N_("update upgrade packages")),
    ("desktop-icons", "personalization", N_("Desktop icons"), "tenwin-desktop", N_("this pc recycle bin desktop icons")),
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
