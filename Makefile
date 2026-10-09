# Prisma – Installation
#   make install                     → /usr/local
#   sudo make install PREFIX=/usr    → systemweit (wie das Debian-Paket)
#   make test                        → Unit-Tests der GTK-freien Logik

PREFIX     ?= /usr/local
DESTDIR    ?=
PYTHON     ?= python3
LIBDIR      = $(PREFIX)/lib/prisma
DATADIR     = $(PREFIX)/share/prisma
BINDIR      = $(PREFIX)/bin
# Display-Manager (GDM, LightDM, SDDM) suchen Sitzungen zuverlässig nur hier:
SESSIONDIR ?= /usr/share/wayland-sessions

BINARIES = prisma-session prisma-shell prisma-msg prisma-settings prisma-lock prisma-launch

.PHONY: all install uninstall test check run clean

all:
	@echo "Nichts zu bauen – reines Python. 'make install' oder 'make test'."

install:
	install -d $(DESTDIR)$(LIBDIR) $(DESTDIR)$(BINDIR) $(DESTDIR)$(DATADIR)/labwc
	cd . && find prisma -name '*.py' -exec install -Dm644 {} $(DESTDIR)$(LIBDIR)/{} \;
	for bin in $(BINARIES); do \
		sed -e 's|@LIBDIR@|$(LIBDIR)|g' -e 's|@DATADIR@|$(DATADIR)|g' bin/$$bin > $(DESTDIR)$(BINDIR)/$$bin; \
		chmod 755 $(DESTDIR)$(BINDIR)/$$bin; \
	done
	install -m644 data/labwc/rc.xml data/labwc/menu.xml data/labwc/environment $(DESTDIR)$(DATADIR)/labwc/
	install -m755 data/labwc/autostart $(DESTDIR)$(DATADIR)/labwc/
	install -Dm644 data/sessions/prisma.desktop $(DESTDIR)$(SESSIONDIR)/prisma.desktop
	install -Dm644 data/applications/at.haemmerle.Prisma.Settings.desktop $(DESTDIR)$(PREFIX)/share/applications/at.haemmerle.Prisma.Settings.desktop
	install -Dm644 data/themes/Prisma/openbox-3/themerc $(DESTDIR)$(PREFIX)/share/themes/Prisma/openbox-3/themerc
	install -Dm644 data/portals/prisma-portals.conf $(DESTDIR)$(PREFIX)/share/xdg-desktop-portal/prisma-portals.conf
	install -Dm644 data/icons/prisma.svg $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/prisma.svg

uninstall:
	rm -rf $(DESTDIR)$(LIBDIR) $(DESTDIR)$(DATADIR)
	for bin in $(BINARIES); do rm -f $(DESTDIR)$(BINDIR)/$$bin; done
	rm -f $(DESTDIR)$(SESSIONDIR)/prisma.desktop
	rm -f $(DESTDIR)$(PREFIX)/share/applications/at.haemmerle.Prisma.Settings.desktop
	rm -rf $(DESTDIR)$(PREFIX)/share/themes/Prisma
	rm -f $(DESTDIR)$(PREFIX)/share/xdg-desktop-portal/prisma-portals.conf
	rm -f $(DESTDIR)$(PREFIX)/share/icons/hicolor/scalable/apps/prisma.svg

test:
	$(PYTHON) -m pytest -q tests

check: test
	$(PYTHON) -m compileall -q prisma

# Prisma in einem Fenster der laufenden Sitzung ausprobieren (labwc verschachtelt).
run:
	PRISMA_DATA=$(CURDIR)/data PATH=$(CURDIR)/bin:$$PATH ./bin/prisma-session

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache
