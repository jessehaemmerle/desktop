/*
 * tenwin-lock - Windows 10 style lock screen for Tenwin.
 *
 * Uses ext-session-lock-v1: if this program crashes the session stays
 * locked. The password is checked with PAM (service "tenwin-lock") in a
 * child process so the UI stays responsive.
 *
 *   tenwin-lock [--daemonize] [--image PATH]
 *
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#define _GNU_SOURCE
#include <cairo.h>
#include <errno.h>
#include <fcntl.h>
#include <gdk-pixbuf/gdk-pixbuf.h>
#include <locale.h>
#include <math.h>
#include <pango/pangocairo.h>
#include <poll.h>
#include <pwd.h>
#include <security/pam_appl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/file.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include <xkbcommon/xkbcommon.h>

#include "ext-session-lock-v1-client-protocol.h"

#define PW_MAX 512
#define FONT "Selawik, Segoe UI, Noto Sans, sans-serif"

enum state { ST_CURTAIN, ST_LOGIN, ST_CHECKING, ST_ERROR };

struct buffer {
	struct wl_buffer *wl_buffer;
	void *data;
	size_t size;
};

struct output {
	struct wl_list link;
	uint32_t global_name;
	struct wl_output *wl_output;
	struct wl_surface *surface;
	struct ext_session_lock_surface_v1 *lock_surface;
	int32_t scale;
	uint32_t width, height;
	bool configured;
	cairo_surface_t *bg, *bg_blur; /* cached backgrounds at buffer size */
	uint32_t bg_w, bg_h;
};

static struct {
	struct wl_display *display;
	struct wl_compositor *compositor;
	struct wl_shm *shm;
	struct wl_seat *seat;
	struct wl_keyboard *keyboard;
	struct wl_pointer *pointer;
	struct ext_session_lock_manager_v1 *lock_manager;
	struct ext_session_lock_v1 *lock;
	struct wl_list outputs;
	struct xkb_context *xkb_context;
	struct xkb_keymap *xkb_keymap;
	struct xkb_state *xkb_state;
	bool locked, finished, running;
	enum state state;
	char password[PW_MAX];
	size_t pw_len;
	/* key repeat */
	int32_t repeat_rate, repeat_delay;
	uint32_t repeat_key;
	long long repeat_next_ms;
	/* PAM child */
	pid_t auth_pid;
	int auth_fd;
	/* appearance */
	char *image_path;
	char accent[8];
	bool clock_24h;
	bool german;
	char *user_name;
	char *avatar_path;
	GdkPixbuf *image;
	GdkPixbuf *avatar;
	char last_clock[32];
	double pointer_x, pointer_y;
	struct output *pointer_output;
} lk;

static long long now_ms(void);

/* ------------------------------------------------------------------------ */
/* Strings                                                                  */

static const char *tr(const char *en)
{
	if (!lk.german)
		return en;
	if (!strcmp(en, "Password")) return "Kennwort";
	if (!strcmp(en, "The password is incorrect. Try again.")) return "Das Kennwort ist falsch. Wiederholen Sie den Vorgang.";
	if (!strcmp(en, "Welcome")) return "Willkommen";
	if (!strcmp(en, "OK")) return "OK";
	if (!strcmp(en, "Press a key or click to sign in")) return "Zum Anmelden eine Taste drücken oder klicken";
	return en;
}

/* ------------------------------------------------------------------------ */
/* Settings (tiny reader for the flat JSON written by tenwin.config)       */

static char *read_file(const char *path)
{
	FILE *f = fopen(path, "r");
	if (!f)
		return NULL;
	char *buf = NULL;
	size_t cap = 0, len = 0;
	for (;;) {
		if (len + 4096 + 1 > cap) {
			cap = cap ? cap * 2 : 8192;
			if (cap > 1 << 20)
				break;
			char *n = realloc(buf, cap);
			if (!n)
				break;
			buf = n;
		}
		size_t r = fread(buf + len, 1, 4096, f);
		len += r;
		if (r < 4096)
			break;
	}
	fclose(f);
	if (buf)
		buf[len] = '\0';
	return buf;
}

/* Returns a newly allocated string value for "key", or NULL. */
static char *json_string(const char *json, const char *key)
{
	if (!json)
		return NULL;
	char pattern[128];
	snprintf(pattern, sizeof(pattern), "\"%s\"", key);
	const char *p = strstr(json, pattern);
	if (!p)
		return NULL;
	p += strlen(pattern);
	while (*p == ' ' || *p == ':' || *p == '\t' || *p == '\n')
		p++;
	if (*p != '"')
		return NULL;
	p++;
	char *out = malloc(strlen(p) + 1);
	if (!out)
		return NULL;
	char *o = out;
	while (*p && *p != '"') {
		if (*p == '\\' && p[1]) {
			p++;
			switch (*p) {
			case 'n': *o++ = '\n'; break;
			case 't': *o++ = '\t'; break;
			default: *o++ = *p; break; /* \" \\ \/ */
			}
			p++;
		} else {
			*o++ = *p++;
		}
	}
	*o = '\0';
	return out;
}

static int json_bool(const char *json, const char *key, int fallback)
{
	if (!json)
		return fallback;
	char pattern[128];
	snprintf(pattern, sizeof(pattern), "\"%s\"", key);
	const char *p = strstr(json, pattern);
	if (!p)
		return fallback;
	p += strlen(pattern);
	while (*p == ' ' || *p == ':')
		p++;
	if (!strncmp(p, "true", 4))
		return 1;
	if (!strncmp(p, "false", 5))
		return 0;
	return fallback;
}

static bool file_exists(const char *path)
{
	struct stat st;
	return path && *path && stat(path, &st) == 0 && S_ISREG(st.st_mode);
}

