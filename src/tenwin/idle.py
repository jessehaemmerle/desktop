"""Idle handling: lock and suspend after inactivity (wraps swayidle).

swayidle is restarted whenever a ``power.*`` setting changes.
"""

import logging
import shutil
import signal
import subprocess
import sys

import gi
gi.require_version("GLib", "2.0")
from gi.repository import GLib

from tenwin import paths
from tenwin.config import get_settings

log = logging.getLogger("tenwin.idle")


def swayidle_args(settings):
    lock = paths.binary("tenwin-lock")
    args = ["swayidle", "-w"]
    lock_min = int(settings["power.lock_after_min"])
    suspend_min = int(settings["power.suspend_after_min"])
    if lock_min > 0:
        args += ["timeout", str(lock_min * 60), lock + " --daemonize"]
    if suspend_min > 0:
        args += ["timeout", str(suspend_min * 60), "systemctl suspend"]
    if settings["power.lock_on_suspend"]:
        args += ["before-sleep", lock + " --daemonize"]
    return args


class IdleManager:
    def __init__(self):
        self.settings = get_settings()
        self.proc = None
        self.settings.connect("changed", self._on_changed)
        self.restart()

    def _on_changed(self, _settings, keys):
        if any(k.startswith("power.") for k in keys):
            self.restart()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self.proc = None

    def restart(self):
        self.stop()
        if not shutil.which("swayidle"):
            log.warning("swayidle not installed; idle locking disabled")
            return
        args = swayidle_args(self.settings)
        if len(args) <= 2:
            return
        log.info("starting %s", " ".join(args))
        self.proc = subprocess.Popen(args)


def main():
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    loop = GLib.MainLoop()
    manager = IdleManager()

    def quit_(*_args):
        manager.stop()
        loop.quit()
        return GLib.SOURCE_REMOVE

    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, quit_)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, quit_)
    loop.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
