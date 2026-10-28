"""tenwin-taskmgr: the Windows 10 Task Manager (Ctrl+Shift+Esc)."""

import logging
import os
import pwd
import signal
import sys
from collections import deque

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from tenwin import autostart, theme
from tenwin.apps import get_registry
from tenwin.config import get_settings
from tenwin.gtkutil import add_class, clear_children, flat_button, human_size
from tenwin.i18n import N_, _
from tenwin.taskmgr import procstat

log = logging.getLogger("tenwin.taskmgr")

INTERVAL = 1000   # ms ("Normal" update speed)
HISTORY = 60      # graph points
HEAT = ["#fff4c4", "#ffe9a3", "#ffd970", "#ffc83d", "#ff9f2b"]  # Windows-like cell shades

STATE_NAMES = {"R": N_("Running"), "S": N_("Running"), "D": N_("Waiting"), "Z": N_("Zombie"),
               "T": N_("Suspended"), "t": N_("Suspended"), "I": N_("Running")}

COL_NAME, COL_ICON, COL_CPU, COL_MEM, COL_DISK, COL_CPU_V, COL_MEM_V, COL_DISK_V, COL_KEY, COL_PIDS = range(10)


def heat(value, high):
    """Cell colour for a value (0..high)."""
    if high <= 0 or value <= 0:
        return HEAT[0]
    return HEAT[min(len(HEAT) - 1, int(len(HEAT) * value / high))]


def rate_text(bytes_per_s):
    return _("%s/s") % human_size(bytes_per_s) if bytes_per_s >= 1 else _("0 MB/s")


def memory_text(value):
    return human_size(value) if value >= 1024 * 1024 else "0 MB"


def percent_text(value):
    return "%.1f %%" % value if value >= 0.05 else "0 %"