static void load_settings(void)
{
	const char *config = getenv("XDG_CONFIG_HOME");
	char path[4096];
	if (config && *config)
		snprintf(path, sizeof(path), "%s/tenwin/settings.json", config);
	else
		snprintf(path, sizeof(path), "%s/.config/tenwin/settings.json", getenv("HOME") ? getenv("HOME") : "");
	char *json = read_file(path);

	if (!lk.image_path) {
		char *p = json_string(json, "lockscreen.picture");
		if (!file_exists(p)) {
			free(p);
			p = json_string(json, "background.picture");
		}
		if (!file_exists(p)) {
			free(p);
			p = NULL;
		}
		lk.image_path = p ? p : strdup("/usr/share/backgrounds/tenwin/tenwin-hero.svg");
	}
	char *accent = json_string(json, "appearance.accent");
	snprintf(lk.accent, sizeof(lk.accent), "%s", accent && strlen(accent) == 7 ? accent : "#0078D7");
	free(accent);
	lk.clock_24h = json_bool(json, "region.clock_24h", 1);

	char *lang = json_string(json, "region.language");
	if (lang && !strcmp(lang, "de")) {
		lk.german = true;
	} else if (lang && !strcmp(lang, "en")) {
		lk.german = false;
	} else {
		const char *vars[] = { "LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG" };
		for (size_t i = 0; i < sizeof(vars) / sizeof(vars[0]); i++) {
			const char *v = getenv(vars[i]);
			if (v && *v) {
				lk.german = !strncmp(v, "de", 2);
				break;
			}
		}
	}
	free(lang);
	free(json);

	struct passwd *pw = getpwuid(getuid());
	if (pw) {
		char *gecos = pw->pw_gecos ? strdup(pw->pw_gecos) : NULL;
		if (gecos) {
			char *comma = strchr(gecos, ',');
			if (comma)
				*comma = '\0';
		}
		lk.user_name = (gecos && *gecos) ? gecos : strdup(pw->pw_name);
		if (gecos && !*gecos)
			free(gecos);
		char face[4096];
		snprintf(face, sizeof(face), "%s/.face", pw->pw_dir);
		if (file_exists(face)) {
			lk.avatar_path = strdup(face);
		} else {
			snprintf(face, sizeof(face), "/var/lib/AccountsService/icons/%s", pw->pw_name);
			if (file_exists(face))
				lk.avatar_path = strdup(face);
		}
	} else {
		lk.user_name = strdup("");
	}
}

/* ------------------------------------------------------------------------ */
/* Drawing                                                                  */

static void set_hex(cairo_t *cr, const char *hex, double alpha)
{
	unsigned r = 0, g = 0, b = 0;
	if (sscanf(hex, "#%02x%02x%02x", &r, &g, &b) != 3)
		r = 0, g = 0x78, b = 0xd7;
	cairo_set_source_rgba(cr, r / 255.0, g / 255.0, b / 255.0, alpha);
}

static void draw_text(cairo_t *cr, const char *text, const char *font, double size_px,
		      double x, double y, int align /* 0 left, 1 center */, double *out_w, double *out_h)
{
	PangoLayout *layout = pango_cairo_create_layout(cr);
	PangoFontDescription *desc = pango_font_description_from_string(font);
	pango_font_description_set_absolute_size(desc, size_px * PANGO_SCALE);
	pango_layout_set_font_description(layout, desc);
	pango_layout_set_text(layout, text, -1);
	int w, h;
	pango_layout_get_pixel_size(layout, &w, &h);
	cairo_move_to(cr, align == 1 ? x - w / 2.0 : x, y);
	pango_cairo_show_layout(cr, layout);
	if (out_w)
		*out_w = w;
	if (out_h)
		*out_h = h;
	pango_font_description_free(desc);
	g_object_unref(layout);
}

/* Convert a GdkPixbuf to a cairo image surface (premultiplied ARGB32). */
static cairo_surface_t *pixbuf_surface(GdkPixbuf *pb)
{
	int w = gdk_pixbuf_get_width(pb), h = gdk_pixbuf_get_height(pb);
	int n = gdk_pixbuf_get_n_channels(pb), src_stride = gdk_pixbuf_get_rowstride(pb);
	bool alpha = gdk_pixbuf_get_has_alpha(pb);
	const guchar *src = gdk_pixbuf_read_pixels(pb);
	cairo_surface_t *surf = cairo_image_surface_create(alpha ? CAIRO_FORMAT_ARGB32 : CAIRO_FORMAT_RGB24, w, h);
	cairo_surface_flush(surf);
	unsigned char *dst = cairo_image_surface_get_data(surf);
	int dst_stride = cairo_image_surface_get_stride(surf);
	for (int y = 0; y < h; y++) {
		const guchar *s = src + y * src_stride;
		uint32_t *d = (uint32_t *)(dst + y * dst_stride);
		for (int x = 0; x < w; x++, s += n) {
			uint32_t a = alpha ? s[3] : 255;
			uint32_t r = s[0] * a / 255, g = s[1] * a / 255, b = s[2] * a / 255;
			d[x] = (a << 24) | (r << 16) | (g << 8) | b;
		}
	}
	cairo_surface_mark_dirty(surf);
	return surf;
}

static cairo_surface_t *image_surf, *avatar_surf;

static void ensure_image(void)
{
	if (lk.image)
		return;
	GError *err = NULL;
	int w = 0, h = 0;
	GdkPixbufFormat *fmt = gdk_pixbuf_get_file_info(lk.image_path, &w, &h);
	if (fmt && w > 0 && h > 0) {
		/* Render vector images large enough for a 4K output. */
		double f = fmax(3840.0 / w, 2160.0 / h);
		bool scalable = gdk_pixbuf_format_is_scalable(fmt);
		if (scalable)
			lk.image = gdk_pixbuf_new_from_file_at_scale(lk.image_path, (int)(w * f), (int)(h * f), TRUE, &err);
		else
			lk.image = gdk_pixbuf_new_from_file(lk.image_path, &err);
	}
	if (err) {
		fprintf(stderr, "tenwin-lock: %s\n", err->message);
		g_error_free(err);
	}
	if (lk.image)
		image_surf = pixbuf_surface(lk.image);
	if (lk.avatar_path && !lk.avatar) {
		lk.avatar = gdk_pixbuf_new_from_file_at_scale(lk.avatar_path, 384, 384, TRUE, NULL);
		if (lk.avatar)
			avatar_surf = pixbuf_surface(lk.avatar);
	}
}

