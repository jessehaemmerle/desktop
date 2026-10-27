/*
 * tenwin-toplevel - bridge between wlr-foreign-toplevel-management and the
 * Tenwin shell.
 *
 * Prints one JSON object per line on stdout whenever a window changes:
 *   {"ev":"update","id":3,"title":"…","app_id":"…","maximized":false,
 *    "minimized":false,"activated":true,"fullscreen":false,"parent":0,
 *    "outputs":["HDMI-A-1"]}
 *   {"ev":"closed","id":3}
 *   {"ev":"ready"}        after the initial window list was sent
 *   {"ev":"finished"}     the compositor stopped the protocol
 *
 * Reads commands from stdin, one per line:
 *   activate ID | close ID | minimize ID | unminimize ID |
 *   maximize ID | unmaximize ID | fullscreen ID | unfullscreen ID
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#define _GNU_SOURCE
#include <errno.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <wayland-client.h>

#include "wlr-foreign-toplevel-management-unstable-v1-client-protocol.h"

#define MAX_OUTPUTS 16

struct output {
	struct wl_list link;
	struct wl_output *wl_output;
	uint32_t global_name;
	char *name;
};

struct toplevel {
	struct wl_list link;
	struct zwlr_foreign_toplevel_handle_v1 *handle;
	uint32_t id;
	char *title;
	char *app_id;
	bool maximized, minimized, activated, fullscreen;
	struct zwlr_foreign_toplevel_handle_v1 *parent;
	struct wl_output *outputs[MAX_OUTPUTS];
	int n_outputs;
};

static struct wl_display *display;
static struct wl_seat *seat;
static struct zwlr_foreign_toplevel_manager_v1 *manager;
static struct wl_list toplevels;
static struct wl_list outputs;
static uint32_t next_id = 1;
static bool running = true;

static void print_json_string(const char *s)
{
	putchar('"');
	for (const unsigned char *p = (const unsigned char *)(s ? s : ""); *p; p++) {
		switch (*p) {
		case '"': fputs("\\\"", stdout); break;
		case '\\': fputs("\\\\", stdout); break;
		case '\n': fputs("\\n", stdout); break;
		case '\r': fputs("\\r", stdout); break;
		case '\t': fputs("\\t", stdout); break;
		default:
			if (*p < 0x20)
				printf("\\u%04x", *p);
			else
				putchar(*p);
		}
	}
	putchar('"');
}

static const char *output_name(struct wl_output *wl_output)
{
	struct output *out;
	wl_list_for_each(out, &outputs, link) {
		if (out->wl_output == wl_output)
			return out->name ? out->name : "";
	}
	return "";
}

static struct toplevel *find_by_handle(struct zwlr_foreign_toplevel_handle_v1 *handle)
{
	struct toplevel *t;
	if (!handle)
		return NULL;
	wl_list_for_each(t, &toplevels, link) {
		if (t->handle == handle)
			return t;
	}
	return NULL;
}

static struct toplevel *find_by_id(uint32_t id)
{
	struct toplevel *t;
	wl_list_for_each(t, &toplevels, link) {
		if (t->id == id)
			return t;
	}
	return NULL;
}

static void emit_update(struct toplevel *t)
{
	struct toplevel *parent = find_by_handle(t->parent);
	printf("{\"ev\":\"update\",\"id\":%u,\"title\":", t->id);
	print_json_string(t->title);
	fputs(",\"app_id\":", stdout);
	print_json_string(t->app_id);
	printf(",\"maximized\":%s,\"minimized\":%s,\"activated\":%s,\"fullscreen\":%s,\"parent\":%u,\"outputs\":[",
	       t->maximized ? "true" : "false", t->minimized ? "true" : "false",
	       t->activated ? "true" : "false", t->fullscreen ? "true" : "false",
	       parent ? parent->id : 0);
	for (int i = 0; i < t->n_outputs; i++) {
		if (i)
			putchar(',');
		print_json_string(output_name(t->outputs[i]));
	}
	puts("]}");
	fflush(stdout);
}

/* --- toplevel handle events --------------------------------------------- */