class Graph(Gtk.DrawingArea):
    """Line graph with grid, like the Performance tab."""

    def __init__(self, color, maximum=100.0, small=False):
        super().__init__()
        self.color = Gdk.RGBA()
        self.color.parse(color)
        self.maximum = maximum
        self.values = deque([0.0] * HISTORY, maxlen=HISTORY)
        self.small = small
        self.set_size_request(64 if small else 400, 40 if small else 260)
        self.connect("draw", self._draw)

    def push(self, value, maximum=None):
        if maximum is not None:
            self.maximum = maximum
        self.values.append(value)
        self.queue_draw()

    def _draw(self, _widget, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        c = self.color
        cr.set_source_rgb(1, 1, 1)
        cr.paint()
        cr.set_line_width(1)
        if not self.small:
            cr.set_source_rgba(c.red, c.green, c.blue, 0.18)
            for i in range(1, 10):
                cr.move_to(0, int(h * i / 10) + 0.5)
                cr.line_to(w, int(h * i / 10) + 0.5)
            for i in range(1, 20):
                cr.move_to(int(w * i / 20) + 0.5, 0)
                cr.line_to(int(w * i / 20) + 0.5, h)
            cr.stroke()
        maximum = self.maximum or 1.0
        step = w / (HISTORY - 1)
        points = [(i * step, h - min(1.0, v / maximum) * (h - 1)) for i, v in enumerate(self.values)]
        cr.move_to(0, h)
        for x, y in points:
            cr.line_to(x, y)
        cr.line_to(w, h)
        cr.close_path()
        cr.set_source_rgba(c.red, c.green, c.blue, 0.12)
        cr.fill()
        cr.move_to(*points[0])
        for x, y in points[1:]:
            cr.line_to(x, y)
        cr.set_source_rgb(c.red, c.green, c.blue)
        cr.stroke()
        cr.rectangle(0.5, 0.5, w - 1, h - 1)
        cr.set_source_rgba(c.red, c.green, c.blue, 0.8)
        cr.stroke()
        return False


class TaskManager(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=_("Task Manager"))
        add_class(self, "tw-app-window", "tw-taskmgr")
        self.set_icon_name("org.tenwin.TaskManager")
        self.settings = get_settings()
        self.apps = get_registry()
        self.sampler = procstat.Sampler()
        self.windows = None
        self._start_windows()
        self.groups = []
        self.background = []
        self.selected_key = None
        self.expanded = set()

        self.stack = Gtk.Stack()
        self.add(self.stack)
        self.stack.add_named(self._build_simple(), "simple")
        self.stack.add_named(self._build_full(), "full")
        self.connect("key-press-event", self._on_key)
        self.show_all()
        self._apply_mode()
        self._refresh()
        GLib.timeout_add(INTERVAL, self._refresh)

    def _start_windows(self):
        try:
            from tenwin.shell.windows import WindowManager
            self.windows = WindowManager()
        except Exception as exc:  # no compositor support: everything is a background process
            log.info("no window list: %s", exc)

    # -- fewer details ---------------------------------------------------------------

    def _build_simple(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.simple_store = Gtk.ListStore(str, Gio.Icon, str)
        self.simple_view = Gtk.TreeView(model=self.simple_store, headers_visible=False)
        add_class(self.simple_view, "tw-taskmgr-list")
        col = Gtk.TreeViewColumn()
        icon = Gtk.CellRendererPixbuf(stock_size=Gtk.IconSize.LARGE_TOOLBAR)
        col.pack_start(icon, False)
        col.add_attribute(icon, "gicon", 1)
        text = Gtk.CellRendererText(ypad=6)
        col.pack_start(text, True)
        col.add_attribute(text, "text", 0)
        self.simple_view.append_column(col)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.simple_view)
        box.pack_start(scroll, True, True, 0)
        bar = add_class(Gtk.Box(), "tw-taskmgr-bar")
        more = flat_button(Gtk.Label(label="⌄  " + _("More details")), "tw-link")
        more.connect("clicked", lambda *_: self.settings.set("taskmgr.more_details", True) or self._apply_mode())
        bar.pack_start(more, False, False, 0)
        end = Gtk.Button(label=_("End task"))
        end.connect("clicked", lambda *_: self._end_simple())
        bar.pack_end(end, False, False, 0)
        box.pack_start(bar, False, False, 0)
        return box

    def _end_simple(self):
        model, it = self.simple_view.get_selection().get_selected()
        if it is not None:
            self._end_key(model[it][2])

    # -- more details ----------------------------------------------------------------

    def _build_full(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.notebook = Gtk.Notebook()
        add_class(self.notebook, "tw-taskmgr-tabs")
        self.notebook.append_page(self._build_processes(), Gtk.Label(label=_("Processes")))
        self.notebook.append_page(self._build_performance(), Gtk.Label(label=_("Performance")))
        self.notebook.append_page(self._build_startup(), Gtk.Label(label=_("Startup")))
        self.notebook.append_page(self._build_details(), Gtk.Label(label=_("Details")))
        box.pack_start(self.notebook, True, True, 0)
        bar = add_class(Gtk.Box(), "tw-taskmgr-bar")
        fewer = flat_button(Gtk.Label(label="⌃  " + _("Fewer details")), "tw-link")
        fewer.connect("clicked", lambda *_: self.settings.set("taskmgr.more_details", False) or self._apply_mode())
        bar.pack_start(fewer, False, False, 0)
        self.end_button = Gtk.Button(label=_("End task"))
        self.end_button.connect("clicked", lambda *_: self._end_selected())
        bar.pack_end(self.end_button, False, False, 0)
        box.pack_start(bar, False, False, 0)
        return box

    def _apply_mode(self):
        full = self.settings["taskmgr.more_details"]
        self.stack.set_visible_child_name("full" if full else "simple")
        self.resize(760, 640) if full else self.resize(420, 400)

    def _column(self, view, title, text_col, value_col=None, high=None, expand=False, xalign=1.0):
        renderer = Gtk.CellRendererText(xalign=xalign)
        column = Gtk.TreeViewColumn(title, renderer, text=text_col)
        column.set_resizable(True)
        column.set_expand(expand)
        if value_col is not None:
            column.set_sort_column_id(value_col)

            def data(_col, cell, model, it, _data):
                key = model[it][COL_KEY]
                if key.startswith("section:"):
                    cell.set_property("cell-background-set", False)
                else:
                    cell.set_property("cell-background", heat(model[it][value_col], high()))
            column.set_cell_data_func(renderer, data)
        view.append_column(column)
        return column

    def _build_processes(self):
        self.store = Gtk.TreeStore(str, Gio.Icon, str, str, str, float, float, float, str, object)
        self.view = Gtk.TreeView(model=self.store)
        add_class(self.view, "tw-taskmgr-list")
        col = Gtk.TreeViewColumn(_("Name"))
        icon = Gtk.CellRendererPixbuf()
        col.pack_start(icon, False)
        col.add_attribute(icon, "gicon", COL_ICON)
        text = Gtk.CellRendererText(ellipsize=Pango.EllipsizeMode.END)
        col.pack_start(text, True)
        col.add_attribute(text, "text", COL_NAME)
        col.set_expand(True)
        col.set_resizable(True)
        col.set_cell_data_func(text, self._name_data)
        self.view.append_column(col)
        mem_total = lambda: float(self.sampler.memory.get("MemTotal", 1)) / 4  # noqa: E731
        self.cpu_column = self._column(self.view, _("CPU"), COL_CPU, COL_CPU_V, lambda: 50.0)
        self.mem_column = self._column(self.view, _("Memory"), COL_MEM, COL_MEM_V, mem_total)
        self.disk_column = self._column(self.view, _("Disk"), COL_DISK, COL_DISK_V, lambda: 20e6)
        self.view.get_selection().connect("changed", self._on_select)
        self.view.connect("row-expanded", lambda _v, it, _p: self.expanded.add(self.store[it][COL_KEY]))
        self.view.connect("row-collapsed", lambda _v, it, _p: self.expanded.discard(self.store[it][COL_KEY]))
        self.view.connect("button-press-event", self._on_process_click)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.view)
        return scroll

    def _name_data(self, _col, cell, model, it, _data):
        section = model[it][COL_KEY].startswith("section:")
        cell.set_property("weight", Pango.Weight.BOLD if section else Pango.Weight.NORMAL)

    def _build_performance(self):
        paned = Gtk.Box()
        self.perf_list = Gtk.ListBox()
        add_class(self.perf_list, "tw-taskmgr-perf-list")
        self.perf_list.set_size_request(220, -1)
        self.perf_list.connect("row-selected", lambda _l, row: row and self._show_perf(row.resource))
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroll.add(self.perf_list)
        paned.pack_start(scroll, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        for side in ("start", "end", "top", "bottom"):
            getattr(right, "set_margin_" + side)(16)
        head = Gtk.Box()
        self.perf_title = add_class(Gtk.Label(xalign=0), "tw-taskmgr-perf-title")
        self.perf_subtitle = add_class(Gtk.Label(xalign=1), "tw-dim")
        head.pack_start(self.perf_title, True, True, 0)
        head.pack_end(self.perf_subtitle, False, False, 0)
        right.pack_start(head, False, False, 0)
        self.perf_graph_box = Gtk.Box()
        right.pack_start(self.perf_graph_box, True, True, 0)
        self.perf_stats = Gtk.Grid(column_spacing=32, row_spacing=4)
        right.pack_start(self.perf_stats, False, False, 0)
        paned.pack_start(right, True, True, 0)
        self.resources = {}
        self.current_resource = None
        return paned

    def _resource(self, key, title, color, maximum=100.0):
        res = self.resources.get(key)
        if res is not None:
            return res
        row = Gtk.ListBoxRow()
        box = Gtk.Box(spacing=10)
        for side in ("start", "end", "top", "bottom"):
            getattr(box, "set_margin_" + side)(6)
        small = Graph(color, maximum, small=True)
        box.pack_start(small, False, False, 0)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        texts.pack_start(add_class(Gtk.Label(label=title, xalign=0), "tw-taskmgr-perf-name"), False, False, 0)
        summary = add_class(Gtk.Label(xalign=0), "tw-dim")
        texts.pack_start(summary, False, False, 0)
        box.pack_start(texts, True, True, 0)
        row.add(box)
        row.resource = key
        self.perf_list.add(row)
        row.show_all()
        res = {"title": title, "small": small, "big": Graph(color, maximum), "summary": summary,
               "stats": [], "subtitle": "", "row": row}
        self.resources[key] = res
        if self.current_resource is None:
            self.perf_list.select_row(row)
        return res

    def _show_perf(self, key):
        self.current_resource = key
        res = self.resources[key]
        self.perf_title.set_text(res["title"])
        self.perf_subtitle.set_text(res["subtitle"])
        clear_children(self.perf_graph_box)
        self.perf_graph_box.pack_start(res["big"], True, True, 0)
        self.perf_graph_box.show_all()
        self._show_stats(res)

    def _show_stats(self, res):
        clear_children(self.perf_stats)
        for i, (label, value) in enumerate(res["stats"]):
            self.perf_stats.attach(add_class(Gtk.Label(label=label, xalign=0), "tw-dim"), (i % 2) * 2, i // 2, 1, 1)
            self.perf_stats.attach(add_class(Gtk.Label(label=value, xalign=0), "tw-taskmgr-stat"),
                                   (i % 2) * 2 + 1, i // 2, 1, 1)
        self.perf_stats.show_all()

    def _build_startup(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.startup_store = Gtk.ListStore(str, str, str, str, bool)
        view = Gtk.TreeView(model=self.startup_store)
        add_class(view, "tw-taskmgr-list")
        for title, col in ((_("Name"), 0), (_("Status"), 1)):
            column = Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=col)
            column.set_expand(col == 0)
            column.set_resizable(True)
            view.append_column(column)
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        box.pack_start(scroll, True, True, 0)
        bar = Gtk.Box()
        button = Gtk.Button(label=_("Disable"))
        bar.pack_end(button, False, False, 6)
        box.pack_start(bar, False, False, 6)

        def selected(*_args):
            model, it = view.get_selection().get_selected()
            button.set_sensitive(it is not None)
            if it is not None:
                button.set_label(_("Disable") if model[it][4] else _("Enable"))

        def toggle(*_args):
            model, it = view.get_selection().get_selected()
            if it is None:
                return
            name, path, enabled = model[it][2], model[it][3], model[it][4]
            try:
                autostart.set_enabled(name, path, not enabled)
            except GLib.Error as exc:
                log.warning("cannot change %s: %s", name, exc)
            self._fill_startup()
            selected()

        view.get_selection().connect("changed", selected)
        button.connect("clicked", toggle)
        self._fill_startup()
        selected()
        return box

    def _fill_startup(self):
        self.startup_store.clear()
        for name, path, title, enabled in autostart.entries():
            self.startup_store.append([title, _("Enabled") if enabled else _("Disabled"), name, path, enabled])

    def _build_details(self):
        self.details_store = Gtk.ListStore(str, int, str, str, float, float, str)
        view = Gtk.TreeView(model=self.details_store)
        add_class(view, "tw-taskmgr-list")
        self.details_view = view
        for title, col, xalign in ((_("Name"), 0, 0.0), (_("PID"), 1, 1.0), (_("Status"), 2, 0.0),
                                   (_("User name"), 3, 0.0), (_("CPU"), 4, 1.0), (_("Memory"), 5, 1.0),
                                   (_("Command line"), 6, 0.0)):
            renderer = Gtk.CellRendererText(xalign=xalign, ellipsize=Pango.EllipsizeMode.END)
            column = Gtk.TreeViewColumn(title, renderer, text=col)
            column.set_sort_column_id(col)
            column.set_resizable(True)
            if col == 4:
                column.set_cell_data_func(renderer, lambda _c, cell, m, it, _d: cell.set_property(
                    "text", "%02d" % round(m[it][4])))
            elif col == 5:
                column.set_cell_data_func(renderer, lambda _c, cell, m, it, _d: cell.set_property(
                    "text", human_size(m[it][5])))
            column.set_expand(col == 6)
            view.append_column(column)
        self.details_store.set_sort_column_id(0, Gtk.SortType.ASCENDING)
        scroll = Gtk.ScrolledWindow()
        scroll.add(view)
        return scroll

    # -- refresh -------------------------------------------------------------------------

    def _window_apps(self):
        apps, seen = [], set()
        if self.windows is None:
            return apps
        for window in self.windows.list():
            if window.parent:
                continue
            info = self.apps.for_window(window.app_id)
            key = info.get_id() if info is not None else "window:" + (window.app_id or str(window.id))
            if key in seen:
                continue
            seen.add(key)
            name = info.get_display_name() if info is not None else (window.title or window.app_id)
            icon = info.get_icon() if info is not None else None
            exe = info.get_executable() if info is not None else None
            apps.append((key, name, icon, window.app_id, exe))
        return apps

    def _refresh(self):
        self.sampler.sample()
        self.groups, self.background = procstat.group_apps(self.sampler.processes, self._window_apps())
        self._fill_simple()
        if self.stack.get_visible_child_name() == "full":
            self._fill_processes()
            self._fill_performance()
            if self.notebook.get_current_page() == 3:
                self._fill_details()
        return GLib.SOURCE_CONTINUE

    def _fill_simple(self):
        model, it = self.simple_view.get_selection().get_selected()
        selected = model[it][2] if it is not None else None
        self.simple_store.clear()
        for key, name, icon, _members in self.groups:
            row = self.simple_store.append([name, icon or Gio.ThemedIcon.new("application-x-executable"), key])
            if key == selected:
                self.simple_view.get_selection().select_iter(row)

    def _fill_processes(self):
        generic = Gio.ThemedIcon.new("application-x-executable")
        totals = [0.0, 0.0, 0.0]

        def row_values(name, icon, procs, key):
            cpu = sum(p.cpu for p in procs)
            mem = float(sum(p.rss for p in procs))
            disk = sum(p.disk_rate for p in procs)
            totals[0] += cpu
            totals[1] += mem
            totals[2] += disk
            return [name, icon, percent_text(cpu), memory_text(mem), rate_text(disk), cpu, mem, disk, key,
                    [p.pid for p in procs]]

        self.store.clear()
        selection_iter = None
        apps_head = self.store.append(None, [_("Apps (%d)") % len(self.groups), None, "", "", "", 0, 0, 0,
                                             "section:apps", []])
        for key, name, icon, members in self.groups:
            parent = self.store.append(apps_head, row_values(name, icon or generic, members, key))
            if key == self.selected_key:
                selection_iter = parent
            if len(members) > 1:
                for p in sorted(members, key=lambda p: -p.rss):
                    child = self.store.append(parent, [p.comm, icon or generic, percent_text(p.cpu),
                                                       memory_text(p.rss), rate_text(p.disk_rate), p.cpu,
                                                       float(p.rss), p.disk_rate, "pid:%d" % p.pid, [p.pid]])
                    if "pid:%d" % p.pid == self.selected_key:
                        selection_iter = child
        head = self.store.append(None, [_("Background processes (%d)") % len(self.background), None, "", "", "",
                                        0, 0, 0, "section:background", []])
        for p in sorted(self.background, key=lambda p: p.comm.casefold()):
            row = self.store.append(head, [p.comm, generic, percent_text(p.cpu), memory_text(p.rss),
                                           rate_text(p.disk_rate), p.cpu, float(p.rss), p.disk_rate,
                                           "pid:%d" % p.pid, [p.pid]])
            if "pid:%d" % p.pid == self.selected_key:
                selection_iter = row
        self.view.expand_row(self.store.get_path(apps_head), False)
        self.view.expand_row(self.store.get_path(head), False)
        for row in self._iter_rows():
            if self.store[row][COL_KEY] in self.expanded:
                self.view.expand_row(self.store.get_path(row), False)
        if selection_iter is not None:
            self.view.get_selection().select_iter(selection_iter)
        mem_total = self.sampler.memory.get("MemTotal", 0)
        mem_used = mem_total - self.sampler.memory.get("MemAvailable", 0)
        self.cpu_column.set_title("%d %%\n%s" % (round(self.sampler.cpu), _("CPU")))
        self.mem_column.set_title("%d %%\n%s" % (round(100 * mem_used / mem_total) if mem_total else 0,
                                                  _("Memory")))
        disk_active = max((d[2] for d in self.sampler.disks.values()), default=0)
        self.disk_column.set_title("%d %%\n%s" % (round(disk_active), _("Disk")))

    def _iter_rows(self):
        stack = [self.store.get_iter_first()]
        while stack:
            it = stack.pop()
            while it is not None:
                yield it
                child = self.store.iter_children(it)
                if child is not None:
                    stack.append(child)
                it = self.store.iter_next(it)

    def _fill_performance(self):
        s = self.sampler
        cpu = self._resource("cpu", _("CPU"), "#1170c8")
        cpu["small"].push(s.cpu)
        cpu["big"].push(s.cpu)
        cpu["summary"].set_text("%d %%" % round(s.cpu))
        cpu["subtitle"] = cpu_model()
        cpu["stats"] = [(_("Utilization"), "%d %%" % round(s.cpu)),
                        (_("Processes"), str(len(s.processes))),
                        (_("Logical processors"), str(s.ncpu)),
                        (_("Up time"), uptime_text())]
        mem_total = s.memory.get("MemTotal", 0)
        used = mem_total - s.memory.get("MemAvailable", 0)
        mem = self._resource("memory", _("Memory"), "#8b12ae", float(mem_total or 1))
        mem["small"].push(used, float(mem_total or 1))
        mem["big"].push(used, float(mem_total or 1))
        percent = round(100 * used / mem_total) if mem_total else 0
        mem["summary"].set_text("%s/%s (%d %%)" % (human_size(used), human_size(mem_total), percent))
        mem["subtitle"] = human_size(mem_total)
        mem["stats"] = [(_("In use"), human_size(used)), (_("Available"), human_size(s.memory.get("MemAvailable", 0))),
                        (_("Cached"), human_size(s.memory.get("Cached", 0))),
                        (_("Swap"), human_size(s.memory.get("SwapTotal", 0) - s.memory.get("SwapFree", 0)))]
        for index, (name, (read, write, active)) in enumerate(sorted(s.disks.items())):
            disk = self._resource("disk:" + name, _("Disk %d (%s)") % (index, name), "#4da60c")
            disk["small"].push(active)
            disk["big"].push(active)
            disk["summary"].set_text("%d %%" % round(active))
            disk["stats"] = [(_("Active time"), "%d %%" % round(active)), (_("Read speed"), rate_text(read)),
                             (_("Write speed"), rate_text(write))]
        for name, (rx, tx) in sorted(s.net.items()):
            kind = _("Wi-Fi") if name.startswith(("wl", "wifi")) else _("Ethernet")
            net = self._resource("net:" + name, "%s (%s)" % (kind, name), "#a74f01", 1e6)
            peak = max(1e5, max(net["big"].values) * 1.2, rx + tx)
            net["small"].push(rx + tx, peak)
            net["big"].push(rx + tx, peak)
            net["summary"].set_text(_("S: %s R: %s") % (kbit(tx), kbit(rx)))
            net["stats"] = [(_("Send"), kbit(tx)), (_("Receive"), kbit(rx))]
        if self.current_resource in self.resources:
            res = self.resources[self.current_resource]
            self.perf_subtitle.set_text(res["subtitle"])
            self._show_stats(res)

    def _fill_details(self):
        self.details_store.clear()
        for p in self.sampler.processes:
            self.details_store.append([p.comm, p.pid, _(STATE_NAMES.get(p.state, N_("Running"))),
                                       user_name(p.uid), p.cpu, float(p.rss), p.cmdline])

    # -- actions ------------------------------------------------------------------------

    def _on_select(self, selection):
        model, it = selection.get_selected()
        key = model[it][COL_KEY] if it is not None else None
        self.selected_key = key if key and not key.startswith("section:") else None
        self.end_button.set_sensitive(self.selected_key is not None)

    def _on_process_click(self, _view, event):
        if event.button != 3:
            return False
        path = self.view.get_path_at_pos(int(event.x), int(event.y))
        if not path:
            return False
        self.view.get_selection().select_path(path[0])
        if self.selected_key is None:
            return True
        menu = Gtk.Menu()
        item = Gtk.MenuItem(label=_("End task"))
        item.connect("activate", lambda *_: self._end_selected())
        menu.append(item)
        pids = self.store[path[0]][COL_PIDS]
        if len(pids) == 1:
            exe = Gtk.MenuItem(label=_("Open file location"))
            exe.connect("activate", lambda *_: open_location(pids[0]))
            menu.append(exe)
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def _end_selected(self):
        if self.selected_key:
            self._end_key(self.selected_key)

    def _end_key(self, key):
        if key.startswith("pid:"):
            pids = [int(key[4:])]
        else:
            members = next((m for k, _n, _i, m in self.groups if k == key), [])
            member_pids = {p.pid for p in members}
            pids = [p.pid for p in members if p.ppid not in member_pids]  # the roots
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError as exc:
                log.warning("cannot end %d: %s", pid, exc)
        GLib.timeout_add(300, lambda: self._refresh() and False)

    def _on_key(self, _widget, event):
        if event.keyval == Gdk.KEY_Delete:
            if self.stack.get_visible_child_name() == "simple":
                self._end_simple()
            else:
                self._end_selected()
            return True
        return False


def kbit(bytes_per_s):
    return _("%d kbit/s") % round(bytes_per_s * 8 / 1000) if bytes_per_s * 8 < 1e6 else \
        _("%.1f Mbit/s") % (bytes_per_s * 8 / 1e6)


def cpu_model():
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def uptime_text():
    try:
        with open("/proc/uptime", encoding="utf-8") as fh:
            seconds = int(float(fh.read().split()[0]))
    except (OSError, ValueError, IndexError):
        return ""
    days, rest = divmod(seconds, 86400)
    return "%d:%02d:%02d:%02d" % (days, rest // 3600, rest % 3600 // 60, rest % 60)


_users = {}


def user_name(uid):
    if uid not in _users:
        try:
            _users[uid] = pwd.getpwuid(uid).pw_name
        except KeyError:
            _users[uid] = str(uid)
    return _users[uid]


def open_location(pid):
    try:
        exe = os.readlink("/proc/%d/exe" % pid)
    except OSError:
        return
    from tenwin import paths
    from tenwin.services import system
    system.run([paths.binary("tenwin-explorer"), os.path.dirname(exe)])


class TaskManagerApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="org.tenwin.TaskManager", flags=Gio.ApplicationFlags.FLAGS_NONE)

    def do_startup(self):
        Gtk.Application.do_startup(self)
        theme.install("taskmgr")

    def do_activate(self):
        windows = self.get_windows()
        if windows:
            windows[0].present()
        else:
            TaskManager(self)


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    GLib.set_prgname("org.tenwin.TaskManager")
    return TaskManagerApp().run(sys.argv)