static cairo_surface_t *make_background(uint32_t w, uint32_t h, bool blur)
{
	cairo_surface_t *surf = cairo_image_surface_create(CAIRO_FORMAT_RGB24, w, h);
	cairo_t *cr = cairo_create(surf);
	cairo_set_source_rgb(cr, 0.0, 0.25, 0.55);
	cairo_paint(cr);
	if (image_surf) {
		int iw = gdk_pixbuf_get_width(lk.image), ih = gdk_pixbuf_get_height(lk.image);
		double f = fmax((double)w / iw, (double)h / ih);
		if (blur) {
			/* Blur by repeated down- and upscaling with bilinear filtering. */
			int levels[] = { 4, 12, 36 };
			cairo_surface_t *prev = NULL;
			int pw = 0, ph = 0;
			for (int i = 0; i < 3; i++) {
				int sw = (int)fmax(1, w / levels[i]), sh = (int)fmax(1, h / levels[i]);
				cairo_surface_t *small = cairo_image_surface_create(CAIRO_FORMAT_RGB24, sw, sh);
				cairo_t *sc = cairo_create(small);
				if (!prev) {
					double sf = fmax((double)sw / iw, (double)sh / ih);
					cairo_translate(sc, (sw - iw * sf) / 2, (sh - ih * sf) / 2);
					cairo_scale(sc, sf, sf);
					cairo_set_source_surface(sc, image_surf, 0, 0);
				} else {
					cairo_scale(sc, (double)sw / pw, (double)sh / ph);
					cairo_set_source_surface(sc, prev, 0, 0);
				}
				cairo_pattern_set_filter(cairo_get_source(sc), CAIRO_FILTER_GOOD);
				cairo_paint(sc);
				cairo_destroy(sc);
				if (prev)
					cairo_surface_destroy(prev);
				prev = small;
				pw = sw;
				ph = sh;
			}
			for (int i = 1; i >= 0; i--) {
				int sw = (int)fmax(1, w / levels[i]), sh = (int)fmax(1, h / levels[i]);
				cairo_surface_t *up = cairo_image_surface_create(CAIRO_FORMAT_RGB24, sw, sh);
				cairo_t *uc = cairo_create(up);
				cairo_scale(uc, (double)sw / pw, (double)sh / ph);
				cairo_set_source_surface(uc, prev, 0, 0);
				cairo_pattern_set_filter(cairo_get_source(uc), CAIRO_FILTER_BILINEAR);
				cairo_pattern_set_extend(cairo_get_source(uc), CAIRO_EXTEND_PAD);
				cairo_paint(uc);
				cairo_destroy(uc);
				cairo_surface_destroy(prev);
				prev = up;
				pw = sw;
				ph = sh;
			}
			cairo_save(cr);
			cairo_scale(cr, (double)w / pw, (double)h / ph);
			cairo_set_source_surface(cr, prev, 0, 0);
			cairo_pattern_set_filter(cairo_get_source(cr), CAIRO_FILTER_BILINEAR);
			cairo_pattern_set_extend(cairo_get_source(cr), CAIRO_EXTEND_PAD);
			cairo_paint(cr);
			cairo_restore(cr);
			cairo_surface_destroy(prev);
			cairo_set_source_rgba(cr, 0, 0, 0, 0.25);
			cairo_paint(cr);
		} else {
			cairo_save(cr);
			cairo_translate(cr, (w - iw * f) / 2, (h - ih * f) / 2);
			cairo_scale(cr, f, f);
			cairo_set_source_surface(cr, image_surf, 0, 0);
			cairo_pattern_set_filter(cairo_get_source(cr), CAIRO_FILTER_GOOD);
			cairo_paint(cr);
			cairo_restore(cr);
		}
	}
	cairo_destroy(cr);
	return surf;
}

static void draw_avatar(cairo_t *cr, double cx, double cy, double r)
{
	cairo_save(cr);
	cairo_arc(cr, cx, cy, r, 0, 2 * M_PI);
	cairo_clip(cr);
	if (avatar_surf) {
		int aw = gdk_pixbuf_get_width(lk.avatar), ah = gdk_pixbuf_get_height(lk.avatar);
		double f = fmax(2 * r / aw, 2 * r / ah);
		cairo_translate(cr, cx - aw * f / 2, cy - ah * f / 2);
		cairo_scale(cr, f, f);
		cairo_set_source_surface(cr, avatar_surf, 0, 0);
		cairo_paint(cr);
	} else {
		cairo_set_source_rgb(cr, 0.80, 0.80, 0.80);
		cairo_paint(cr);
		cairo_set_source_rgb(cr, 1, 1, 1);
		cairo_arc(cr, cx, cy - r * 0.18, r * 0.36, 0, 2 * M_PI);
		cairo_fill(cr);
		cairo_arc(cr, cx, cy + r * 0.95, r * 0.75, M_PI, 2 * M_PI);
		cairo_fill(cr);
	}
	cairo_restore(cr);
}

static void format_clock(char *time_buf, size_t tlen, char *date_buf, size_t dlen)
{
	time_t now = time(NULL);
	struct tm tm;
	localtime_r(&now, &tm);
	if (lk.clock_24h) {
		strftime(time_buf, tlen, "%H:%M", &tm);
	} else {
		strftime(time_buf, tlen, "%I:%M", &tm);
		if (time_buf[0] == '0')
			memmove(time_buf, time_buf + 1, strlen(time_buf));
	}
	if (date_buf)
		strftime(date_buf, dlen, lk.german ? "%A, %e. %B" : "%A, %B %e", &tm);
	if (date_buf) {
		/* "%e" pads single digits with a space. */
		char *dbl;
		while ((dbl = strstr(date_buf, "  ")))
			memmove(dbl, dbl + 1, strlen(dbl));
	}
}

/* Geometry of the submit arrow / OK button in surface coordinates. */
static void login_geometry(struct output *o, double *box_x, double *box_y, double *box_w, double *box_h)
{
	double cy = o->height / 2.0;
	*box_w = 296;
	*box_h = 32;
	*box_x = o->width / 2.0 - *box_w / 2;
	*box_y = cy + 76;
}

