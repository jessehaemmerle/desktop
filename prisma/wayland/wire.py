"""Wayland-Wire-Protokoll: Kodierung und Dekodierung von Nachrichten.

Jede Nachricht beginnt mit einem 8-Byte-Header: Objekt-ID (u32) und
(Größe << 16 | Opcode) (u32), gefolgt von 4-Byte-ausgerichteten Argumenten.
Signaturzeichen: u=uint, i=int, f=fixed, o=Objekt, n=neue ID, s=String, a=Array.
"""

from __future__ import annotations

import struct

HEADER = struct.Struct("=II")


def _pad(length: int) -> int:
    return (4 - length % 4) % 4


def pack_args(signature: str, args: list | tuple) -> bytes:
    if len(signature) != len(args):
        raise ValueError(f"Signatur {signature!r} erwartet {len(signature)} Argumente, bekam {len(args)}")
    out = bytearray()
    for kind, value in zip(signature, args):
        if kind in "uon":
            out += struct.pack("=I", int(value or 0))
        elif kind == "i":
            out += struct.pack("=i", int(value))
        elif kind == "f":
            out += struct.pack("=i", int(round(float(value) * 256)))
        elif kind == "s":
            if value is None:
                out += struct.pack("=I", 0)
                continue
            raw = str(value).encode("utf-8") + b"\0"
            out += struct.pack("=I", len(raw)) + raw + b"\0" * _pad(len(raw))
        elif kind == "a":
            raw = bytes(value)
            out += struct.pack("=I", len(raw)) + raw + b"\0" * _pad(len(raw))
        else:
            raise ValueError(f"Unbekannter Signaturtyp {kind!r}")
    return bytes(out)


def unpack_args(signature: str, data: bytes) -> list:
    args: list = []
    offset = 0
    for kind in signature:
        if kind in "uon":
            args.append(struct.unpack_from("=I", data, offset)[0])
            offset += 4
        elif kind == "i":
            args.append(struct.unpack_from("=i", data, offset)[0])
            offset += 4
        elif kind == "f":
            args.append(struct.unpack_from("=i", data, offset)[0] / 256.0)
            offset += 4
        elif kind in "sa":
            (length,) = struct.unpack_from("=I", data, offset)
            offset += 4
            raw = bytes(data[offset : offset + length])
            offset += length + _pad(length)
            if kind == "s":
                args.append(raw[:-1].decode("utf-8", "replace") if length else None)
            else:
                args.append(raw)
        else:
            raise ValueError(f"Unbekannter Signaturtyp {kind!r}")
    return args


def encode_message(object_id: int, opcode: int, payload: bytes = b"") -> bytes:
    size = HEADER.size + len(payload)
    return HEADER.pack(object_id, (size << 16) | opcode) + payload


def split_messages(buffer: bytes) -> tuple[list[tuple[int, int, bytes]], bytes]:
    """Zerlegt einen Puffer in vollständige Nachrichten; gibt den Rest zurück."""
    messages = []
    offset = 0
    while len(buffer) - offset >= HEADER.size:
        object_id, size_opcode = HEADER.unpack_from(buffer, offset)
        size, opcode = size_opcode >> 16, size_opcode & 0xFFFF
        if size < HEADER.size:
            raise ValueError("Beschädigte Wayland-Nachricht")
        if len(buffer) - offset < size:
            break
        messages.append((object_id, opcode, bytes(buffer[offset + HEADER.size : offset + size])))
        offset += size
    return messages, bytes(buffer[offset:])


def u32_array(data: bytes) -> list[int]:
    return list(struct.unpack(f"={len(data) // 4}I", data[: len(data) // 4 * 4]))
