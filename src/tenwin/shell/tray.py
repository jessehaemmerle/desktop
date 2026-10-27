"""Notification area: StatusNotifierWatcher + host (SNI tray icons)."""

import logging

from gi.repository import GdkPixbuf, Gio, GLib, GObject, Gtk

from tenwin.config import get_settings
from tenwin.gtkutil import add_class, clear_children, flat_button, icon_image, set_icon
from tenwin.i18n import _
from tenwin.shell.layer import Edge, Popup, taskbar_edge

log = logging.getLogger(__name__)

try:
    import gi
    gi.require_version("DbusmenuGtk3", "0.4")
    from gi.repository import DbusmenuGtk3
except (ImportError, ValueError):
    DbusmenuGtk3 = None

WATCHER_XML = """
<node>
  <interface name="org.kde.StatusNotifierWatcher">
    <method name="RegisterStatusNotifierItem"><arg type="s" direction="in"/></method>
    <method name="RegisterStatusNotifierHost"><arg type="s" direction="in"/></method>
    <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
    <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
    <property name="ProtocolVersion" type="i" access="read"/>
    <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
    <signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
    <signal name="StatusNotifierHostRegistered"/>
    <signal name="StatusNotifierHostUnregistered"/>
  </interface>
</node>
"""

ITEM_IFACE = "org.kde.StatusNotifierItem"


def pixmap_to_pixbuf(pixmaps, size):
    """Pick the best ARGB32 (network byte order) pixmap and convert it."""
    best = None
    for width, height, data in pixmaps or []:
        if width <= 0 or height <= 0 or len(data) < width * height * 4:
            continue
        if best is None or abs(width - size) < abs(best[0] - size):
            best = (width, height, data)
    if best is None:
        return None
    width, height, data = best
    raw = bytes(data)
    rgba = bytearray(len(raw))
    rgba[0::4] = raw[1::4]
    rgba[1::4] = raw[2::4]
    rgba[2::4] = raw[3::4]
    rgba[3::4] = raw[0::4]
    pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(rgba)), GdkPixbuf.Colorspace.RGB, True, 8,
                                             width, height, width * 4)
    if width != size:
        pixbuf = pixbuf.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
    return pixbuf