static void draw(struct output *o, cairo_t *cr)
{
	double W = o->width, H = o->height;
	char tbuf[32], dbuf[128];
	format_clock(tbuf, sizeof(tbuf), dbuf, sizeof(dbuf));

	cairo_save(cr);
	cairo_scale(cr, 1.0 / o->scale, 1.0 / o->scale);
	cairo_set_source_surface(cr, lk.state == ST_CURTAIN ? o->bg : o->bg_blur, 0, 0);
	cairo_paint(cr);
	cairo_restore(cr);

	if (lk.state == ST_CURTAIN) {
		double time_px = fmax(64, H * 0.118), date_px = fmax(22, H * 0.036);
		double left = fmax(24, H * 0.045);
		double th, dh;
		/* Measure first, then draw bottom-aligned. */
		PangoLayout *probe = pango_cairo_create_layout(cr);
		PangoFontDescription *desc = pango_font_description_from_string(FONT " Light");
		pango_font_description_set_absolute_size(desc, time_px * PANGO_SCALE);
		pango_layout_set_font_description(probe, desc);
		pango_layout_set_text(probe, tbuf, -1);
		int tw_i, th_i;
		pango_layout_get_pixel_size(probe, &tw_i, &th_i);
		pango_font_description_free(desc);
		g_object_unref(probe);
		th = th_i;
		dh = date_px * 1.4;
		double y = H - H * 0.09 - dh - th;
		cairo_set_source_rgba(cr, 0, 0, 0, 0.25);
		draw_text(cr, tbuf, FONT " Light", time_px, left + 1, y + 1, 0, NULL, NULL);
		draw_text(cr, dbuf, FONT, date_px, left + 1, y + th + 1, 0, NULL, NULL);
		cairo_set_source_rgb(cr, 1, 1, 1);
		draw_text(cr, tbuf, FONT " Light", time_px, left, y, 0, NULL, NULL);
		draw_text(cr, dbuf, FONT, date_px, left, y + th, 0, NULL, NULL);
		return;
	}

	double cx = W / 2, cy = H / 2;
	draw_avatar(cr, cx, cy - 110, 96);
	cairo_set_source_rgb(cr, 1, 1, 1);
	draw_text(cr, lk.user_name, FONT " Light", 34, cx, cy + 4, 1, NULL, NULL);

	double bx, by, bw, bh;
	login_geometry(o, &bx, &by, &bw, &bh);

	if (lk.state == ST_LOGIN) {
		/* Password box */
		cairo_set_source_rgba(cr, 1, 1, 1, 0.9);
		cairo_rectangle(cr, bx, by, bw, bh);
		cairo_fill(cr);
		set_hex(cr, lk.accent, 1);
		cairo_set_line_width(cr, 2);
		cairo_rectangle(cr, bx + 1, by + 1, bw - 2, bh - 2);
		cairo_stroke(cr);
		/* Submit arrow button */
		double ax = bx + bw - bh;
		cairo_set_source_rgba(cr, 0, 0, 0, 0.12);
		cairo_rectangle(cr, ax, by + 2, bh - 2, bh - 4);
		cairo_fill(cr);
		cairo_set_source_rgb(cr, 0.2, 0.2, 0.2);
		cairo_set_line_width(cr, 1.5);
		cairo_move_to(cr, ax + 9, by + bh / 2);
		cairo_line_to(cr, ax + bh - 11, by + bh / 2);
		cairo_move_to(cr, ax + bh - 16, by + bh / 2 - 5);
		cairo_line_to(cr, ax + bh - 11, by + bh / 2);
		cairo_line_to(cr, ax + bh - 16, by + bh / 2 + 5);
		cairo_stroke(cr);
		if (lk.pw_len == 0) {
			cairo_set_source_rgb(cr, 0.45, 0.45, 0.45);
			draw_text(cr, tr("Password"), FONT, 15, bx + 10, by + 6, 0, NULL, NULL);
		} else {
			/* One dot per character (count UTF-8 lead bytes). */
			size_t chars = 0;
			for (size_t i = 0; i < lk.pw_len; i++)
				if ((lk.password[i] & 0xC0) != 0x80)
					chars++;
			cairo_set_source_rgb(cr, 0.1, 0.1, 0.1);
			double dx = bx + 14;
			for (size_t i = 0; i < chars && dx < ax - 8; i++, dx += 11) {
				cairo_arc(cr, dx, by + bh / 2, 3.2, 0, 2 * M_PI);
				cairo_fill(cr);
			}
		}
	} else if (lk.state == ST_CHECKING) {
		cairo_set_source_rgb(cr, 1, 1, 1);
		draw_text(cr, tr("Welcome"), FONT " Light", 22, cx, by, 1, NULL, NULL);
		/* Spinner dots */
		double t = (double)(now_ms() % 1000) / 1000.0;
		for (int i = 0; i < 5; i++) {
			double a = 2 * M_PI * (t + i * 0.08);
			cairo_arc(cr, cx + 16 * cos(a), by + 60 + 16 * sin(a), 2.2, 0, 2 * M_PI);
			cairo_fill(cr);
		}
	} else if (lk.state == ST_ERROR) {
		cairo_set_source_rgb(cr, 1, 1, 1);
		draw_text(cr, tr("The password is incorrect. Try again."), FONT, 15, cx, by, 1, NULL, NULL);
		double okw = 112, okh = 32, okx = cx - okw / 2, oky = by + 40;
		cairo_set_source_rgba(cr, 1, 1, 1, 0.25);
		cairo_rectangle(cr, okx, oky, okw, okh);
		cairo_fill(cr);
		cairo_set_source_rgba(cr, 1, 1, 1, 0.6);
		cairo_set_line_width(cr, 2);
		cairo_rectangle(cr, okx + 1, oky + 1, okw - 2, okh - 2);
		cairo_stroke(cr);
		cairo_set_source_rgb(cr, 1, 1, 1);
		draw_text(cr, tr("OK"), FONT, 15, cx, oky + 6, 1, NULL, NULL);
	}
}

