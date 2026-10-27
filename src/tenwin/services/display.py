"""Backlight brightness (brightnessctl), night light (gammastep) and outputs (wlr-randr)."""

import json
import logging
import shutil
import subprocess

from gi.repository import GLib

log = logging.getLogger(__name__)


class Brightness:
    def __init__(self):
        self.device = None
        self.percent = 100
        self.refresh()

    @property
    def available(self):
        return self.device is not None

    def refresh(self):
        if not shutil.which("brightnessctl"):
            return
        try:
            out = subprocess.run(["brightnessctl", "-m", "-l"], capture_output=True, text=True,
                                 timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            return
        for line in out.splitlines():
            parts = line.split(",")
            if len(parts) >= 5 and parts[1] == "backlight":
                self.device = parts[0]
                try:
                    self.percent = int(parts[3].rstrip("%"))
                except ValueError:
                    pass
                return

    def set(self, percent):
        if not self.device:
            return
        self.percent = max(1, min(100, int(percent)))
        GLib.spawn_async(["brightnessctl", "-q", "-d", self.device, "set", "%d%%" % self.percent],
                         flags=GLib.SpawnFlags.SEARCH_PATH)

    def change(self, delta):
        self.set(self.percent + delta)


class NightLight:
    def __init__(self):
        self.proc = None

    @property
    def available(self):
        return bool(shutil.which("gammastep") or shutil.which("wlsunset"))

    @property
    def active(self):
        return self.proc is not None and self.proc.poll() is None

    def set(self, enabled, temperature=4500):
        self.stop()
        if not enabled:
            return
        if shutil.which("gammastep"):
            args = ["gammastep", "-P", "-O", str(int(temperature)), "-m", "wayland"]
        elif shutil.which("wlsunset"):
            t = str(int(temperature))
            args = ["wlsunset", "-t", t, "-T", str(int(temperature) + 1), "-S", "00:00", "-s", "23:59"]
        else:
            return
        try:
            self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            log.warning("night light: %s", exc)

    def stop(self):
        if self.active:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None


def list_outputs():
    """Outputs as reported by ``wlr-randr --json`` (empty list if unavailable)."""
    if not shutil.which("wlr-randr"):
        return []
    try:
        out = subprocess.run(["wlr-randr", "--json"], capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.SubprocessError):
        return []
    if out.returncode == 0:
        try:
            return json.loads(out.stdout)
        except ValueError:
            pass
    return _parse_text(subprocess.run(["wlr-randr"], capture_output=True, text=True).stdout)


def _parse_text(text):
    """Fallback parser for the plain text output of older wlr-randr versions."""
    outputs = []
    current = None
    in_modes = False
    for line in text.splitlines():
        if line and not line.startswith(" "):
            name, _, desc = line.partition(" ")
            current = {"name": name, "description": desc.strip('"() '), "modes": [],
                       "enabled": True, "scale": 1.0, "transform": "normal"}
            outputs.append(current)
            in_modes = False
            continue
        stripped = line.strip()
        if current is None:
            continue
        if stripped.startswith("Modes:"):
            in_modes = True
        elif in_modes and "px" in stripped:
            try:
                res, _, rest = stripped.partition(" px, ")
                w, h = res.split("x")
                refresh = float(rest.split(" ")[0])
                current["modes"].append({"width": int(w), "height": int(h), "refresh": refresh,
                                         "current": "current" in rest, "preferred": "preferred" in rest})
            except ValueError:
                pass
        else:
            in_modes = False
            key, _, value = stripped.partition(":")
            value = value.strip()
            if key == "Enabled":
                current["enabled"] = value == "yes"
            elif key == "Scale":
                try:
                    current["scale"] = float(value)
                except ValueError:
                    pass
            elif key == "Transform":
                current["transform"] = value
    return outputs


def apply_output(name, width=None, height=None, refresh=None, scale=None, transform=None):
    args = ["wlr-randr", "--output", name]
    if width and height:
        mode = "%dx%d" % (width, height)
        if refresh:
            mode += "@%.3fHz" % refresh
        args += ["--mode", mode]
    if scale:
        args += ["--scale", "%.2f" % scale]
    if transform:
        args += ["--transform", transform]
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False
