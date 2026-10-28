"""org.freedesktop.Notifications server and Windows 10 style toasts."""

import html
import logging
import re
import time

from gi.repository import GdkPixbuf, Gio, GLib, GObject, Gtk, Pango

from tenwin.config import get_settings
from tenwin.gtkutil import add_class, flat_button, icon_image
from tenwin.i18n import _
from tenwin.shell.layer import Edge, Layer, LayerWindow, taskbar_edge

log = logging.getLogger(__name__)

IFACE_XML = """
<node>
  <interface name="org.freedesktop.Notifications">
    <method name="GetCapabilities"><arg type="as" direction="out"/></method>
    <method name="Notify">
      <arg type="s" name="app_name" direction="in"/>
      <arg type="u" name="replaces_id" direction="in"/>
      <arg type="s" name="app_icon" direction="in"/>
      <arg type="s" name="summary" direction="in"/>
      <arg type="s" name="body" direction="in"/>
      <arg type="as" name="actions" direction="in"/>
      <arg type="a{sv}" name="hints" direction="in"/>
      <arg type="i" name="expire_timeout" direction="in"/>
      <arg type="u" name="id" direction="out"/>
    </method>
    <method name="CloseNotification"><arg type="u" name="id" direction="in"/></method>
    <method name="GetServerInformation">
      <arg type="s" name="name" direction="out"/>
      <arg type="s" name="vendor" direction="out"/>
      <arg type="s" name="version" direction="out"/>
      <arg type="s" name="spec_version" direction="out"/>
    </method>
    <signal name="NotificationClosed"><arg type="u" name="id"/><arg type="u" name="reason"/></signal>
    <signal name="ActionInvoked"><arg type="u" name="id"/><arg type="s" name="action_key"/></signal>
  </interface>
</node>
"""

REASON_EXPIRED, REASON_DISMISSED, REASON_CLOSED = 1, 2, 3
TOAST_SECONDS = 6
MAX_TOASTS = 3

_ALLOWED_TAGS = re.compile(r"</?(b|i|u)>", re.I)


def sanitize_markup(text):
    """Keep <b>, <i>, <u>; escape everything else (spec 'body-markup')."""
    parts = []
    pos = 0
    for match in _ALLOWED_TAGS.finditer(text or ""):
        parts.append(html.escape(html.unescape(text[pos:match.start()]), quote=False))
        parts.append(match.group(0).lower())
        pos = match.end()
    parts.append(html.escape(html.unescape((text or "")[pos:]), quote=False))
    markup = "".join(parts)
    try:
        Pango.parse_markup(markup, -1, "\0")
        return markup
    except GLib.Error:
        return GLib.markup_escape_text(re.sub(r"<[^>]*>", "", text or ""))


class Notification:
    def __init__(self, nid, app_name, app_icon, summary, body, actions, hints, timeout):
        self.id = nid
        self.app_name = app_name or _("Notification")
        self.app_icon = app_icon
        self.summary = summary
        self.body = body
        self.actions = list(zip(actions[0::2], actions[1::2]))
        self.hints = hints
        self.timeout = timeout
        self.time = time.time()
        self.urgency = int(hints.get("urgency", 1)) if isinstance(hints.get("urgency"), (int, float)) else 1
        self.transient = bool(hints.get("transient", False))
        self.resident = bool(hints.get("resident", False))
        self.desktop_entry = hints.get("desktop-entry") or ""

    def icon(self):
        """Gio.Icon/str/pixbuf for the notification image."""
        data = self.hints.get("image-data") or self.hints.get("image_data") or self.hints.get("icon_data")
        if data:
            try:
                width, height, rowstride, alpha, bits, _channels, pixels = data
                pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(pixels)),
                                                         GdkPixbuf.Colorspace.RGB, alpha, bits,
                                                         width, height, rowstride)
                return pixbuf
            except (TypeError, ValueError, GLib.Error):
                pass
        path = self.hints.get("image-path") or self.hints.get("image_path")
        if isinstance(path, str) and path:
            return path[7:] if path.startswith("file://") else path
        if self.app_icon:
            return self.app_icon[7:] if self.app_icon.startswith("file://") else self.app_icon
        if self.desktop_entry:
            info = Gio.DesktopAppInfo.new(self.desktop_entry + ".desktop")
            if info is not None:
                return info.get_icon()
        return "dialog-information"


def notification_image(icon, size):
    if isinstance(icon, GdkPixbuf.Pixbuf):
        scaled = icon.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
        return Gtk.Image.new_from_pixbuf(scaled)
    return icon_image(icon, size)