static void handle_title(void *data, struct zwlr_foreign_toplevel_handle_v1 *h, const char *title)
{
	struct toplevel *t = data;
	free(t->title);
	t->title = strdup(title);
}

static void handle_app_id(void *data, struct zwlr_foreign_toplevel_handle_v1 *h, const char *app_id)
{
	struct toplevel *t = data;
	free(t->app_id);
	t->app_id = strdup(app_id);
}

static void handle_output_enter(void *data, struct zwlr_foreign_toplevel_handle_v1 *h,
				struct wl_output *output)
{
	struct toplevel *t = data;
	for (int i = 0; i < t->n_outputs; i++)
		if (t->outputs[i] == output)
			return;
	if (t->n_outputs < MAX_OUTPUTS)
		t->outputs[t->n_outputs++] = output;
}

static void handle_output_leave(void *data, struct zwlr_foreign_toplevel_handle_v1 *h,
				struct wl_output *output)
{
	struct toplevel *t = data;
	for (int i = 0; i < t->n_outputs; i++) {
		if (t->outputs[i] == output) {
			t->outputs[i] = t->outputs[--t->n_outputs];
			return;
		}
	}
}

static void handle_state(void *data, struct zwlr_foreign_toplevel_handle_v1 *h, struct wl_array *state)
{
	struct toplevel *t = data;
	uint32_t *entry;
	t->maximized = t->minimized = t->activated = t->fullscreen = false;
	wl_array_for_each(entry, state) {
		switch (*entry) {
		case ZWLR_FOREIGN_TOPLEVEL_HANDLE_V1_STATE_MAXIMIZED: t->maximized = true; break;
		case ZWLR_FOREIGN_TOPLEVEL_HANDLE_V1_STATE_MINIMIZED: t->minimized = true; break;
		case ZWLR_FOREIGN_TOPLEVEL_HANDLE_V1_STATE_ACTIVATED: t->activated = true; break;
		case ZWLR_FOREIGN_TOPLEVEL_HANDLE_V1_STATE_FULLSCREEN: t->fullscreen = true; break;
		}
	}
}

static void handle_done(void *data, struct zwlr_foreign_toplevel_handle_v1 *h)
{
	emit_update(data);
}

static void handle_closed(void *data, struct zwlr_foreign_toplevel_handle_v1 *h)
{
	struct toplevel *t = data;
	struct toplevel *other;
	printf("{\"ev\":\"closed\",\"id\":%u}\n", t->id);
	fflush(stdout);
	wl_list_for_each(other, &toplevels, link) {
		if (other->parent == t->handle)
			other->parent = NULL;
	}
	wl_list_remove(&t->link);
	zwlr_foreign_toplevel_handle_v1_destroy(t->handle);
	free(t->title);
	free(t->app_id);
	free(t);
}

static void handle_parent(void *data, struct zwlr_foreign_toplevel_handle_v1 *h,
			  struct zwlr_foreign_toplevel_handle_v1 *parent)
{
	struct toplevel *t = data;
	t->parent = parent;
}

static const struct zwlr_foreign_toplevel_handle_v1_listener handle_listener = {
	.title = handle_title,
	.app_id = handle_app_id,
	.output_enter = handle_output_enter,
	.output_leave = handle_output_leave,
	.state = handle_state,
	.done = handle_done,
	.closed = handle_closed,
	.parent = handle_parent,
};

/* --- manager events ------------------------------------------------------ */