/* ------------------------------------------------------------------------ */
/* Buffers                                                                  */

static void buffer_release(void *data, struct wl_buffer *wl_buffer)
{
	struct buffer *b = data;
	wl_buffer_destroy(b->wl_buffer);
	munmap(b->data, b->size);
	free(b);
}

static const struct wl_buffer_listener buffer_listener = { .release = buffer_release };

static void render(struct output *o)
{
	if (!o->configured || !o->width || !o->height)
		return;
	uint32_t bw = o->width * o->scale, bh = o->height * o->scale;
	if (!o->bg || o->bg_w != bw || o->bg_h != bh) {
		ensure_image();
		if (o->bg)
			cairo_surface_destroy(o->bg);
		if (o->bg_blur)
			cairo_surface_destroy(o->bg_blur);
		o->bg = make_background(bw, bh, false);
		o->bg_blur = make_background(bw, bh, true);
		o->bg_w = bw;
		o->bg_h = bh;
	}
	int stride = cairo_format_stride_for_width(CAIRO_FORMAT_ARGB32, bw);
	size_t size = (size_t)stride * bh;
	int fd = memfd_create("tenwin-lock", MFD_CLOEXEC);
	if (fd < 0 || ftruncate(fd, size) < 0) {
		if (fd >= 0)
			close(fd);
		return;
	}
	void *data = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
	if (data == MAP_FAILED) {
		close(fd);
		return;
	}
	struct wl_shm_pool *pool = wl_shm_create_pool(lk.shm, fd, size);
	struct buffer *b = calloc(1, sizeof(*b));
	b->wl_buffer = wl_shm_pool_create_buffer(pool, 0, bw, bh, stride, WL_SHM_FORMAT_ARGB8888);
	b->data = data;
	b->size = size;
	wl_buffer_add_listener(b->wl_buffer, &buffer_listener, b);
	wl_shm_pool_destroy(pool);
	close(fd);

	cairo_surface_t *surf = cairo_image_surface_create_for_data(data, CAIRO_FORMAT_ARGB32, bw, bh, stride);
	cairo_t *cr = cairo_create(surf);
	cairo_scale(cr, o->scale, o->scale);
	draw(o, cr);
	cairo_destroy(cr);
	cairo_surface_destroy(surf);

	wl_surface_set_buffer_scale(o->surface, o->scale);
	wl_surface_attach(o->surface, b->wl_buffer, 0, 0);
	wl_surface_damage_buffer(o->surface, 0, 0, bw, bh);
	wl_surface_commit(o->surface);
}

static void render_all(void)
{
	struct output *o;
	wl_list_for_each(o, &lk.outputs, link)
		render(o);
}

/* ------------------------------------------------------------------------ */
/* Lock surfaces                                                            */

static void lock_surface_configure(void *data, struct ext_session_lock_surface_v1 *surface,
				   uint32_t serial, uint32_t width, uint32_t height)
{
	struct output *o = data;
	o->width = width;
	o->height = height;
	o->configured = true;
	ext_session_lock_surface_v1_ack_configure(surface, serial);
	render(o);
}

static const struct ext_session_lock_surface_v1_listener lock_surface_listener = {
	.configure = lock_surface_configure,
};

static void create_lock_surface(struct output *o)
{
	if (!lk.lock || o->lock_surface)
		return;
	o->surface = wl_compositor_create_surface(lk.compositor);
	o->lock_surface = ext_session_lock_v1_get_lock_surface(lk.lock, o->surface, o->wl_output);
	ext_session_lock_surface_v1_add_listener(o->lock_surface, &lock_surface_listener, o);
}

static void lock_locked(void *data, struct ext_session_lock_v1 *lock)
{
	lk.locked = true;
}

static void lock_finished(void *data, struct ext_session_lock_v1 *lock)
{
	lk.finished = true;
	lk.running = false;
}

static const struct ext_session_lock_v1_listener lock_listener = {
	.locked = lock_locked,
	.finished = lock_finished,
};

/* ------------------------------------------------------------------------ */
/* Outputs                                                                  */

static void output_geometry(void *d, struct wl_output *o, int32_t x, int32_t y, int32_t pw, int32_t ph,
			    int32_t sp, const char *make, const char *model, int32_t transform) {}
static void output_mode(void *d, struct wl_output *o, uint32_t f, int32_t w, int32_t h, int32_t r) {}
static void output_done(void *d, struct wl_output *o) {}
static void output_scale(void *data, struct wl_output *wl_output, int32_t factor)
{
	struct output *o = data;
	o->scale = factor > 0 ? factor : 1;
	render(o);
}

static const struct wl_output_listener output_listener = {
	.geometry = output_geometry,
	.mode = output_mode,
	.done = output_done,
	.scale = output_scale,
};

/* ------------------------------------------------------------------------ */
/* Authentication                                                           */

static int pam_conv_cb(int num_msg, const struct pam_message **msg, struct pam_response **resp,
		       void *appdata)
{
	const char *password = appdata;
	struct pam_response *replies = calloc(num_msg, sizeof(*replies));
	if (!replies)
		return PAM_BUF_ERR;
	for (int i = 0; i < num_msg; i++) {
		if (msg[i]->msg_style == PAM_PROMPT_ECHO_OFF || msg[i]->msg_style == PAM_PROMPT_ECHO_ON) {
			replies[i].resp = strdup(password);
			if (!replies[i].resp) {
				for (int j = 0; j < i; j++)
					free(replies[j].resp);
				free(replies);
				return PAM_BUF_ERR;
			}
		}
	}
	*resp = replies;
	return PAM_SUCCESS;
}

static bool pam_check(const char *password)
{
	struct passwd *pw = getpwuid(getuid());
	if (!pw)
		return false;
	struct pam_conv conv = { pam_conv_cb, (void *)password };
	pam_handle_t *handle = NULL;
	if (pam_start("tenwin-lock", pw->pw_name, &conv, &handle) != PAM_SUCCESS)
		return false;
	int ret = pam_authenticate(handle, 0);
	if (ret == PAM_SUCCESS)
		ret = pam_acct_mgmt(handle, 0);
	pam_setcred(handle, PAM_REFRESH_CRED);
	pam_end(handle, ret);
	return ret == PAM_SUCCESS;
}

