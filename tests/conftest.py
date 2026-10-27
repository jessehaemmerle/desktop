import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

# Isolate every test run from the real user configuration.
_home = tempfile.mkdtemp(prefix="tenwin-tests-")
os.environ["HOME"] = _home
os.environ["XDG_CONFIG_HOME"] = os.path.join(_home, ".config")
os.environ["XDG_STATE_HOME"] = os.path.join(_home, ".local/state")
os.environ["XDG_CACHE_HOME"] = os.path.join(_home, ".cache")
os.environ["XDG_DATA_HOME"] = os.path.join(_home, ".local/share")
os.environ.pop("TENWIN_CONFIG_DIR", None)
os.environ["LANGUAGE"] = "en"

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