static void manager_toplevel(void *data, struct zwlr_foreign_toplevel_manager_v1 *m,
			     struct zwlr_foreign_toplevel_handle_v1 *handle)
{
	struct toplevel *t = calloc(1, sizeof(*t));
	if (!t) {
		zwlr_foreign_toplevel_handle_v1_destroy(handle);
		return;
	}
	t->handle = handle;
	t->id = next_id++;
	wl_list_insert(toplevels.prev, &t->link);
	zwlr_foreign_toplevel_handle_v1_add_listener(handle, &handle_listener, t);
}

static void manager_finished(void *data, struct zwlr_foreign_toplevel_manager_v1 *m)
{
	puts("{\"ev\":\"finished\"}");
	fflush(stdout);
	running = false;
}

static const struct zwlr_foreign_toplevel_manager_v1_listener manager_listener = {
	.toplevel = manager_toplevel,
	.finished = manager_finished,
};

/* --- outputs ------------------------------------------------------------- */

static void output_geometry(void *data, struct wl_output *o, int32_t x, int32_t y, int32_t pw,
			    int32_t ph, int32_t subpixel, const char *make, const char *model,
			    int32_t transform) {}
static void output_mode(void *data, struct wl_output *o, uint32_t flags, int32_t w, int32_t h,
			int32_t refresh) {}
static void output_done(void *data, struct wl_output *o) {}
static void output_scale(void *data, struct wl_output *o, int32_t factor) {}

static void output_name_ev(void *data, struct wl_output *o, const char *name)
{
	struct output *out = data;
	free(out->name);
	out->name = strdup(name);
}

static void output_description(void *data, struct wl_output *o, const char *description) {}

static const struct wl_output_listener output_listener = {
	.geometry = output_geometry,
	.mode = output_mode,
	.done = output_done,
	.scale = output_scale,
	.name = output_name_ev,
	.description = output_description,
};

/* --- registry ------------------------------------------------------------ */

static void registry_global(void *data, struct wl_registry *registry, uint32_t name,
			    const char *interface, uint32_t version)
{
	if (strcmp(interface, zwlr_foreign_toplevel_manager_v1_interface.name) == 0) {
		manager = wl_registry_bind(registry, name, &zwlr_foreign_toplevel_manager_v1_interface,
					   version < 3 ? version : 3);
		zwlr_foreign_toplevel_manager_v1_add_listener(manager, &manager_listener, NULL);
	} else if (strcmp(interface, wl_seat_interface.name) == 0 && !seat) {
		seat = wl_registry_bind(registry, name, &wl_seat_interface, 1);
	} else if (strcmp(interface, wl_output_interface.name) == 0) {
		struct output *out = calloc(1, sizeof(*out));
		if (!out)
			return;
		out->global_name = name;
		out->wl_output = wl_registry_bind(registry, name, &wl_output_interface,
						  version < 4 ? version : 4);
		wl_output_add_listener(out->wl_output, &output_listener, out);
		wl_list_insert(&outputs, &out->link);
	}
}

static void registry_global_remove(void *data, struct wl_registry *registry, uint32_t name)
{
	struct output *out, *tmp;
	wl_list_for_each_safe(out, tmp, &outputs, link) {
		if (out->global_name == name) {
			wl_list_remove(&out->link);
			if (wl_output_get_version(out->wl_output) >= 3)
				wl_output_release(out->wl_output);
			else
				wl_output_destroy(out->wl_output);
			free(out->name);
			free(out);
		}
	}
}

static const struct wl_registry_listener registry_listener = {
	.global = registry_global,
	.global_remove = registry_global_remove,
};

/* --- commands ------------------------------------------------------------ */

