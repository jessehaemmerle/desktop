# Tenwin build and installation.
#
#   make                 build helpers and translations
#   make check           run the unit tests
#   make smoke           headless screenshots (needs labwc, grim)
#   make install DESTDIR=... PREFIX=/usr
#   make deb             build .deb packages (needs debhelper)

PREFIX ?= /usr
SYSCONFDIR ?= /etc
DESTDIR ?=
PYTHON ?= python3

BUILD := $(CURDIR)/build
SHARE := $(DESTDIR)$(PREFIX)/share
LIBEXEC := $(DESTDIR)$(PREFIX)/libexec/tenwin
BINDIR := $(DESTDIR)$(PREFIX)/bin
LANGS := $(basename $(notdir $(wildcard po/*.po)))
PY_SOURCES := $(shell find src -name '*.py')

LAUNCHERS := tenwin-session tenwin-ctl tenwin-python tenwin-shell tenwin-desktop tenwin-explorer \
	tenwin-settings tenwin-idle tenwin-xdg-autostart

all: helpers locale

helpers:
	$(MAKE) -C helpers BUILDDIR=$(BUILD)/helpers

locale: $(foreach l,$(LANGS),$(BUILD)/locale/$(l)/LC_MESSAGES/tenwin.mo)

$(BUILD)/locale/%/LC_MESSAGES/tenwin.mo: po/%.po
	mkdir -p $(dir $@)
	msgfmt --check -o $@ $<

pot:
	xgettext --language=Python --keyword=_ --keyword=N_ --keyword=ngettext:1,2 --keyword=pgettext:1c,2 \
		--from-code=UTF-8 --package-name=tenwin --package-version=0.1.0 -o po/tenwin.pot $(sort $(PY_SOURCES))
	for l in $(LANGS); do msgmerge --update --backup=none po/$$l.po po/tenwin.pot; done

check: all
	$(PYTHON) -m pytest -q tests

smoke: all
	tools/smoke-test.sh

install: install-desktop install-greeter

install-desktop: all
	install -d $(BINDIR) $(LIBEXEC) $(SHARE)/tenwin/lib $(SHARE)/tenwin/css
	for f in $(filter-out tenwin-greeter,$(LAUNCHERS)); do install -m 755 bin/$$f $(BINDIR)/$$f; done
	install -m 755 $(BUILD)/helpers/tenwin-lock $(BINDIR)/tenwin-lock
	install -m 755 $(BUILD)/helpers/tenwin-toplevel $(LIBEXEC)/tenwin-toplevel
	cd src && find tenwin -name '*.py' -not -path '*/greeter/*' -exec install -D -m 644 {} $(SHARE)/tenwin/lib/{} \;
	install -m 644 data/css/*.css $(SHARE)/tenwin/css/
	install -d $(SHARE)/backgrounds/tenwin
	install -m 644 data/wallpapers/*.svg $(SHARE)/backgrounds/tenwin/
	for t in Tenwin Tenwin-Dark; do \
		install -d $(SHARE)/themes/$$t/openbox-3 $(SHARE)/themes/$$t/gtk-3.0; \
		install -m 644 data/themes/$$t/index.theme $(SHARE)/themes/$$t/; \
		install -m 644 data/themes/$$t/openbox-3/* $(SHARE)/themes/$$t/openbox-3/; \
		install -m 644 data/themes/$$t/gtk-3.0/* $(SHARE)/themes/$$t/gtk-3.0/; \
	done
	install -d $(SHARE)/icons/hicolor/scalable/actions $(SHARE)/icons/hicolor/scalable/apps
	install -m 644 data/icons/hicolor/scalable/actions/*.svg $(SHARE)/icons/hicolor/scalable/actions/
	install -m 644 data/icons/hicolor/scalable/apps/*.svg $(SHARE)/icons/hicolor/scalable/apps/
	install -d $(SHARE)/fonts/truetype/selawik $(SHARE)/doc/tenwin-desktop
	install -m 644 data/fonts/*.ttf $(SHARE)/fonts/truetype/selawik/
	install -m 644 data/fonts/OFL-Selawik.txt $(SHARE)/doc/tenwin-desktop/
	install -D -m 644 data/sessions/tenwin.desktop $(SHARE)/wayland-sessions/tenwin.desktop
	install -d $(SHARE)/applications
	install -m 644 data/applications/*.desktop data/applications/tenwin-mimeapps.list $(SHARE)/applications/
	install -D -m 644 data/xdg-desktop-portal/tenwin-portals.conf $(SHARE)/xdg-desktop-portal/tenwin-portals.conf
	install -D -m 644 data/dconf/tenwin $(SHARE)/dconf/profile/tenwin
	install -D -m 644 data/pam/tenwin-lock $(DESTDIR)$(SYSCONFDIR)/pam.d/tenwin-lock
	for l in $(LANGS); do \
		install -D -m 644 $(BUILD)/locale/$$l/LC_MESSAGES/tenwin.mo $(SHARE)/locale/$$l/LC_MESSAGES/tenwin.mo; \
	done

install-greeter:
	install -d $(BINDIR) $(SHARE)/tenwin/lib/tenwin/greeter $(SHARE)/tenwin/css
	install -m 755 bin/tenwin-greeter $(BINDIR)/tenwin-greeter
	install -m 644 src/tenwin/greeter/*.py $(SHARE)/tenwin/lib/tenwin/greeter/
	install -D -m 644 data/lightdm/tenwin-greeter.desktop $(SHARE)/xgreeters/tenwin-greeter.desktop
	install -D -m 644 data/lightdm/90-tenwin-greeter.conf $(DESTDIR)$(SYSCONFDIR)/lightdm/lightdm.conf.d/90-tenwin-greeter.conf
	install -D -m 644 data/lightdm/tenwin-greeter.conf $(DESTDIR)$(SYSCONFDIR)/lightdm/tenwin-greeter.conf

deb:
	dpkg-buildpackage -us -uc -b

clean:
	rm -rf $(BUILD)
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

.PHONY: all helpers locale pot check smoke install install-desktop install-greeter deb clean