static void clear_password(void)
{
	explicit_bzero(lk.password, sizeof(lk.password));
	lk.pw_len = 0;
}

static void submit(void)
{
	if (lk.auth_pid > 0)
		return;
	int fds[2];
	if (pipe2(fds, O_CLOEXEC) < 0)
		return;
	pid_t pid = fork();
	if (pid < 0) {
		close(fds[0]);
		close(fds[1]);
		return;
	}
	if (pid == 0) {
		close(fds[0]);
		char ok = pam_check(lk.password) ? 1 : 0;
		explicit_bzero(lk.password, sizeof(lk.password));
		if (write(fds[1], &ok, 1) != 1)
			_exit(2);
		_exit(0);
	}
	close(fds[1]);
	clear_password();
	lk.auth_pid = pid;
	lk.auth_fd = fds[0];
	lk.state = ST_CHECKING;
	render_all();
}

static void auth_result(void)
{
	char ok = 0;
	if (read(lk.auth_fd, &ok, 1) != 1)
		ok = 0;
	close(lk.auth_fd);
	lk.auth_fd = -1;
	waitpid(lk.auth_pid, NULL, 0);
	lk.auth_pid = 0;
	if (ok) {
		ext_session_lock_v1_unlock_and_destroy(lk.lock);
		lk.lock = NULL;
		wl_display_roundtrip(lk.display);
		lk.running = false;
	} else {
		lk.state = ST_ERROR;
		render_all();
	}
}

/* ------------------------------------------------------------------------ */
/* Input                                                                    */

static long long now_ms(void)
{
	struct timespec ts;
	clock_gettime(CLOCK_MONOTONIC, &ts);
	return (long long)ts.tv_sec * 1000 + ts.tv_nsec / 1000000;
}

static void handle_keysym(xkb_keysym_t sym, uint32_t keycode)
{
	switch (lk.state) {
	case ST_CHECKING:
		return;
	case ST_ERROR:
		if (sym == XKB_KEY_Return || sym == XKB_KEY_KP_Enter || sym == XKB_KEY_Escape ||
		    sym == XKB_KEY_space) {
			lk.state = ST_LOGIN;
			render_all();
		}
		return;
	case ST_CURTAIN:
		lk.state = ST_LOGIN;
		if (sym == XKB_KEY_Escape || sym == XKB_KEY_Return || sym == XKB_KEY_KP_Enter ||
		    sym == XKB_KEY_space) {
			render_all();
			return;
		}
		break; /* fall through: type the character into the password box */
	case ST_LOGIN:
		break;
	}

	switch (sym) {
	case XKB_KEY_Return:
	case XKB_KEY_KP_Enter:
		if (lk.pw_len > 0)
			submit();
		return;
	case XKB_KEY_Escape:
		clear_password();
		lk.state = ST_CURTAIN;
		break;
	case XKB_KEY_BackSpace:
		while (lk.pw_len > 0) {
			lk.pw_len--;
			bool lead = (lk.password[lk.pw_len] & 0xC0) != 0x80;
			lk.password[lk.pw_len] = '\0';
			if (lead)
				break;
		}
		break;
	default: {
		char buf[16];
		int n = xkb_state_key_get_utf8(lk.xkb_state, keycode, buf, sizeof(buf));
		if (n > 0 && (unsigned char)buf[0] >= 0x20 && buf[0] != 0x7f && lk.pw_len + n < PW_MAX - 1) {
			memcpy(lk.password + lk.pw_len, buf, n);
			lk.pw_len += n;
			lk.password[lk.pw_len] = '\0';
		}
		explicit_bzero(buf, sizeof(buf));
	}
	}
	render_all();
}

static void kb_keymap(void *data, struct wl_keyboard *kb, uint32_t format, int32_t fd, uint32_t size)
{
	if (format != WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1) {
		close(fd);
		return;
	}
	char *map = mmap(NULL, size, PROT_READ, MAP_PRIVATE, fd, 0);
	close(fd);
	if (map == MAP_FAILED)
		return;
	struct xkb_keymap *keymap = xkb_keymap_new_from_string(lk.xkb_context, map, XKB_KEYMAP_FORMAT_TEXT_V1,
							       XKB_KEYMAP_COMPILE_NO_FLAGS);
	munmap(map, size);
	if (!keymap)
		return;
	xkb_state_unref(lk.xkb_state);
	xkb_keymap_unref(lk.xkb_keymap);
	lk.xkb_keymap = keymap;
	lk.xkb_state = xkb_state_new(keymap);
}

static void kb_enter(void *d, struct wl_keyboard *kb, uint32_t serial, struct wl_surface *s, struct wl_array *keys) {}
static void kb_leave(void *d, struct wl_keyboard *kb, uint32_t serial, struct wl_surface *s)
{
	lk.repeat_key = 0;
}

static void kb_key(void *data, struct wl_keyboard *kb, uint32_t serial, uint32_t time, uint32_t key, uint32_t state)
{
	if (!lk.xkb_state)
		return;
	uint32_t keycode = key + 8;
	if (state == WL_KEYBOARD_KEY_STATE_PRESSED) {
		xkb_keysym_t sym = xkb_state_key_get_one_sym(lk.xkb_state, keycode);
		handle_keysym(sym, keycode);
		if (lk.repeat_rate > 0 && xkb_keymap_key_repeats(lk.xkb_keymap, keycode)) {
			lk.repeat_key = keycode;
			lk.repeat_next_ms = now_ms() + lk.repeat_delay;
		}
	} else if (keycode == lk.repeat_key) {
		lk.repeat_key = 0;
	}
}

static void kb_modifiers(void *data, struct wl_keyboard *kb, uint32_t serial, uint32_t depressed,
			 uint32_t latched, uint32_t locked, uint32_t group)
{
	if (lk.xkb_state)
		xkb_state_update_mask(lk.xkb_state, depressed, latched, locked, 0, 0, group);
}