static void run_command(char *line)
{
	char cmd[32];
	unsigned id;
	if (sscanf(line, "%31s %u", cmd, &id) != 2)
		return;
	struct toplevel *t = find_by_id(id);
	if (!t)
		return;
	struct zwlr_foreign_toplevel_handle_v1 *h = t->handle;
	if (!strcmp(cmd, "activate")) {
		if (t->minimized)
			zwlr_foreign_toplevel_handle_v1_unset_minimized(h);
		if (seat)
			zwlr_foreign_toplevel_handle_v1_activate(h, seat);
	} else if (!strcmp(cmd, "close")) {
		zwlr_foreign_toplevel_handle_v1_close(h);
	} else if (!strcmp(cmd, "minimize")) {
		zwlr_foreign_toplevel_handle_v1_set_minimized(h);
	} else if (!strcmp(cmd, "unminimize")) {
		zwlr_foreign_toplevel_handle_v1_unset_minimized(h);
	} else if (!strcmp(cmd, "maximize")) {
		zwlr_foreign_toplevel_handle_v1_set_maximized(h);
	} else if (!strcmp(cmd, "unmaximize")) {
		zwlr_foreign_toplevel_handle_v1_unset_maximized(h);
	} else if (!strcmp(cmd, "fullscreen")) {
		if (wl_proxy_get_version((struct wl_proxy *)h) >= 2)
			zwlr_foreign_toplevel_handle_v1_set_fullscreen(h, NULL);
	} else if (!strcmp(cmd, "unfullscreen")) {
		if (wl_proxy_get_version((struct wl_proxy *)h) >= 2)
			zwlr_foreign_toplevel_handle_v1_unset_fullscreen(h);
	}
}

static bool read_stdin(void)
{
	static char buf[4096];
	static size_t len;
	ssize_t n = read(STDIN_FILENO, buf + len, sizeof(buf) - len - 1);
	if (n <= 0)
		return n < 0 && (errno == EAGAIN || errno == EINTR);
	len += (size_t)n;
	buf[len] = '\0';
	char *start = buf, *nl;
	while ((nl = memchr(start, '\n', len - (size_t)(start - buf)))) {
		*nl = '\0';
		run_command(start);
		start = nl + 1;
	}
	len -= (size_t)(start - buf);
	memmove(buf, start, len);
	if (len >= sizeof(buf) - 1)
		len = 0; /* drop overlong garbage */
	return true;
}

int main(void)
{
	wl_list_init(&toplevels);
	wl_list_init(&outputs);

	display = wl_display_connect(NULL);
	if (!display) {
		fprintf(stderr, "tenwin-toplevel: cannot connect to Wayland display\n");
		return 1;
	}
	struct wl_registry *registry = wl_display_get_registry(display);
	wl_registry_add_listener(registry, &registry_listener, NULL);
	wl_display_roundtrip(display);
	if (!manager) {
		fprintf(stderr, "tenwin-toplevel: compositor lacks wlr-foreign-toplevel-management\n");
		return 2;
	}
	wl_display_roundtrip(display);
	wl_display_roundtrip(display);
	puts("{\"ev\":\"ready\"}");
	fflush(stdout);

	struct pollfd fds[2] = {
		{ .fd = wl_display_get_fd(display), .events = POLLIN },
		{ .fd = STDIN_FILENO, .events = POLLIN },
	};
	while (running) {
		while (wl_display_prepare_read(display) != 0)
			wl_display_dispatch_pending(display);
		if (wl_display_flush(display) < 0 && errno != EAGAIN) {
			wl_display_cancel_read(display);
			break;
		}
		if (poll(fds, 2, -1) < 0) {
			wl_display_cancel_read(display);
			if (errno == EINTR)
				continue;
			break;
		}
		if (fds[0].revents & POLLIN) {
			if (wl_display_read_events(display) < 0)
				break;
		} else {
			wl_display_cancel_read(display);
		}
		if (fds[0].revents & (POLLERR | POLLHUP))
			break;
		if (wl_display_dispatch_pending(display) < 0)
			break;
		if (fds[1].revents & POLLIN) {
			if (!read_stdin())
				break; /* the shell went away */
		} else if (fds[1].revents & (POLLHUP | POLLERR)) {
			break;
		}
		wl_display_flush(display);
	}
	wl_display_disconnect(display);
	return 0;
}