class NotificationServer(GObject.Object):
    __gsignals__ = {
        "added": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "removed": (GObject.SignalFlags.RUN_FIRST, None, (object,)),
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.next_id = 1
        self.history = []        # notifications shown in the Info-Center
        self.toasts = {}         # id -> Toast
        self.connection = None
        node = Gio.DBusNodeInfo.new_for_xml(IFACE_XML)
        self.iface = node.interfaces[0]
        Gio.bus_own_name(Gio.BusType.SESSION, "org.freedesktop.Notifications",
                         Gio.BusNameOwnerFlags.REPLACE | Gio.BusNameOwnerFlags.ALLOW_REPLACEMENT,
                         self._on_bus, None, self._on_lost)

    def _on_bus(self, connection, _name):
        self.connection = connection
        connection.register_object("/org/freedesktop/Notifications", self.iface, self._on_call, None, None)

    def _on_lost(self, _connection, name):
        log.warning("could not own %s (another notification daemon is running?)", name)

    def _on_call(self, _conn, _sender, _path, _iface, method, params, invocation):
        if method == "GetCapabilities":
            invocation.return_value(GLib.Variant("(as)", (["actions", "body", "body-markup", "icon-static",
                                                            "persistence"],)))
        elif method == "GetServerInformation":
            from tenwin import __version__
            invocation.return_value(GLib.Variant("(ssss)", ("Tenwin", "Tenwin", __version__, "1.2")))
        elif method == "CloseNotification":
            nid = params.unpack()[0]
            self.close(nid, REASON_CLOSED)
            invocation.return_value(None)
        elif method == "Notify":
            args = params.unpack()
            nid = self.notify(*args)
            invocation.return_value(GLib.Variant("(u)", (nid,)))
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    # -- API ----------------------------------------------------------------

    def notify(self, app_name, replaces_id, app_icon, summary, body, actions, hints, timeout):
        if replaces_id and (replaces_id in self.toasts or any(n.id == replaces_id for n in self.history)):
            nid = replaces_id
            self._drop(nid)
        else:
            nid = self.next_id
            self.next_id += 1
        note = Notification(nid, app_name, app_icon, summary, body, actions, hints, timeout)
        settings = get_settings()
        if not note.transient:
            self.history.insert(0, note)
            self.emit("added", note)
            self.emit("changed")
        quiet = settings["notifications.focus_assist"] and note.urgency < 2
        if settings["notifications.enabled"] and not quiet and not self.shell.action_center.is_open():
            self._show_toast(note)
        return nid

    def _show_toast(self, note):
        while len(self.toasts) >= MAX_TOASTS:
            oldest = min(self.toasts.values(), key=lambda t: t.note.time)
            oldest.dismiss(expired=True)
        toast = Toast(self, note)
        self.toasts[note.id] = toast
        self._layout_toasts()
        toast.show_all()

    def _layout_toasts(self):
        offset = 12
        for toast in sorted(self.toasts.values(), key=lambda t: -t.note.time):
            toast.set_offset(offset)
            offset += toast.get_preferred_height()[1] + 8

    def toast_finished(self, toast, reason):
        if self.toasts.get(toast.note.id) is not toast:
            return  # already replaced or removed
        self.toasts.pop(toast.note.id, None)
        self._layout_toasts()
        if reason != REASON_EXPIRED or toast.note.transient:
            if reason == REASON_DISMISSED:
                self.remove(toast.note.id, REASON_DISMISSED)
            elif toast.note.transient:
                self._signal_closed(toast.note.id, reason)

    def invoke(self, note, action_key):
        if self.connection is not None:
            self.connection.emit_signal(None, "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                                        "ActionInvoked", GLib.Variant("(us)", (note.id, action_key)))
        if not note.resident:
            self.remove(note.id, REASON_DISMISSED)

    def _drop(self, nid):
        toast = self.toasts.pop(nid, None)
        if toast is not None:
            toast.destroy()
        self.history = [n for n in self.history if n.id != nid]

    def close(self, nid, reason=REASON_CLOSED):
        self.remove(nid, reason)

    def remove(self, nid, reason=REASON_DISMISSED):
        toast = self.toasts.pop(nid, None)
        if toast is not None:
            toast.destroy()
            self._layout_toasts()
        before = len(self.history)
        removed = [n for n in self.history if n.id == nid]
        self.history = [n for n in self.history if n.id != nid]
        if removed or toast is not None:
            self._signal_closed(nid, reason)
        if len(self.history) != before:
            for note in removed:
                self.emit("removed", note)
            self.emit("changed")

    def clear(self, app_name=None):
        for note in list(self.history):
            if app_name is None or note.app_name == app_name:
                self.remove(note.id, REASON_DISMISSED)

    def _signal_closed(self, nid, reason):
        if self.connection is not None:
            self.connection.emit_signal(None, "/org/freedesktop/Notifications", "org.freedesktop.Notifications",
                                        "NotificationClosed", GLib.Variant("(uu)", (nid, reason)))

    def hide_toasts(self):
        for toast in list(self.toasts.values()):
            toast.dismiss(expired=True)


class Toast(LayerWindow):
    WIDTH = 364

    def __init__(self, server, note):
        edge = taskbar_edge()
        super().__init__("tenwin-toast", layer=Layer.OVERLAY, anchors=(edge, Edge.RIGHT),
                         css="tw-surface tw-popup")
        self.server = server
        self.note = note
        self.edge = edge
        self.set_margins(right=12)
        frame = add_class(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6), "tw-toast")
        frame.set_size_request(self.WIDTH, -1)
        header = Gtk.Box(spacing=8)
        header.pack_start(notification_image(note.icon(), 16), False, False, 0)
        header.pack_start(add_class(Gtk.Label(label=note.app_name, xalign=0), "tw-toast-app"), True, True, 0)
        close = flat_button(icon_image("tenwin-close", 12, symbolic=True), "tw-notif-close")
        close.connect("clicked", lambda *_: self.dismiss())
        header.pack_end(close, False, False, 0)
        frame.pack_start(header, False, False, 0)

        content = Gtk.Box(spacing=12)
        image = note.icon()
        if image is not None and (isinstance(image, GdkPixbuf.Pixbuf) or note.hints.get("image-path")):
            content.pack_start(notification_image(image, 48), False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        summary = add_class(Gtk.Label(label=note.summary, xalign=0), "tw-notif-summary")
        summary.set_line_wrap(True)
        summary.set_max_width_chars(36)
        texts.pack_start(summary, False, False, 0)
        if note.body:
            body = add_class(Gtk.Label(xalign=0), "tw-notif-body")
            body.set_markup(sanitize_markup(note.body))
            body.set_line_wrap(True)
            body.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
            body.set_max_width_chars(40)
            body.set_lines(4)
            body.set_ellipsize(Pango.EllipsizeMode.END)
            texts.pack_start(body, False, False, 0)
        content.pack_start(texts, True, True, 0)
        frame.pack_start(content, False, False, 0)

        actions = [(k, label) for k, label in note.actions if k != "default"]
        if actions:
            row = Gtk.Box(spacing=4, homogeneous=True)
            for key, label in actions[:3]:
                button = flat_button(Gtk.Label(label=label), "tw-toast-action")
                button.connect("clicked", lambda _b, k=key: self._invoke(k))
                row.pack_start(button, True, True, 0)
            frame.pack_start(row, False, False, 0)

        events = Gtk.EventBox()
        events.add(frame)
        events.connect("button-release-event", self._on_click)
        events.connect("enter-notify-event", lambda *_: self._pause(True))
        events.connect("leave-notify-event", lambda *_: self._pause(False))
        self.add(events)
        self._timer = 0
        self._paused = False
        self._finished = False
        self.connect("destroy", lambda *_: self._stop_timer())
        self._start_timer()

    def _stop_timer(self):
        if self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0

    def set_offset(self, offset):
        if self.edge == Edge.TOP:
            self.set_margins(top=offset, right=12)
        else:
            self.set_margins(bottom=offset, right=12)

    def _start_timer(self):
        if self.note.urgency >= 2 and self.note.timeout <= 0:
            return  # critical notifications stay until dismissed
        seconds = TOAST_SECONDS
        if self.note.timeout > 0:
            seconds = max(2, min(30, self.note.timeout / 1000))
        self._timer = GLib.timeout_add(int(seconds * 1000), self._expire)

    def _pause(self, paused):
        if paused and self._timer:
            GLib.source_remove(self._timer)
            self._timer = 0
        elif not paused and not self._timer:
            self._start_timer()

    def _expire(self):
        self._timer = 0
        self.dismiss(expired=True)
        return GLib.SOURCE_REMOVE

    def _on_click(self, _widget, event):
        if event.button == 1:
            if any(k == "default" for k, _l in self.note.actions):
                self._invoke("default")
            else:
                self.dismiss(expired=True)
        return True

    def _invoke(self, key):
        self.dismiss(expired=True)
        self.server.invoke(self.note, key)

    def dismiss(self, expired=False):
        if self._finished:
            return
        self._finished = True
        self._stop_timer()
        self.server.toast_finished(self, REASON_EXPIRED if expired else REASON_DISMISSED)
        self.destroy()