class TrayItem(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, key, bus_name, path):
        super().__init__()
        self.key = key
        self.bus_name = bus_name
        self.path = path
        self.props = {}
        self.proxy = None
        Gio.DBusProxy.new_for_bus(Gio.BusType.SESSION, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES, None,
                                  bus_name, path, ITEM_IFACE, None, self._on_proxy)

    def _on_proxy(self, _src, result):
        try:
            self.proxy = Gio.DBusProxy.new_for_bus_finish(result)
        except GLib.Error as exc:
            log.info("tray item %s: %s", self.key, exc)
            return
        self.proxy.connect("g-signal", lambda *_: self.reload())
        self.reload()

    def reload(self):
        if self.proxy is None:
            return
        self.proxy.call("org.freedesktop.DBus.Properties.GetAll", GLib.Variant("(s)", (ITEM_IFACE,)),
                        Gio.DBusCallFlags.NONE, 2000, None, self._on_props)

    def _on_props(self, proxy, result):
        try:
            self.props = proxy.call_finish(result).unpack()[0]
        except GLib.Error:
            return
        self.emit("changed")

    @property
    def status(self):
        return self.props.get("Status", "Active")

    @property
    def title(self):
        tooltip = self.props.get("ToolTip")
        if tooltip and len(tooltip) >= 4 and (tooltip[2] or tooltip[3]):
            return tooltip[2] or tooltip[3]
        return self.props.get("Title") or self.props.get("Id") or ""

    def set_image(self, image, size=16):
        attention = self.status == "NeedsAttention"
        name = self.props.get("AttentionIconName" if attention else "IconName") or self.props.get("IconName")
        theme_path = self.props.get("IconThemePath")
        if theme_path:
            Gtk.IconTheme.get_default().append_search_path(theme_path)
        if name:
            if name.startswith("/"):
                try:
                    image.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_size(name, size, size))
                    return
                except GLib.Error:
                    pass
            elif Gtk.IconTheme.get_default().has_icon(name):
                set_icon(image, name, size)
                return
        pixbuf = pixmap_to_pixbuf(self.props.get("AttentionIconPixmap" if attention else "IconPixmap")
                                  or self.props.get("IconPixmap"), size)
        if pixbuf is not None:
            image.set_from_pixbuf(pixbuf)
        else:
            set_icon(image, "application-x-executable", size)

    def activate(self, x, y):
        if self.props.get("ItemIsMenu") and self.props.get("Menu"):
            return False
        self._call("Activate", x, y)
        return True

    def secondary_activate(self, x, y):
        self._call("SecondaryActivate", x, y)

    def context_menu(self, widget, event):
        menu_path = self.props.get("Menu")
        if menu_path and DbusmenuGtk3 is not None:
            menu = DbusmenuGtk3.Menu.new(self.bus_name, menu_path)
            add_class(menu, "tw-menu")
            menu.attach_to_widget(widget, None)

            def show():
                menu.show_all()
                menu.popup_at_pointer(event)
                return False
            # dbusmenu fills the menu asynchronously.
            GLib.timeout_add(120, show)
            return
        self._call("ContextMenu", int(event.x_root), int(event.y_root))

    def scroll(self, delta, orientation):
        self._call_raw("Scroll", GLib.Variant("(is)", (delta, orientation)))

    def _call(self, method, x, y):
        self._call_raw(method, GLib.Variant("(ii)", (int(x), int(y))))

    def _call_raw(self, method, params):
        if self.proxy is not None:
            self.proxy.call(method, params, Gio.DBusCallFlags.NONE, -1, None, None)


class TrayHost(GObject.Object):
    __gsignals__ = {"changed": (GObject.SignalFlags.RUN_FIRST, None, ())}

    def __init__(self, shell):
        super().__init__()
        self.shell = shell
        self.items = {}
        self.watches = {}
        self.connection = None
        self.overflow = TrayOverflow(shell, self)
        node = Gio.DBusNodeInfo.new_for_xml(WATCHER_XML)
        self.iface = node.interfaces[0]
        Gio.bus_own_name(Gio.BusType.SESSION, "org.kde.StatusNotifierWatcher", Gio.BusNameOwnerFlags.NONE,
                         self._on_bus, None, lambda *_: log.warning("another tray watcher is running"))

    def _on_bus(self, connection, _name):
        self.connection = connection
        connection.register_object("/StatusNotifierWatcher", self.iface, self._on_call, self._on_get, None)
        connection.emit_signal(None, "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
                               "StatusNotifierHostRegistered", None)

    def _on_get(self, _conn, _sender, _path, _iface, prop):
        if prop == "RegisteredStatusNotifierItems":
            return GLib.Variant("as", list(self.items))
        if prop == "IsStatusNotifierHostRegistered":
            return GLib.Variant("b", True)
        if prop == "ProtocolVersion":
            return GLib.Variant("i", 0)
        return None

    def _on_call(self, conn, sender, _path, _iface, method, params, invocation):
        if method == "RegisterStatusNotifierItem":
            service = params.unpack()[0]
            if service.startswith("/"):
                bus_name, path = sender, service
            else:
                bus_name, path = service, "/StatusNotifierItem"
            key = bus_name + path
            if key not in self.items:
                item = TrayItem(key, bus_name, path)
                item.connect("changed", lambda *_: self.emit("changed"))
                self.items[key] = item
                watch = Gio.bus_watch_name_on_connection(conn, bus_name, Gio.BusNameWatcherFlags.NONE,
                                                         None, lambda *_a, k=key: self._unregister(k))
                self.watches[key] = watch
                conn.emit_signal(None, "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
                                 "StatusNotifierItemRegistered", GLib.Variant("(s)", (key,)))
                self.emit("changed")
            invocation.return_value(None)
        elif method == "RegisterStatusNotifierHost":
            invocation.return_value(None)
        else:
            invocation.return_dbus_error("org.freedesktop.DBus.Error.UnknownMethod", method)

    def _unregister(self, key):
        item = self.items.pop(key, None)
        watch = self.watches.pop(key, None)
        if watch:
            Gio.bus_unwatch_name(watch)
        if item is not None and self.connection is not None:
            self.connection.emit_signal(None, "/StatusNotifierWatcher", "org.kde.StatusNotifierWatcher",
                                        "StatusNotifierItemUnregistered", GLib.Variant("(s)", (key,)))
            self.emit("changed")

    def visible_items(self):
        return [i for i in self.items.values() if i.status != "Passive" and i.proxy is not None]

    def create_widget(self, taskbar):
        return TrayArea(self, taskbar)

    def item_button(self, item, size=16):
        button = flat_button(css="tw-tray-item")
        image = Gtk.Image()
        item.set_image(image, size)
        button.add(image)
        button.set_tooltip_text(item.title)

        def on_release(_w, event):
            if event.button == 1:
                if not item.activate(event.x_root, event.y_root):
                    item.context_menu(button, event)
                self.overflow.close_popup()
            elif event.button == 2:
                item.secondary_activate(event.x_root, event.y_root)
            elif event.button == 3:
                item.context_menu(button, event)
            return True

        button.connect("button-release-event", on_release)
        return button