static void kb_repeat_info(void *data, struct wl_keyboard *kb, int32_t rate, int32_t delay)
{
	lk.repeat_rate = rate;
	lk.repeat_delay = delay;
}

static const struct wl_keyboard_listener keyboard_listener = {
	.keymap = kb_keymap,
	.enter = kb_enter,
	.leave = kb_leave,
	.key = kb_key,
	.modifiers = kb_modifiers,
	.repeat_info = kb_repeat_info,
};

static void ptr_enter(void *data, struct wl_pointer *p, uint32_t serial, struct wl_surface *surface,
		      wl_fixed_t x, wl_fixed_t y)
{
	struct output *o;
	wl_pointer_set_cursor(p, serial, NULL, 0, 0); /* hide the cursor like Windows does */
	wl_list_for_each(o, &lk.outputs, link) {
		if (o->surface == surface)
			lk.pointer_output = o;
	}
	lk.pointer_x = wl_fixed_to_double(x);
	lk.pointer_y = wl_fixed_to_double(y);
}

static void ptr_leave(void *d, struct wl_pointer *p, uint32_t serial, struct wl_surface *s) {}

static void ptr_motion(void *data, struct wl_pointer *p, uint32_t time, wl_fixed_t x, wl_fixed_t y)
{
	lk.pointer_x = wl_fixed_to_double(x);
	lk.pointer_y = wl_fixed_to_double(y);
}

static void ptr_button(void *data, struct wl_pointer *p, uint32_t serial, uint32_t time, uint32_t button,
		       uint32_t state)
{
	if (state != WL_POINTER_BUTTON_STATE_PRESSED)
		return;
	if (lk.state == ST_CURTAIN || lk.state == ST_ERROR) {
		lk.state = ST_LOGIN;
		render_all();
		return;
	}
	if (lk.state == ST_LOGIN && lk.pointer_output && lk.pw_len > 0) {
		double bx, by, bw, bh;
		login_geometry(lk.pointer_output, &bx, &by, &bw, &bh);
		double ax = bx + bw - bh;
		if (lk.pointer_x >= ax && lk.pointer_x <= bx + bw && lk.pointer_y >= by && lk.pointer_y <= by + bh)
			submit();
	}
}

static void ptr_axis(void *d, struct wl_pointer *p, uint32_t time, uint32_t axis, wl_fixed_t value) {}

static const struct wl_pointer_listener pointer_listener = {
	.enter = ptr_enter,
	.leave = ptr_leave,
	.motion = ptr_motion,
	.button = ptr_button,
	.axis = ptr_axis,
};

static void seat_capabilities(void *data, struct wl_seat *seat, uint32_t caps)
{
	if ((caps & WL_SEAT_CAPABILITY_KEYBOARD) && !lk.keyboard) {
		lk.keyboard = wl_seat_get_keyboard(seat);
		wl_keyboard_add_listener(lk.keyboard, &keyboard_listener, NULL);
	} else if (!(caps & WL_SEAT_CAPABILITY_KEYBOARD) && lk.keyboard) {
		wl_keyboard_release(lk.keyboard);
		lk.keyboard = NULL;
	}
	if ((caps & WL_SEAT_CAPABILITY_POINTER) && !lk.pointer) {
		lk.pointer = wl_seat_get_pointer(seat);
		wl_pointer_add_listener(lk.pointer, &pointer_listener, NULL);
	} else if (!(caps & WL_SEAT_CAPABILITY_POINTER) && lk.pointer) {
		wl_pointer_release(lk.pointer);
		lk.pointer = NULL;
	}
}

static void seat_name(void *data, struct wl_seat *seat, const char *name) {}

static const struct wl_seat_listener seat_listener = {
	.capabilities = seat_capabilities,
	.name = seat_name,
};

/* ------------------------------------------------------------------------ */
/* Registry                                                                 */

static void registry_global(void *data, struct wl_registry *registry, uint32_t name,
			    const char *interface, uint32_t version)
{
	if (!strcmp(interface, wl_compositor_interface.name)) {
		lk.compositor = wl_registry_bind(registry, name, &wl_compositor_interface, version < 4 ? version : 4);
	} else if (!strcmp(interface, wl_shm_interface.name)) {
		lk.shm = wl_registry_bind(registry, name, &wl_shm_interface, 1);
	} else if (!strcmp(interface, wl_seat_interface.name) && !lk.seat) {
		lk.seat = wl_registry_bind(registry, name, &wl_seat_interface, version < 5 ? version : 5);
		wl_seat_add_listener(lk.seat, &seat_listener, NULL);
	} else if (!strcmp(interface, ext_session_lock_manager_v1_interface.name)) {
		lk.lock_manager = wl_registry_bind(registry, name, &ext_session_lock_manager_v1_interface, 1);
	} else if (!strcmp(interface, wl_output_interface.name)) {
		struct output *o = calloc(1, sizeof(*o));
		if (!o)
			return;
		o->global_name = name;
		o->scale = 1;
		o->wl_output = wl_registry_bind(registry, name, &wl_output_interface, version < 3 ? version : 3);
		wl_output_add_listener(o->wl_output, &output_listener, o);
		wl_list_insert(&lk.outputs, &o->link);
		create_lock_surface(o);
	}
}

static void destroy_output(struct output *o)
{
	wl_list_remove(&o->link);
	if (o->lock_surface)
		ext_session_lock_surface_v1_destroy(o->lock_surface);
	if (o->surface)
		wl_surface_destroy(o->surface);
	if (o->bg)
		cairo_surface_destroy(o->bg);
	if (o->bg_blur)
		cairo_surface_destroy(o->bg_blur);
	if (lk.pointer_output == o)
		lk.pointer_output = NULL;
	wl_output_destroy(o->wl_output);
	free(o);
}

static void registry_global_remove(void *data, struct wl_registry *registry, uint32_t name)
{
	struct output *o, *tmp;
	wl_list_for_each_safe(o, tmp, &lk.outputs, link) {
		if (o->global_name == name)
			destroy_output(o);
	}
}

