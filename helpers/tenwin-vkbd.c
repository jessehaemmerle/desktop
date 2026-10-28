/*
 * tenwin-vkbd - send key presses through zwp_virtual_keyboard_v1.
 *
 * labwc 0.7 has no IPC, but it runs key bindings for virtual keyboards
 * (matched by keysym). Tenwin binds hidden key combinations such as
 * C-A-S-XF86Launch1 to window actions (SnapToRegion, ...) and triggers them with
 *
 *   tenwin-vkbd combo C-A-S-XF86Launch1 [combo ...]
 *
 * The on-screen keyboard keeps one instance running and writes commands
 * to stdin, one per line:
 *
 *   tenwin-vkbd --layout de [--variant nodeadkeys] --stdin
 *     tap CODE [shift] [altgr] [ctrl] [alt] [super]   press and release an evdev key
 *     combo C-A-S-XF86Launch1                                 same as the argument form
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#define _GNU_SOURCE
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include <xkbcommon/xkbcommon.h>

#include "virtual-keyboard-unstable-v1-client-protocol.h"

static struct wl_display *display;
static struct wl_seat *seat;
static struct zwp_virtual_keyboard_manager_v1 *manager;
static struct zwp_virtual_keyboard_v1 *keyboard;
static struct xkb_keymap *keymap;
static uint32_t mod_shift, mod_ctrl, mod_alt, mod_super, mod_altgr;

static void
registry_global(void *data, struct wl_registry *registry, uint32_t name,
		const char *interface, uint32_t version)
{
	if (strcmp(interface, wl_seat_interface.name) == 0 && !seat) {
		seat = wl_registry_bind(registry, name, &wl_seat_interface, 1);
	} else if (strcmp(interface, zwp_virtual_keyboard_manager_v1_interface.name) == 0) {
		manager = wl_registry_bind(registry, name,
			&zwp_virtual_keyboard_manager_v1_interface, 1);
	}
}

static void
registry_global_remove(void *data, struct wl_registry *registry, uint32_t name)
{
}

static const struct wl_registry_listener registry_listener = {
	.global = registry_global,
	.global_remove = registry_global_remove,
};

static uint32_t
now_ms(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (uint32_t)(ts.tv_sec * 1000 + ts.tv_nsec / 1000000);
}

static uint32_t
mod_mask(const char *name)
{
	xkb_mod_index_t index = xkb_keymap_mod_get_index(keymap, name);
	return index == XKB_MOD_INVALID ? 0 : 1u << index;
}

static bool
upload_keymap(const char *layout, const char *variant)
{
	struct xkb_context *ctx = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
	if (!ctx) {
		return false;
	}
	struct xkb_rule_names names = {
		.layout = layout,
		.variant = variant,
	};
	keymap = xkb_keymap_new_from_names(ctx, &names, XKB_KEYMAP_COMPILE_NO_FLAGS);
	if (!keymap) {
		fprintf(stderr, "tenwin-vkbd: cannot compile keymap for layout %s\n",
			layout ? layout : "(default)");
		return false;
	}
	char *text = xkb_keymap_get_as_string(keymap, XKB_KEYMAP_FORMAT_TEXT_V1);
	size_t size = strlen(text) + 1;
	int fd = memfd_create("tenwin-vkbd-keymap", MFD_CLOEXEC);
	if (fd < 0 || ftruncate(fd, size) < 0) {
		free(text);
		return false;
	}
	void *map = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	if (map == MAP_FAILED) {
		close(fd);
		free(text);
		return false;
	}
	memcpy(map, text, size);
	munmap(map, size);
	free(text);
	zwp_virtual_keyboard_v1_keymap(keyboard, WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1, fd, size);
	close(fd);

	mod_shift = mod_mask(XKB_MOD_NAME_SHIFT);
	mod_ctrl = mod_mask(XKB_MOD_NAME_CTRL);
	mod_alt = mod_mask(XKB_MOD_NAME_ALT);
	mod_super = mod_mask(XKB_MOD_NAME_LOGO);
	mod_altgr = mod_mask("Mod5");
	return true;
}

/* evdev key code for a keysym on the first level of the first layout, or -1 */
static int
keycode_for(xkb_keysym_t sym)
{
	xkb_keycode_t min = xkb_keymap_min_keycode(keymap);
	xkb_keycode_t max = xkb_keymap_max_keycode(keymap);
	for (xkb_keycode_t kc = min; kc <= max; kc++) {
		const xkb_keysym_t *syms;
		int n = xkb_keymap_key_get_syms_by_level(keymap, kc, 0, 0, &syms);
		for (int i = 0; i < n; i++) {
			if (syms[i] == sym) {
				return (int)kc - 8;
			}
		}
	}
	return -1;
}

