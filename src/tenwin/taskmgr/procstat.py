"""Process and system statistics from /proc (no third-party modules).

The parse_* functions take file contents so they can be tested anywhere.
"""

import os
import time

CLK_TCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
PAGE_SIZE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
SECTOR = 512


# -- parsers ------------------------------------------------------------------------

def parse_stat(text):
    """/proc/PID/stat -> dict (the name may contain spaces and parentheses)."""
    left, right = text.index("("), text.rindex(")")
    fields = text[right + 2:].split()
    return {
        "pid": int(text[:left].strip()),
        "comm": text[left + 1:right],
        "state": fields[0],
        "ppid": int(fields[1]),
        "ticks": int(fields[11]) + int(fields[12]),  # utime + stime
        "threads": int(fields[17]),
        "start": int(fields[19]),
    }


def parse_cpu_times(text):
    """/proc/stat -> {"cpu": (busy, total), "cpu0": …}."""
    result = {}
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        parts = line.split()
        values = [int(v) for v in parts[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
        total = sum(values[:8])
        result[parts[0]] = (total - idle, total)
    return result


def parse_meminfo(text):
    """/proc/meminfo -> {key: bytes}."""
    result = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts:
            value = int(parts[0])
            result[key] = value * 1024 if len(parts) > 1 and parts[1] == "kB" else value
    return result


def parse_net_dev(text):
    """/proc/net/dev -> {iface: (rx_bytes, tx_bytes)} without loopback."""
    result = {}
    for line in text.splitlines()[2:]:
        name, _, rest = line.partition(":")
        name = name.strip()
        values = rest.split()
        if name and name != "lo" and len(values) >= 9:
            result[name] = (int(values[0]), int(values[8]))
    return result


def is_physical_disk(name):
    if name.startswith(("loop", "ram", "zram", "dm-", "sr", "fd", "md")):
        return False
    if name.startswith("nvme"):
        return "p" not in name[4:]   # nvme0n1 yes, nvme0n1p1 no
    if name.startswith("mmcblk"):
        return "p" not in name[6:]
    return not name[-1:].isdigit()   # sda yes, sda1 no


def parse_diskstats(text):
    """/proc/diskstats -> {disk: (read_bytes, written_bytes, busy_ms)} for whole disks."""
    result = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 14 or not is_physical_disk(parts[2]):
            continue
        result[parts[2]] = (int(parts[5]) * SECTOR, int(parts[9]) * SECTOR, int(parts[12]))
    return result


def parse_io(text):
    """/proc/PID/io -> read_bytes + write_bytes."""
    total = 0
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if key in ("read_bytes", "write_bytes"):
            total += int(value)
    return total


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


# -- sampling -------------------------------------------------------------------------

class Process:
    __slots__ = ("pid", "ppid", "comm", "cmdline", "exe", "state", "threads", "uid", "rss",
                 "ticks", "io", "cpu", "disk_rate", "start")

    def __init__(self):
        self.cpu = 0.0
        self.disk_rate = 0.0


class Sampler:
    """Keeps the previous sample to compute rates (CPU %, bytes/s)."""

    def __init__(self, proc="/proc"):
        self.proc = proc
        self.uid = os.getuid()
        self._prev_ticks = {}
        self._prev_io = {}
        self._prev_cpu = None
        self._prev_disks = None
        self._prev_net = None
        self._prev_time = None
        self.ncpu = os.cpu_count() or 1
        self.processes = []
        self.cpu = 0.0
        self.cpus = []
        self.memory = {}
        self.disks = {}   # name -> (read/s, write/s, active %)
        self.net = {}     # iface -> (rx/s, tx/s)

    def sample(self, all_users=False):
        now = time.monotonic()
        elapsed = (now - self._prev_time) if self._prev_time else None
        self._prev_time = now

        cpu_text = _read(os.path.join(self.proc, "stat")) or ""
        cpu = parse_cpu_times(cpu_text)
        total_delta = None
        if self._prev_cpu and "cpu" in cpu and "cpu" in self._prev_cpu:
            busy = cpu["cpu"][0] - self._prev_cpu["cpu"][0]
            total_delta = cpu["cpu"][1] - self._prev_cpu["cpu"][1]
            self.cpu = 100.0 * busy / total_delta if total_delta > 0 else 0.0
            self.cpus = []
            for i in range(self.ncpu):
                key = "cpu%d" % i
                if key in cpu and key in self._prev_cpu:
                    b = cpu[key][0] - self._prev_cpu[key][0]
                    tot = cpu[key][1] - self._prev_cpu[key][1]
                    self.cpus.append(100.0 * b / tot if tot > 0 else 0.0)
        self._prev_cpu = cpu

        self.memory = parse_meminfo(_read(os.path.join(self.proc, "meminfo")) or "")

        disks = parse_diskstats(_read(os.path.join(self.proc, "diskstats")) or "")
        if self._prev_disks is not None and elapsed:
            self.disks = {}
            for name, (r, w, busy) in disks.items():
                pr, pw, pbusy = self._prev_disks.get(name, (r, w, busy))
                active = min(100.0, (busy - pbusy) / (elapsed * 10.0))
                self.disks[name] = ((r - pr) / elapsed, (w - pw) / elapsed, max(0.0, active))
        self._prev_disks = disks

        net = parse_net_dev(_read(os.path.join(self.proc, "net/dev")) or "")
        if self._prev_net is not None and elapsed:
            self.net = {n: ((rx - self._prev_net.get(n, (rx, tx))[0]) / elapsed,
                            (tx - self._prev_net.get(n, (rx, tx))[1]) / elapsed) for n, (rx, tx) in net.items()}
        self._prev_net = net

        self.processes = self._processes(all_users, total_delta, elapsed)
        return self

    def _processes(self, all_users, total_delta, elapsed):
        result = []
        ticks, ios = {}, {}
        try:
            pids = [int(d) for d in os.listdir(self.proc) if d.isdigit()]
        except OSError:
            pids = []
        for pid in pids:
            base = os.path.join(self.proc, str(pid))
            try:
                uid = os.stat(base).st_uid
            except OSError:
                continue
            if not all_users and uid != self.uid:
                continue
            text = _read(os.path.join(base, "stat"))
            if not text:
                continue
            try:
                stat = parse_stat(text)
            except (ValueError, IndexError):
                continue
            if stat["pid"] == 2 or stat["ppid"] == 2:
                continue  # kernel threads
            p = Process()
            p.pid, p.ppid, p.comm, p.state = stat["pid"], stat["ppid"], stat["comm"], stat["state"]
            p.threads, p.start, p.uid = stat["threads"], stat["start"], uid
            p.ticks = stat["ticks"]
            statm = _read(os.path.join(base, "statm"))
            p.rss = int(statm.split()[1]) * PAGE_SIZE if statm else 0
            cmdline = _read(os.path.join(base, "cmdline")) or ""
            p.cmdline = cmdline.replace("\0", " ").strip()
            try:
                p.exe = os.path.basename(os.readlink(os.path.join(base, "exe")))
            except OSError:
                p.exe = ""
            io_text = _read(os.path.join(base, "io"))
            p.io = parse_io(io_text) if io_text else 0
            key = (pid, p.start)
            ticks[key] = p.ticks
            ios[key] = p.io
            if total_delta and key in self._prev_ticks:
                # Like Windows: share of the whole machine (all cores = 100 %).
                p.cpu = 100.0 * (p.ticks - self._prev_ticks[key]) / total_delta
            if elapsed and key in self._prev_io:
                p.disk_rate = max(0.0, (p.io - self._prev_io[key]) / elapsed)
            result.append(p)
        self._prev_ticks, self._prev_io = ticks, ios
        return result


# -- grouping into apps -------------------------------------------------------------------

def children_map(processes):
    kids = {}
    for p in processes:
        kids.setdefault(p.ppid, []).append(p)
    return kids


def descendants(root, kids):
    result, stack = [], [root]
    while stack:
        p = stack.pop()
        result.append(p)
        stack.extend(kids.get(p.pid, []))
    return result


# Tenwin's own apps run as "python3 -m MODULE".
PYTHON_MODULES = {"org.tenwin.Explorer": "tenwin.explorer", "org.tenwin.Settings": "tenwin.settings",
                  "org.tenwin.TaskManager": "tenwin.taskmgr"}


def script_names(cmdline):
    """Base names of the program and of a script it runs (python3 /usr/bin/foo …)."""
    words = cmdline.split()[:3]
    names = {os.path.basename(w).lower() for w in words if not w.startswith("-")}
    if "-m" in words:
        index = words.index("-m")
        if index + 1 < len(words):
            names.add("module:" + words[index + 1])
    return names


def match_names(app_id, executable):
    """Names a process of this app may have (comm is truncated to 15 bytes)."""
    names = set()
    for value in (app_id or "", executable or ""):
        value = os.path.basename(value).lower()
        if value.endswith(".desktop"):
            value = value[:-8]
        if not value:
            continue
        names.add(value)
        names.add(value.rsplit(".", 1)[-1])
    module = PYTHON_MODULES.get(app_id or "")
    if module:
        names.add("module:" + module)
    return {n for n in names if n} | {n[:15] for n in names if n}


def group_apps(processes, apps):
    """Split processes into apps and background processes.

    ``apps`` is a list of (key, name, icon, app_id, executable) for the open
    windows. Returns ([(key, name, icon, [process, …])], [background processes]).
    """
    kids = children_map(processes)
    by_pid = {p.pid: p for p in processes}
    used = set()
    groups = []
    for key, name, icon, app_id, executable in apps:
        names = match_names(app_id, executable)
        candidates = [p for p in processes if p.pid not in used and
                      (p.comm.lower() in names or p.exe.lower() in names
                       or script_names(p.cmdline) & names)]
        # Roots: matching processes whose parent is not a matching process too.
        roots = [p for p in candidates if by_pid.get(p.ppid) not in candidates]
        members = []
        for root in roots:
            for p in descendants(root, kids):
                if p.pid not in used:
                    used.add(p.pid)
                    members.append(p)
        if members:
            groups.append((key, name, icon, members))
    background = [p for p in processes if p.pid not in used]
    return groups, background
