"""Testet den reinen Python-Wayland-Client gegen einen simulierten Compositor (socketpair)."""

import socket
import struct

from prisma.wayland import wire
from prisma.wayland.toplevel import MANAGER_IFACE, ToplevelTracker


def test_pack_unpack_roundtrip():
    payload = wire.pack_args("uisao", [7, -3, "Hallo Welt", b"\x01\x00\x00\x00", 42])
    assert len(payload) % 4 == 0
    assert wire.unpack_args("uisao", payload) == [7, -3, "Hallo Welt", b"\x01\x00\x00\x00", 42]
    assert wire.unpack_args("s", wire.pack_args("s", [None])) == [None]
    assert wire.unpack_args("f", wire.pack_args("f", [1.5])) == [1.5]


def test_split_messages_keeps_partial_tail():
    one = wire.encode_message(3, 1, wire.pack_args("u", [9]))
    two = wire.encode_message(4, 0, wire.pack_args("s", ["abc"]))
    messages, rest = wire.split_messages(one + two[:5])
    assert messages == [(3, 1, wire.pack_args("u", [9]))]
    assert rest == two[:5]


class FakeCompositor:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = b""

    def send(self, object_id, opcode, signature="", args=()):
        self.sock.sendall(wire.encode_message(object_id, opcode, wire.pack_args(signature, list(args))))

    def requests(self):
        self.sock.setblocking(False)
        try:
            while True:
                chunk = self.sock.recv(65536)
                if not chunk:
                    break
                self.buffer += chunk
        except BlockingIOError:
            pass
        messages, self.buffer = wire.split_messages(self.buffer)
        return messages


def make_pair():
    client_sock, server_sock = socket.socketpair()
    events = {"added": [], "changed": [], "removed": []}
    tracker = ToplevelTracker(
        sock=client_sock,
        on_added=lambda t: events["added"].append(t),
        on_changed=lambda t: events["changed"].append(t),
        on_removed=lambda t: events["removed"].append(t),
    )
    return tracker, FakeCompositor(server_sock), events


def test_registry_binds_manager_and_seat():
    tracker, server, _events = make_pair()
    initial = server.requests()
    assert initial[0][:2] == (1, 1)  # get_registry
    registry = struct.unpack("=I", initial[0][2])[0]
    server.send(registry, 0, "usu", [1, "wl_compositor", 5])
    server.send(registry, 0, "usu", [2, MANAGER_IFACE, 3])
    server.send(registry, 0, "usu", [3, "wl_seat", 8])
    tracker.dispatch()
    binds = [m for m in server.requests() if m[0] == registry]
    names = [wire.unpack_args("usun", payload)[1] for _oid, _op, payload in binds]
    assert names == [MANAGER_IFACE, "wl_seat"]
    assert tracker.available and tracker.seat


def _setup_window(tracker, server, events):
    initial = server.requests()
    registry = struct.unpack("=I", initial[0][2])[0]
    server.send(registry, 0, "usu", [2, MANAGER_IFACE, 3])
    server.send(registry, 0, "usu", [3, "wl_seat", 8])
    tracker.dispatch()
    server.requests()
    handle = 0xFF000001
    server.send(tracker.manager, 0, "n", [handle])
    server.send(handle, 0, "s", ["Dokument – Editor"])
    server.send(handle, 1, "s", ["org.gnome.TextEditor"])
    server.send(handle, 4, "a", [struct.pack("=I", 2)])  # activated
    server.send(handle, 5)
    tracker.dispatch()
    return handle


def test_toplevel_lifecycle_and_requests():
    tracker, server, events = make_pair()
    handle = _setup_window(tracker, server, events)
    assert len(events["added"]) == 1
    top = events["added"][0]
    assert (top.title, top.app_id, top.activated, top.minimized) == ("Dokument – Editor", "org.gnome.TextEditor", True, False)
    assert tracker.active() is top

    tracker.set_minimized(top, True)
    tracker.activate(top)
    sent = [(oid, op) for oid, op, _p in server.requests()]
    assert (handle, 2) in sent  # set_minimized
    assert (handle, 4) in sent  # activate(seat)

    server.send(handle, 4, "a", [struct.pack("=II", 1, 0)])  # minimiert + maximiert
    server.send(handle, 5)
    tracker.dispatch()
    assert top.minimized and top.maximized and not top.activated
    assert events["changed"] == [top]

    server.send(handle, 6)  # closed
    tracker.dispatch()
    assert events["removed"] == [top]
    assert handle not in tracker.toplevels
    assert (handle, 7) in [(oid, op) for oid, op, _p in server.requests()]  # destroy


def test_hangup_is_reported():
    tracker, server, _events = make_pair()
    server.sock.close()
    assert tracker.dispatch() is False
