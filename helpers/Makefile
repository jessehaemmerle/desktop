# Builds the Tenwin C helpers.
CC ?= cc
CFLAGS ?= -O2 -g
CFLAGS += -Wall -Wextra -Wno-unused-parameter -std=c11
PKG_CONFIG ?= pkg-config
BUILDDIR ?= ../build/helpers
WAYLAND_SCANNER := $(shell $(PKG_CONFIG) --variable=wayland_scanner wayland-scanner)
WL_PROTOCOLS := $(shell $(PKG_CONFIG) --variable=pkgdatadir wayland-protocols)

TOPLEVEL_XML := protocols/wlr-foreign-toplevel-management-unstable-v1.xml
LOCK_XML := $(WL_PROTOCOLS)/staging/ext-session-lock/ext-session-lock-v1.xml
VKBD_XML := protocols/virtual-keyboard-unstable-v1.xml
XDG_OUTPUT_XML := $(WL_PROTOCOLS)/unstable/xdg-output/xdg-output-unstable-v1.xml

TOPLEVEL_PKGS := wayland-client
LOCK_PKGS := wayland-client xkbcommon cairo pangocairo gdk-pixbuf-2.0
VKBD_PKGS := wayland-client xkbcommon

all: $(BUILDDIR)/tenwin-toplevel $(BUILDDIR)/tenwin-lock $(BUILDDIR)/tenwin-vkbd

$(BUILDDIR):
	mkdir -p $@


$(BUILDDIR)/wlr-foreign-toplevel-management-unstable-v1-client-protocol.h: $(TOPLEVEL_XML) | $(BUILDDIR)
	$(WAYLAND_SCANNER) client-header $< $@
$(BUILDDIR)/wlr-foreign-toplevel-management-unstable-v1-protocol.c: $(TOPLEVEL_XML) | $(BUILDDIR)
	$(WAYLAND_SCANNER) private-code $< $@
$(BUILDDIR)/ext-session-lock-v1-client-protocol.h: $(LOCK_XML) | $(BUILDDIR)
	$(WAYLAND_SCANNER) client-header $< $@
$(BUILDDIR)/ext-session-lock-v1-protocol.c: $(LOCK_XML) | $(BUILDDIR)
	$(WAYLAND_SCANNER) private-code $< $@

$(BUILDDIR)/virtual-keyboard-unstable-v1-client-protocol.h: $(VKBD_XML) | $(BUILDDIR)
	$(WAYLAND_SCANNER) client-header $< $@
$(BUILDDIR)/virtual-keyboard-unstable-v1-protocol.c: $(VKBD_XML) | $(BUILDDIR)
	$(WAYLAND_SCANNER) private-code $< $@

$(BUILDDIR)/xdg-output-unstable-v1-client-protocol.h: $(XDG_OUTPUT_XML) | $(BUILDDIR)
	$(WAYLAND_SCANNER) client-header $< $@
$(BUILDDIR)/xdg-output-unstable-v1-protocol.c: $(XDG_OUTPUT_XML) | $(BUILDDIR)
	$(WAYLAND_SCANNER) private-code $< $@

$(BUILDDIR)/tenwin-toplevel: tenwin-toplevel.c \
		$(BUILDDIR)/wlr-foreign-toplevel-management-unstable-v1-client-protocol.h \
		$(BUILDDIR)/wlr-foreign-toplevel-management-unstable-v1-protocol.c \
		$(BUILDDIR)/xdg-output-unstable-v1-client-protocol.h \
		$(BUILDDIR)/xdg-output-unstable-v1-protocol.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -I$(BUILDDIR) $(shell $(PKG_CONFIG) --cflags $(TOPLEVEL_PKGS)) \
		-o $@ tenwin-toplevel.c $(BUILDDIR)/wlr-foreign-toplevel-management-unstable-v1-protocol.c \
		$(BUILDDIR)/xdg-output-unstable-v1-protocol.c \
		$(LDFLAGS) $(shell $(PKG_CONFIG) --libs $(TOPLEVEL_PKGS))

$(BUILDDIR)/tenwin-lock: tenwin-lock.c \
		$(BUILDDIR)/ext-session-lock-v1-client-protocol.h \
		$(BUILDDIR)/ext-session-lock-v1-protocol.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -I$(BUILDDIR) $(shell $(PKG_CONFIG) --cflags $(LOCK_PKGS)) \
		-o $@ tenwin-lock.c $(BUILDDIR)/ext-session-lock-v1-protocol.c \
		$(LDFLAGS) $(shell $(PKG_CONFIG) --libs $(LOCK_PKGS)) -lpam -lm

$(BUILDDIR)/tenwin-vkbd: tenwin-vkbd.c \
		$(BUILDDIR)/virtual-keyboard-unstable-v1-client-protocol.h \
		$(BUILDDIR)/virtual-keyboard-unstable-v1-protocol.c
	$(CC) $(CPPFLAGS) $(CFLAGS) -I$(BUILDDIR) $(shell $(PKG_CONFIG) --cflags $(VKBD_PKGS)) \
		-o $@ tenwin-vkbd.c $(BUILDDIR)/virtual-keyboard-unstable-v1-protocol.c \
		$(LDFLAGS) $(shell $(PKG_CONFIG) --libs $(VKBD_PKGS))

clean:
	rm -rf $(BUILDDIR)

.PHONY: all clean
