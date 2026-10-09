"""Benachrichtigungsdienst (org.freedesktop.Notifications) mit Facetten- und Fokus-Logik."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from gi.repository import Gio, GLib, GObject

from .. import __version__
from ..core.policy import URGENCY_CRITICAL, URGENCY_LOW, URGENCY_NORMAL, notification_route

BUS_NAME = "org.freedesktop.Notifications"
OBJECT_PATH = "/org/freedesktop/Notifications"
INTERFACE_XML = """
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="GetCapabilities"><arg type="as" direction="out"/></method>
    <method name="Notify">
      <arg type="s" direction="in"/><arg type="u" direction="in"/><arg type="s" direction="in"/>
      <arg type="s" direction="in"/><arg type="s" direction="in"/><arg type="as" direction="in"/>
      <arg type="a{sv}" direction="in"/><arg type="i" direction="in"/>
      <arg type="u" direction="out"/>
    </method>
    <method name="CloseNotification"><arg type="u" direction="in"/></method>
    <method name="GetServerInformation">
      <arg type="s" direction="out"/><arg type="s" direction="out"/>
      <arg type="s" direction="out"/><arg type="s" direction="out"/>
    </method>
    <signal name="NotificationClosed"><arg type="u"/><arg type="u"/></signal>
    <signal name="ActionInvoked"><arg type="u"/><arg type="s"/></signal>
  </interface>
</node>
"""

REASON_EXPIRED, REASON_DISMISSED, REASON_CLOSED = 1, 2, 3
MAX_HISTORY = 80


@dataclass
class Notification:
    id: int
    app_name: str
    summary: str
    body: str = ""
    icon: str = ""
    image: object = None  # GdkPixbuf aus image-data
    actions: list = field(default_factory=list)  # [(key, label)]
    urgency: int = URGENCY_NORMAL
    timeout: int = -1
    desktop_entry: str = ""
    transient: bool = False
    timestamp: float = field(default_factory=time.time)
    held: bool = False  # während Fokus/Stille zurückgehalten
    internal: bool = False
    callback: object = None  # für interne Aktionen


def _pixbuf_from_image_data(value):
    try:
        from gi.repository import GdkPixbuf

        width, height, rowstride, has_alpha, bits, _channels, data = value
        return GdkPixbuf.Pixbuf.new_from_bytes(
            GLib.Bytes.new(bytes(data)), GdkPixbuf.Colorspace.RGB, has_alpha, bits, width, height, rowstride
        )
    except Exception:
        return None


class NotificationStore(GObject.Object):
    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "popup": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "withdrawn": (GObject.SignalFlags.RUN_FIRST, None, (int,)),
    }

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.items: list[Notification] = []
        self._next_id = 1
        self._focus_started = 0.0
        self.digest: list[Notification] = []
        self._connection: Gio.DBusConnection | None = None
        self._node = Gio.DBusNodeInfo.new_for_xml(INTERFACE_XML)
        Gio.bus_own_name(
            Gio.BusType.SESSION,
            BUS_NAME,
            Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT | Gio.BusNameOwnerFlags.REPLACE,
            self._on_bus_acquired,
            None,
            lambda *_: print("prisma: Benachrichtigungsdienst belegt – ein anderer Daemon läuft bereits"),
        )

    # --------------------------------------------------------------- D-Bus
    def _on_bus_acquired(self, connection, _name) -> None:
        self._connection = connection
        connection.register_object(OBJECT_PATH, self._node.interfaces[0], self._on_method_call, None, None)

    def _on_method_call(self, _conn, _sender, _path, _iface, method, params, invocation) -> None:
        if method == "GetCapabilities":
            caps = ["body", "actions", "persistence", "icon-static"]
            invocation.return_value(GLib.Variant("(as)", (caps,)))
        elif method == "GetServerInformation":
            invocation.return_value(GLib.Variant("(ssss)", ("Prisma", "Prisma Desktop", __version__, "1.2")))
        elif method == "CloseNotification":
            (nid,) = params.unpack()
            self.close(nid, REASON_CLOSED)
            invocation.return_value(None)
        elif method == "Notify":
            app_name, replaces, icon, summary, body, actions, hints, timeout = params.unpack()
            nid = self._notify(app_name, replaces, icon, summary, body, actions, hints, timeout)
            invocation.return_value(GLib.Variant("(u)", (nid,)))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _emit_signal(self, name: str, variant: GLib.Variant) -> None:
        if self._connection is not None:
            try:
                self._connection.emit_signal(None, OBJECT_PATH, BUS_NAME, name, variant)
            except GLib.Error:
                pass

    # ---------------------------------------------------------- Annahme
    def _notify(self, app_name, replaces, icon, summary, body, actions, hints, timeout) -> int:
        urgency = hints.get("urgency", URGENCY_NORMAL)
        try:
            urgency = int(urgency)
        except (TypeError, ValueError):
            urgency = URGENCY_NORMAL
        image = None
        for key in ("image-data", "image_data", "icon_data"):
            if key in hints:
                image = _pixbuf_from_image_data(hints[key])
                break
        icon = icon or hints.get("image-path") or hints.get("image_path") or ""
        pairs = [(actions[i], actions[i + 1]) for i in range(0, len(actions) - 1, 2)]
        if replaces and any(n.id == replaces for n in self.items):
            nid = replaces
        else:
            nid = self._next_id
            self._next_id += 1
        note = Notification(
            id=nid,
            app_name=app_name or "Anwendung",
            summary=summary or "",
            body=body or "",
            icon=icon,
            image=image,
            actions=pairs,
            urgency=max(URGENCY_LOW, min(URGENCY_CRITICAL, urgency)),
            timeout=timeout,
            desktop_entry=str(hints.get("desktop-entry", "")),
            transient=bool(hints.get("transient", False)),
        )
        self._deliver(note, replace=bool(replaces))
        return nid

    def _deliver(self, note: Notification, replace: bool = False) -> None:
        route = notification_route(
            note.urgency,
            note.app_name,
            self.hub.facet.get("notifications", "all"),
            self.hub.in_focus,
            self.hub.dnd,
            self.hub.config["focus"].get("allow_apps", []),
        )
        note.held = route == "quiet"
        existing = next((i for i, n in enumerate(self.items) if n.id == note.id), None)
        if existing is not None:
            self.items[existing] = note
        else:
            self.items.insert(0, note)
            del self.items[MAX_HISTORY:]
        if note.held and self.hub.in_focus and not note.internal:
            self.digest = [n for n in self.digest if n.id != note.id] + [note]
        if not note.held:
            self.emit("popup", note)
        self.emit("changed")

    def post_internal(self, summary: str, body: str, icon: str, urgency: int = URGENCY_NORMAL,
                      actions: list | None = None, callback=None) -> int:
        note = Notification(
            id=self._next_id, app_name="Prisma", summary=summary, body=body, icon=icon,
            urgency=urgency, internal=True, actions=actions or [], callback=callback,
        )
        self._next_id += 1
        # Interne Meldungen umgehen Facettenregeln, respektieren aber „Nicht stören“.
        self.items.insert(0, note)
        del self.items[MAX_HISTORY:]
        if not self.hub.dnd or urgency >= URGENCY_CRITICAL:
            self.emit("popup", note)
        self.emit("changed")
        return note.id

    # ---------------------------------------------------------- Fokus-Rückblick
    def begin_focus(self) -> None:
        self._focus_started = time.time()
        self.digest = []

    def end_focus(self, completed: bool) -> None:
        held = len(self.digest)
        if completed:
            minutes = self.hub.config["focus"]["break_minutes"]
            body = f"{held} Benachrichtigung{'en' if held != 1 else ''} während der Session gesammelt. " if held else "Keine Unterbrechungen – stark! "
            body += f"Gönn dir {minutes} Minuten Pause."
            self.post_internal("Fokus-Session geschafft 🎉", body, "emblem-ok-symbolic", URGENCY_CRITICAL,
                               actions=[("show", "Rückblick ansehen")],
                               callback=lambda _key: self.hub.app.activate_action("daypanel", None))
        elif held:
            self.post_internal("Fokus beendet", f"{held} gesammelte Benachrichtigungen warten im Tagesüberblick.",
                               "preferences-system-notifications-symbolic")

    # ---------------------------------------------------------- Aktionen
    def get(self, nid: int) -> Notification | None:
        return next((n for n in self.items if n.id == nid), None)

    def invoke(self, nid: int, key: str) -> None:
        note = self.get(nid)
        if note is None:
            return
        if note.internal:
            if callable(note.callback):
                note.callback(key)
        else:
            self._emit_signal("ActionInvoked", GLib.Variant("(us)", (nid, key)))
            if key == "default" and note.desktop_entry:
                app = self.hub.apps.get(note.desktop_entry)
                # Fenster der App nach vorne holen
                if app is not None:
                    windows = [w for w in self.hub.windows.all() if getattr(w.extra.get("app"), "id", None) == app.id]
                    if windows:
                        self.hub.windows.activate(windows[0])
        self.close(nid, REASON_DISMISSED)

    def close(self, nid: int, reason: int = REASON_DISMISSED) -> None:
        before = len(self.items)
        self.items = [n for n in self.items if n.id != nid]
        self.digest = [n for n in self.digest if n.id != nid]
        if len(self.items) != before:
            self._emit_signal("NotificationClosed", GLib.Variant("(uu)", (nid, reason)))
            self.emit("withdrawn", nid)
            self.emit("changed")

    def expire_popup(self, note: Notification) -> None:
        """Popup ist abgelaufen – flüchtige Meldungen verschwinden ganz, andere bleiben im Zentrum."""
        if note.transient:
            self.close(note.id, REASON_EXPIRED)

    def clear(self) -> None:
        for note in list(self.items):
            self.close(note.id, REASON_DISMISSED)
        self.digest = []
        self.emit("changed")

    @property
    def count(self) -> int:
        return len(self.items)
