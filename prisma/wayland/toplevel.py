"""Fensterliste über ``zwlr_foreign_toplevel_management_unstable_v1``.

Unterstützt von labwc, sway, Wayfire, river, Hyprland u. a. Die Klasse ist bewusst
frei von GTK: Die Shell ruft ``dispatch()`` auf, sobald der Socket lesbar ist.
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass, field
from typing import Callable

from . import wire

MANAGER_IFACE = "zwlr_foreign_toplevel_manager_v1"

# Ereignis-Signaturen je Schnittstelle (Index = Opcode)
EVENTS = {
    "wl_display": ["ous", "u"],
    "wl_registry": ["usu", "u"],
    "wl_callback": ["u"],
    "wl_seat": ["u", "s"],
    MANAGER_IFACE: ["n", ""],
    "handle": ["s", "s", "o", "o", "a", "", "", "o"],
}

# Requests am Toplevel-Handle
REQ_SET_MAXIMIZED, REQ_UNSET_MAXIMIZED = 0, 1
REQ_SET_MINIMIZED, REQ_UNSET_MINIMIZED = 2, 3
REQ_ACTIVATE, REQ_CLOSE, REQ_DESTROY = 4, 5, 7
REQ_SET_FULLSCREEN, REQ_UNSET_FULLSCREEN = 8, 9

STATE_MAXIMIZED, STATE_MINIMIZED, STATE_ACTIVATED, STATE_FULLSCREEN = 0, 1, 2, 3


@dataclass
class Toplevel:
    handle: int
    title: str = ""
    app_id: str = ""
    maximized: bool = False
    minimized: bool = False
    activated: bool = False
    fullscreen: bool = False
    parent: int = 0
    ready: bool = False
    extra: dict = field(default_factory=dict)  # frei nutzbar für die Shell

    def __hash__(self) -> int:
        return hash(self.handle)


class WaylandError(RuntimeError):
    pass


def display_socket_path(display: str | None = None) -> str:
    display = display or os.environ.get("WAYLAND_DISPLAY") or "wayland-0"
    if display.startswith("/"):
        return display
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime:
        raise WaylandError("XDG_RUNTIME_DIR ist nicht gesetzt")
    return os.path.join(runtime, display)


class ToplevelTracker:
    def __init__(
        self,
        sock: socket.socket | None = None,
        on_added: Callable[[Toplevel], None] | None = None,
        on_changed: Callable[[Toplevel], None] | None = None,
        on_removed: Callable[[Toplevel], None] | None = None,
    ):
        if sock is None:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(display_socket_path())
        self.sock = sock
        self.sock.setblocking(False)
        self.on_added = on_added or (lambda t: None)
        self.on_changed = on_changed or (lambda t: None)
        self.on_removed = on_removed or (lambda t: None)
        self._buffer = b""
        self._next_id = 2
        self._objects: dict[int, str] = {1: "wl_display"}
        self._pending: dict[int, dict] = {}
        self.toplevels: dict[int, Toplevel] = {}
        self.seat = 0
        self.manager = 0
        self.manager_version = 0
        self.globals_done = False
        self.registry = self._new_object("wl_registry")
        self._send(1, 1, "n", [self.registry])  # wl_display.get_registry
        self._sync_cb = self._new_object("wl_callback")
        self._send(1, 0, "n", [self._sync_cb])  # wl_display.sync

    # ---------------------------------------------------------------- intern
    def fileno(self) -> int:
        return self.sock.fileno()

    def _new_object(self, interface: str) -> int:
        object_id = self._next_id
        self._next_id += 1
        self._objects[object_id] = interface
        return object_id

    def _send(self, object_id: int, opcode: int, signature: str, args: list) -> None:
        payload = wire.pack_args(signature, args)
        self.sock.sendall(wire.encode_message(object_id, opcode, payload))

    def _bind(self, name: int, interface: str, version: int, local_iface: str | None = None) -> int:
        object_id = self._new_object(local_iface or interface)
        # wl_registry.bind(name, new_id ohne Typ = (interface, version, id))
        self._send(self.registry, 0, "usun", [name, interface, version, object_id])
        return object_id

    # --------------------------------------------------------------- Ereignisse
    def dispatch(self) -> bool:
        """Liest alle verfügbaren Daten. ``False`` = Verbindung beendet."""
        while True:
            try:
                chunk = self.sock.recv(65536)
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                return False
            if not chunk:
                return False
            self._buffer += chunk
        messages, self._buffer = wire.split_messages(self._buffer)
        for object_id, opcode, payload in messages:
            self._handle(object_id, opcode, payload)
        return True

    def _handle(self, object_id: int, opcode: int, payload: bytes) -> None:
        interface = self._objects.get(object_id)
        if interface is None:
            return  # Ereignis an bereits zerstörtes Objekt
        signatures = EVENTS.get(interface, [])
        if opcode >= len(signatures):
            return
        args = wire.unpack_args(signatures[opcode], payload)
        handler = getattr(self, f"_on_{interface}", None)
        if handler:
            handler(object_id, opcode, args)

    def _on_wl_display(self, _oid: int, opcode: int, args: list) -> None:
        if opcode == 0:
            raise WaylandError(f"Wayland-Protokollfehler an Objekt {args[0]}: {args[2]} (Code {args[1]})")
        if opcode == 1:  # delete_id
            self._objects.pop(args[0], None)

    def _on_wl_registry(self, _oid: int, opcode: int, args: list) -> None:
        if opcode != 0:
            return
        name, interface, version = args
        if interface == MANAGER_IFACE and not self.manager:
            self.manager_version = min(version, 3)
            self.manager = self._bind(name, interface, self.manager_version)
        elif interface == "wl_seat" and not self.seat:
            self.seat = self._bind(name, interface, 1)

    def _on_wl_callback(self, oid: int, _opcode: int, _args: list) -> None:
        if oid == self._sync_cb:
            self.globals_done = True

    def _on_zwlr_foreign_toplevel_manager_v1(self, _oid: int, opcode: int, args: list) -> None:
        if opcode == 0:
            handle = args[0]
            self._objects[handle] = "handle"
            self.toplevels[handle] = Toplevel(handle=handle)
        elif opcode == 1:  # finished
            self.manager = 0

    def _on_handle(self, oid: int, opcode: int, args: list) -> None:
        top = self.toplevels.get(oid)
        if top is None:
            return
        if opcode == 0:
            top.title = args[0] or ""
        elif opcode == 1:
            top.app_id = args[0] or ""
        elif opcode == 4:
            states = set(wire.u32_array(args[0]))
            top.maximized = STATE_MAXIMIZED in states
            top.minimized = STATE_MINIMIZED in states
            top.activated = STATE_ACTIVATED in states
            top.fullscreen = STATE_FULLSCREEN in states
        elif opcode == 7:
            top.parent = args[0]
        elif opcode == 5:  # done
            if top.ready:
                self.on_changed(top)
            else:
                top.ready = True
                self.on_added(top)
        elif opcode == 6:  # closed
            self.toplevels.pop(oid, None)
            self._send(oid, REQ_DESTROY, "", [])
            self._objects.pop(oid, None)
            if top.ready:
                self.on_removed(top)

    # ---------------------------------------------------------------- Requests
    @property
    def available(self) -> bool:
        return bool(self.manager)

    def _request(self, top: Toplevel, opcode: int, signature: str = "", args: list | None = None) -> None:
        if top.handle in self.toplevels:
            try:
                self._send(top.handle, opcode, signature, args or [])
            except OSError:
                pass

    def activate(self, top: Toplevel) -> None:
        if self.seat:
            if top.minimized:
                self._request(top, REQ_UNSET_MINIMIZED)
            self._request(top, REQ_ACTIVATE, "o", [self.seat])

    def close(self, top: Toplevel) -> None:
        self._request(top, REQ_CLOSE)

    def set_minimized(self, top: Toplevel, value: bool) -> None:
        self._request(top, REQ_SET_MINIMIZED if value else REQ_UNSET_MINIMIZED)

    def set_maximized(self, top: Toplevel, value: bool) -> None:
        self._request(top, REQ_SET_MAXIMIZED if value else REQ_UNSET_MAXIMIZED)

    def set_fullscreen(self, top: Toplevel, value: bool) -> None:
        if self.manager_version >= 2:
            if value:
                self._request(top, REQ_SET_FULLSCREEN, "o", [0])
            else:
                self._request(top, REQ_UNSET_FULLSCREEN)

    def active(self) -> Toplevel | None:
        return next((t for t in self.toplevels.values() if t.activated and t.ready), None)