class TrayArea(Gtk.Box):
    def __init__(self, host, taskbar):
        super().__init__()
        self.host = host
        self.taskbar = taskbar
        self.chevron = flat_button(icon_image("tenwin-chevron-up", 12, symbolic=True), "tw-tray-item",
                                   _("Show hidden icons"))
        self.chevron.connect("clicked", lambda *_: host.overflow.toggle_at(self.chevron, taskbar.monitor))
        self.pack_start(self.chevron, False, False, 0)
        self.inline = Gtk.Box()
        self.pack_start(self.inline, False, False, 0)
        self._handler = host.connect("changed", lambda *_: self.refresh())
        self.connect("destroy", lambda *_: host.disconnect(self._handler))
        self.refresh()

    def refresh(self):
        clear_children(self.inline)
        items = self.host.visible_items()
        show_all = get_settings()["taskbar.tray_show_all"]
        self.chevron.set_visible(bool(items) and not show_all)
        self.chevron.set_no_show_all(True)
        if show_all:
            for item in items:
                self.inline.pack_start(self.host.item_button(item), False, False, 0)
        self.inline.show_all()


class TrayOverflow(Popup):
    def __init__(self, shell, host):
        super().__init__("tenwin-tray-overflow", anchors=(taskbar_edge(), Edge.RIGHT))
        self.shell = shell
        self.host = host
        self.grid = add_class(Gtk.FlowBox(), "tw-panel")
        self.grid.set_selection_mode(Gtk.SelectionMode.NONE)
        self.grid.set_max_children_per_line(4)
        self.grid.set_min_children_per_line(1)
        self.add(self.grid)

    def toggle_at(self, chevron, monitor):
        if self.is_open():
            self.close_popup()
            return
        toplevel = chevron.get_toplevel()
        x = chevron.translate_coordinates(toplevel, 0, 0)[0]
        center_from_right = toplevel.get_allocated_width() - x - chevron.get_allocated_width() // 2
        count = max(1, min(4, len(self.host.visible_items())))
        self.set_margins(right=max(0, center_from_right - count * 20))
        self.shell.toggle_popup(self, monitor)

    def on_open(self):
        clear_children(self.grid)
        for item in self.host.visible_items():
            button = self.host.item_button(item, 16)
            button.set_size_request(40, 40)
            self.grid.add(button)
        self.grid.show_all()
