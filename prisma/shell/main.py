"""Einstiegspunkt: ``prisma-shell``."""

from __future__ import annotations

import os
import sys


def main() -> int:
    if not os.environ.get("WAYLAND_DISPLAY"):
        print("prisma-shell: Prisma benötigt eine Wayland-Sitzung (z. B. über „prisma-session“).", file=sys.stderr)
        return 1
    os.environ["GDK_BACKEND"] = "wayland"
    from .app import PrismaShell  # das Paket-__init__ legt die gi-Versionen fest

    return PrismaShell().run(sys.argv[:1])


if __name__ == "__main__":
    sys.exit(main())