static const struct wl_registry_listener registry_listener = {
	.global = registry_global,
	.global_remove = registry_global_remove,
};

/* ------------------------------------------------------------------------ */

static int acquire_instance_lock(void)
{
	const char *runtime = getenv("XDG_RUNTIME_DIR");
	char path[4096];
	snprintf(path, sizeof(path), "%s/tenwin-lock.lock", runtime && *runtime ? runtime : "/tmp");
	int fd = open(path, O_RDWR | O_CREAT | O_CLOEXEC, 0600);
	if (fd < 0)
		return -1;
	if (flock(fd, LOCK_EX | LOCK_NB) < 0) {
		close(fd);
		return -2;
	}
	return fd;
}

static int next_timeout_ms(void)
{
	long long now = now_ms();
	struct timespec ts;
	clock_gettime(CLOCK_REALTIME, &ts);
	int to_second = 1000 - (int)(ts.tv_nsec / 1000000);
	int timeout = to_second;
	if (lk.state == ST_CHECKING)
		timeout = 50;
	if (lk.repeat_key) {
		long long d = lk.repeat_next_ms - now;
		if (d < timeout)
			timeout = d < 0 ? 0 : (int)d;
	}
	return timeout;
}

static void on_timeout(void)
{
	char tbuf[32];
	format_clock(tbuf, sizeof(tbuf), NULL, 0);
	if (lk.state == ST_CHECKING || (lk.state == ST_CURTAIN && strcmp(tbuf, lk.last_clock))) {
		snprintf(lk.last_clock, sizeof(lk.last_clock), "%s", tbuf);
		render_all();
	}
	if (lk.repeat_key && now_ms() >= lk.repeat_next_ms && lk.xkb_state) {
		xkb_keysym_t sym = xkb_state_key_get_one_sym(lk.xkb_state, lk.repeat_key);
		if (sym != XKB_KEY_Return && sym != XKB_KEY_KP_Enter && sym != XKB_KEY_Escape)
			handle_keysym(sym, lk.repeat_key);
		lk.repeat_next_ms = now_ms() + (lk.repeat_rate > 0 ? 1000 / lk.repeat_rate : 40);
	}
}

int main(int argc, char **argv)
{
	bool daemonize = false;
	for (int i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "--daemonize") || !strcmp(argv[i], "-f")) {
			daemonize = true;
		} else if (!strcmp(argv[i], "--image") && i + 1 < argc) {
			lk.image_path = strdup(argv[++i]);
		} else if (!strcmp(argv[i], "--state") && i + 1 < argc) {
			/* Debugging/screenshots only: start in another state. */
			const char *st = argv[++i];
			lk.state = !strcmp(st, "login") ? ST_LOGIN : !strcmp(st, "error") ? ST_ERROR : ST_CURTAIN;
		} else if (!strcmp(argv[i], "--help") || !strcmp(argv[i], "-h")) {
			printf("usage: tenwin-lock [--daemonize] [--image PATH]\n");
			return 0;
		}
	}
	setlocale(LC_ALL, "");
	signal(SIGPIPE, SIG_IGN);

	int instance = acquire_instance_lock();
	if (instance == -2)
		return 0; /* already locked */

	lk.auth_fd = -1;
	lk.repeat_rate = 25;
	lk.repeat_delay = 600;
	lk.running = true;
	wl_list_init(&lk.outputs);
	lk.xkb_context = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
	load_settings();

	lk.display = wl_display_connect(NULL);
	if (!lk.display) {
		fprintf(stderr, "tenwin-lock: cannot connect to Wayland display\n");
		return 1;
	}
	struct wl_registry *registry = wl_display_get_registry(lk.display);
	wl_registry_add_listener(registry, &registry_listener, NULL);
	wl_display_roundtrip(lk.display);
	if (!lk.compositor || !lk.shm || !lk.lock_manager) {
		fprintf(stderr, "tenwin-lock: compositor lacks ext-session-lock-v1\n");
		return 1;
	}

	lk.lock = ext_session_lock_manager_v1_lock(lk.lock_manager);
	ext_session_lock_v1_add_listener(lk.lock, &lock_listener, NULL);
	struct output *o;
	wl_list_for_each(o, &lk.outputs, link)
		create_lock_surface(o);

	while (!lk.locked && !lk.finished) {
		if (wl_display_dispatch(lk.display) < 0)
			break;
	}
	if (!lk.locked) {
		fprintf(stderr, "tenwin-lock: the compositor refused to lock the session\n");
		return 1;
	}

	if (daemonize) {
		pid_t pid = fork();
		if (pid < 0)
			return 1;
		if (pid > 0)
			_exit(0); /* parent: the session is locked now */
		setsid();
	}

	struct pollfd fds[2];
	while (lk.running) {
		while (wl_display_prepare_read(lk.display) != 0)
			wl_display_dispatch_pending(lk.display);
		wl_display_flush(lk.display);
		fds[0] = (struct pollfd){ .fd = wl_display_get_fd(lk.display), .events = POLLIN };
		fds[1] = (struct pollfd){ .fd = lk.auth_fd, .events = POLLIN };
		int n = poll(fds, lk.auth_fd >= 0 ? 2 : 1, next_timeout_ms());
		if (n < 0) {
			wl_display_cancel_read(lk.display);
			if (errno == EINTR)
				continue;
			break;
		}
		if (fds[0].revents & POLLIN) {
			if (wl_display_read_events(lk.display) < 0)
				break;
		} else {
			wl_display_cancel_read(lk.display);
		}
		if (fds[0].revents & (POLLERR | POLLHUP))
			break;
		wl_display_dispatch_pending(lk.display);
		if (lk.auth_fd >= 0 && (fds[1].revents & (POLLIN | POLLHUP)))
			auth_result();
		if (n == 0)
			on_timeout();
	}
	clear_password();
	wl_display_flush(lk.display);
	wl_display_disconnect(lk.display);
	if (instance >= 0)
		close(instance);
	return 0;
}
