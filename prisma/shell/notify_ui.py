"""Benachrichtigungskarten und das Popup-Fenster oben rechts."""

from __future__ import annotations

import time
from datetime import datetime

from gi.repository import GLib, Gtk

from ..core.policy import URGENCY_CRITICAL
from . import util

DEFAULT_TIMEOUT_MS = 6500
MAX_POPUPS = 4


def relative_time(timestamp: float) -> str:
    delta = time.time() - timestamp
    if delta < 60:
        return "jetzt"
    if delta < 3600:
        return f"vor {int(delta // 60)} Min."
    return datetime.fromtimestamp(timestamp).strftime("%H:%M")


class NotificationCard(Gtk.EventBox):
    def __init__(self, hub, note, in_center: bool = False, on_close=None):
        super().__init__()
        self.hub = hub
        self.note = note
        self._on_close = on_close
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        util.add_class(box, "card", "notification")
        if in_center:
            util.add_class(box, "in-center")
        if note.urgency >= URGENCY_CRITICAL:
            util.add_class(box, "critical")
        self.add(box)

        head = Gtk.Box(spacing=8)
        app = hub.apps.get(note.desktop_entry) if note.desktop_entry else None
        icon = note.image or note.icon or (app.icon if app else None) or "preferences-system-notifications-symbolic"
        image = Gtk.Image()
        if hasattr(icon, "scale_simple"):
            image.set_from_pixbuf(icon.scale_simple(36, 36, 2))
        else:
            util.set_icon(image, icon, 36, "preferences-system-notifications-symbolic")
        image.set_valign(Gtk.Align.START)
        head.pack_start(image, False, False, 0)

        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        meta = Gtk.Box(spacing=6)
        meta.pack_start(util.label(note.app_name, "notif-app", ellipsize=True), False, False, 0)
        meta.pack_start(util.label("·", "notif-time"), False, False, 0)
        meta.pack_start(util.label(relative_time(note.timestamp), "notif-time"), False, False, 0)
        if note.held:
            meta.pack_start(util.label("· gesammelt", "notif-time"), False, False, 0)
        text.pack_start(meta, False, False, 0)
        if note.summary:
            text.pack_start(util.label(note.summary, "notif-summary", wrap=True), False, False, 0)
        if note.body:
            body = util.label(note.body, "notif-body", wrap=True)
            body.set_lines(4)
            from gi.repository import Pango

            body.set_ellipsize(Pango.EllipsizeMode.END)
            text.pack_start(body, False, False, 0)
        head.pack_start(text, True, True, 0)

        close = Gtk.Button()
        close.add(util.icon_image("window-close-symbolic", 14))
        util.add_class(close, "notif-close")
        close.set_valign(Gtk.Align.START)
        close.set_tooltip_text("Verwerfen")
        close.connect("clicked", lambda *_: self._dismiss())
        head.pack_end(close, False, False, 0)
        box.pack_start(head, False, False, 0)

        buttons = [(k, l) for k, l in note.actions if k != "default"]
        if buttons:
            row = Gtk.Box(spacing=6, homogeneous=True)
            for key, title in buttons[:3]:
                btn = Gtk.Button(label=title)
                util.add_class(btn, "notif-action")
                btn.connect("clicked", lambda _b, k=key: hub.notifications.invoke(note.id, k))
                row.pack_start(btn, True, True, 0)
            box.pack_start(row, False, False, 0)

        self.connect("button-release-event", self._on_click)

    def _on_click(self, _widget, event) -> bool:
        if event.button == 1:
            keys = [k for k, _ in self.note.actions]
            if "default" in keys or self.note.desktop_entry:
                self.hub.notifications.invoke(self.note.id, "default")
            else:
                self._dismiss()
            return True
        if event.button in (2, 3):
            self._dismiss()
            return True
        return False

    def _dismiss(self) -> None:
        if self._on_close:
            self._on_close(self.note)
        else:
            self.hub.notifications.close(self.note.id)


class NotificationPopups:
    """Stapel aktueller Popups – oben rechts, unter der Leiste."""

    def __init__(self, app, hub):
        self.hub = hub
        self.window = util.layer_window(
            app, "notifications", layer="overlay", anchors=("top", "right"), margins={"top": 0, "right": 0}
        )
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        # Platz für den Schatten, sonst schneidet die Fenstergrenze ihn ab
        self.box.set_margin_start(22)
        self.box.set_margin_end(18)
        self.box.set_margin_top(8)
        self.box.set_margin_bottom(24)
        self.window.add(self.box)
        self.box.show()
        self._cards: dict[int, tuple[Gtk.Revealer, int]] = {}
        self.suppressed = False
        hub.notifications.connect("popup", lambda _s, note: self.show(note))
        hub.notifications.connect("withdrawn", lambda _s, nid: self.remove(nid))

    def set_suppressed(self, value: bool) -> None:
        """Während ein Panel offen ist, keine Popups darüber legen."""
        self.suppressed = value
        if value:
            self.window.hide()
        elif self._cards:
            self.window.show()

    def show(self, note) -> None:
        self.remove(note.id, animate=False)
        if self.suppressed:
            return
        revealer = Gtk.Revealer()
        revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        revealer.set_transition_duration(220)
        card = NotificationCard(self.hub, note, on_close=lambda n: self.remove(n.id, dismiss=True))
        revealer.add(card)
        self.box.pack_start(revealer, False, False, 0)
        revealer.show_all()
        revealer.set_reveal_child(True)
        timeout = note.timeout if note.timeout and note.timeout > 0 else DEFAULT_TIMEOUT_MS
        source = 0
        if note.urgency < URGENCY_CRITICAL and note.timeout != 0:
            source = GLib.timeout_add(timeout, self._expire, note)
        self._cards[note.id] = (revealer, source)
        while len(self._cards) > MAX_POPUPS:
            self.remove(next(iter(self._cards)))
        if not self.suppressed:
            self.window.show()

    def _expire(self, note) -> bool:
        entry = self._cards.get(note.id)
        if entry:
            self._cards[note.id] = (entry[0], 0)
        self.remove(note.id)
        self.hub.notifications.expire_popup(note)
        return False

    def remove(self, nid: int, animate: bool = True, dismiss: bool = False) -> None:
        entry = self._cards.pop(nid, None)
        if dismiss:
            self.hub.notifications.close(nid)
        if entry is None:
            return
        revealer, source = entry
        if source:
            GLib.source_remove(source)
        if animate:
            revealer.set_reveal_child(False)
            GLib.timeout_add(260, self._destroy, revealer)
        else:
            self._destroy(revealer)

    def _destroy(self, revealer) -> bool:
        revealer.destroy()
        if not self._cards or self.suppressed:
            self.window.hide()
        self.window.resize(1, 1)
        return False