static void
tap(uint32_t code, uint32_t mods)
{
	if (mods) {
		zwp_virtual_keyboard_v1_modifiers(keyboard, mods, 0, 0, 0);
	}
	zwp_virtual_keyboard_v1_key(keyboard, now_ms(), code, WL_KEYBOARD_KEY_STATE_PRESSED);
	zwp_virtual_keyboard_v1_key(keyboard, now_ms(), code, WL_KEYBOARD_KEY_STATE_RELEASED);
	if (mods) {
		zwp_virtual_keyboard_v1_modifiers(keyboard, 0, 0, 0, 0);
	}
	wl_display_roundtrip(display);
}

/* "C-A-S-W-F13": labwc's key binding syntax */
static bool
combo(const char *spec)
{
	uint32_t mods = 0;
	const char *p = spec;
	while (p[0] && p[1] == '-') {
		switch (p[0]) {
		case 'C': mods |= mod_ctrl; break;
		case 'A': mods |= mod_alt; break;
		case 'S': mods |= mod_shift; break;
		case 'W': mods |= mod_super; break;
		default:
			fprintf(stderr, "tenwin-vkbd: unknown modifier in %s\n", spec);
			return false;
		}
		p += 2;
	}
	xkb_keysym_t sym = xkb_keysym_from_name(p, XKB_KEYSYM_CASE_INSENSITIVE);
	int code = sym == XKB_KEY_NoSymbol ? -1 : keycode_for(sym);
	if (code < 0) {
		fprintf(stderr, "tenwin-vkbd: no key for %s\n", p);
		return false;
	}
	tap((uint32_t)code, mods);
	return true;
}

static bool
command(char *line)
{
	char *save = NULL;
	char *word = strtok_r(line, " \t\r\n", &save);
	if (!word) {
		return true;
	}
	if (!strcmp(word, "combo")) {
		char *spec = strtok_r(NULL, " \t\r\n", &save);
		return spec && combo(spec);
	}
	if (!strcmp(word, "tap")) {
		char *arg = strtok_r(NULL, " \t\r\n", &save);
		if (!arg) {
			return false;
		}
		char *end;
		long code = strtol(arg, &end, 10);
		if (*end || code <= 0 || code > 767) {
			return false;
		}
		uint32_t mods = 0;
		while ((arg = strtok_r(NULL, " \t\r\n", &save))) {
			if (!strcmp(arg, "shift")) mods |= mod_shift;
			else if (!strcmp(arg, "altgr")) mods |= mod_altgr;
			else if (!strcmp(arg, "ctrl")) mods |= mod_ctrl;
			else if (!strcmp(arg, "alt")) mods |= mod_alt;
			else if (!strcmp(arg, "super")) mods |= mod_super;
		}
		tap((uint32_t)code, mods);
		return true;
	}
	fprintf(stderr, "tenwin-vkbd: unknown command %s\n", word);
	return false;
}

static void
usage(void)
{
	fprintf(stderr, "usage: tenwin-vkbd [--layout L] [--variant V] (--stdin | combo SPEC ...)\n");
}

int
main(int argc, char *argv[])
{
	const char *layout = NULL, *variant = NULL;
	bool from_stdin = false;
	int first = 1;
	while (first < argc && !strncmp(argv[first], "--", 2)) {
		if (!strcmp(argv[first], "--stdin")) {
			from_stdin = true;
			first++;
		} else if (!strcmp(argv[first], "--layout") && first + 1 < argc) {
			layout = argv[first + 1];
			first += 2;
		} else if (!strcmp(argv[first], "--variant") && first + 1 < argc) {
			variant = argv[first + 1];
			first += 2;
		} else {
			usage();
			return 2;
		}
	}
	if (!from_stdin && first >= argc) {
		usage();
		return 2;
	}

	display = wl_display_connect(NULL);
	if (!display) {
		fprintf(stderr, "tenwin-vkbd: cannot connect to the Wayland display\n");
		return 1;
	}
	struct wl_registry *registry = wl_display_get_registry(display);
	wl_registry_add_listener(registry, &registry_listener, NULL);
	wl_display_roundtrip(display);
	if (!seat || !manager) {
		fprintf(stderr, "tenwin-vkbd: compositor lacks zwp_virtual_keyboard_manager_v1\n");
		return 1;
	}
	keyboard = zwp_virtual_keyboard_manager_v1_create_virtual_keyboard(manager, seat);
	if (!upload_keymap(layout, variant)) {
		return 1;
	}
	wl_display_roundtrip(display);

	int status = 0;
	if (from_stdin) {
		char *line = NULL;
		size_t cap = 0;
		while (getline(&line, &cap, stdin) > 0) {
			if (!command(line)) {
				status = 1;
			}
			if (wl_display_get_error(display)) {
				status = 1;
				break;
			}
		}
		free(line);
	} else {
		for (int i = first; i < argc; i++) {
			if (!strcmp(argv[i], "combo") && i + 1 < argc) {
				i++;
			}
			if (!combo(argv[i])) {
				status = 1;
			}
		}
	}
	zwp_virtual_keyboard_v1_destroy(keyboard);
	wl_display_roundtrip(display);
	wl_display_disconnect(display);
	return status;
}
