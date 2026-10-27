"""Search back ends: applications and files in the home folder."""

import os
import threading
import time

SKIP_DIRS = {"node_modules", "__pycache__", "snap", "venv", ".venv", "site-packages"}
MAX_FILES = 60000
MAX_DEPTH = 6
INDEX_TTL = 300


def score_app(info, query):
    """Lower is better; None if the app doesn't match."""
    q = query.casefold()
    name = (info.get_display_name() or "").casefold()
    if name.startswith(q):
        return 0
    words = name.split()
    if any(w.startswith(q) for w in words):
        return 1
    if q in name:
        return 2
    generic = (info.get_generic_name() or "").casefold()
    if q in generic:
        return 3
    keywords = " ".join(info.get_keywords() or []).casefold()
    if q in keywords:
        return 4
    executable = os.path.basename(info.get_executable() or "").casefold()
    if executable.startswith(q):
        return 5
    return None


def search_apps(apps, query, limit=8):
    scored = []
    for info in apps:
        score = score_app(info, query)
        if score is not None:
            scored.append((score, (info.get_display_name() or "").casefold(), info))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [info for _s, _n, info in scored[:limit]]


class FileIndex:
    """A file-name index of the home folder, built in a background thread."""

    def __init__(self, root=None):
        self.root = root or os.path.expanduser("~")
        self.entries = []          # (lower name, path, is_dir, mtime)
        self.built_at = 0
        self._lock = threading.Lock()
        self._thread = None

    def ensure(self):
        if time.time() - self.built_at > INDEX_TTL and (self._thread is None or not self._thread.is_alive()):
            self._thread = threading.Thread(target=self._build, daemon=True)
            self._thread.start()

    def _build(self):
        entries = []
        stack = [(self.root, 0)]
        while stack and len(entries) < MAX_FILES:
            directory, depth = stack.pop()
            try:
                with os.scandir(directory) as it:
                    for entry in it:
                        name = entry.name
                        if name.startswith("."):
                            continue
                        try:
                            is_dir = entry.is_dir(follow_symlinks=False)
                            mtime = entry.stat(follow_symlinks=False).st_mtime
                        except OSError:
                            continue
                        entries.append((name.casefold(), entry.path, is_dir, mtime))
                        if is_dir and depth < MAX_DEPTH and name not in SKIP_DIRS:
                            stack.append((entry.path, depth + 1))
            except OSError:
                continue
        with self._lock:
            self.entries = entries
            self.built_at = time.time()

    def search(self, query, limit=10, dirs=None):
        q = query.casefold().strip()
        if not q:
            return []
        with self._lock:
            entries = self.entries
        starts, contains = [], []
        for name, path, is_dir, mtime in entries:
            if dirs is not None and is_dir != dirs:
                continue
            if name.startswith(q):
                starts.append((-mtime, path, is_dir))
            elif q in name:
                contains.append((-mtime, path, is_dir))
        starts.sort()
        contains.sort()
        return [(p, d) for _m, p, d in (starts + contains)[:limit]]
