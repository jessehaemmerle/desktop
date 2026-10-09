"""Parser für die Ausgaben von Systemwerkzeugen (wpctl, brightnessctl, nmcli, …)."""

from __future__ import annotations

import re
from pathlib import Path


def parse_wpctl_volume(text: str) -> tuple[float, bool] | None:
    """'Volume: 0.45 [MUTED]' → (0.45, True)."""
    match = re.search(r"Volume:\s*([0-9.]+)", text or "")
    if not match:
        return None
    return float(match.group(1)), "MUTED" in text


def parse_pactl_volume(volume_text: str, mute_text: str = "") -> tuple[float, bool] | None:
    """Ausgabe von ``pactl get-sink-volume`` / ``get-sink-mute``."""
    values = [int(v) for v in re.findall(r"(\d+)%", volume_text or "")]
    if not values:
        return None
    return sum(values) / len(values) / 100.0, "yes" in (mute_text or "").lower()


def parse_brightnessctl(text: str) -> float | None:
    """Maschinenlesbare Ausgabe (-m): 'intel_backlight,backlight,600,50%,1200' → 0.5."""
    for line in (text or "").splitlines():
        parts = line.strip().split(",")
        if len(parts) >= 5 and parts[1] == "backlight":
            try:
                return int(parts[2]) / max(1, int(parts[4]))
            except ValueError:
                continue
    return None


def parse_nmcli_devices(text: str) -> dict:
    """``nmcli -t -f TYPE,STATE,CONNECTION device`` → Zusammenfassung des Netzwerks."""
    result = {"kind": "none", "connected": False, "name": ""}
    best = 0
    rank = {"ethernet": 3, "wifi": 2}
    for line in (text or "").splitlines():
        # nmcli escaped ':' in Feldern als '\:'
        parts = re.split(r"(?<!\\):", line.strip())
        if len(parts) < 3:
            continue
        kind, state, name = parts[0], parts[1], parts[2].replace("\\:", ":")
        if kind not in rank:
            continue
        connected = state.startswith("connected") or state.startswith("verbunden")
        score = rank[kind] + (10 if connected else 0)
        if score > best:
            best = score
            result = {"kind": kind, "connected": connected, "name": name if connected else ""}
    return result


def parse_wifi_signal(text: str) -> int | None:
    """``nmcli -t -f ACTIVE,SIGNAL dev wifi`` → Signalstärke der aktiven Verbindung."""
    for line in (text or "").splitlines():
        parts = line.strip().split(":")
        if len(parts) >= 2 and parts[0] in ("yes", "ja"):
            try:
                return int(parts[1])
            except ValueError:
                return None
    return None


def parse_bluetoothctl_show(text: str) -> bool | None:
    match = re.search(r"Powered:\s*(yes|no)", text or "")
    if not match:
        return None
    return match.group(1) == "yes"


def read_battery(root: Path = Path("/sys/class/power_supply")) -> dict | None:
    """Liest den ersten Akku aus sysfs."""
    try:
        candidates = sorted(root.iterdir())
    except OSError:
        return None
    for entry in candidates:
        try:
            if (entry / "type").read_text().strip() != "Battery":
                continue
            capacity = int((entry / "capacity").read_text().strip())
            status = (entry / "status").read_text().strip()
        except (OSError, ValueError):
            continue
        return {"percent": capacity, "charging": status in ("Charging", "Full"), "status": status}
    return None


def battery_icon(percent: int, charging: bool) -> str:
    level = max(0, min(100, int(round(percent / 10.0) * 10)))
    suffix = "-charging" if charging else ""
    return f"battery-level-{level}{suffix}-symbolic"


def volume_icon(volume: float, muted: bool) -> str:
    if muted or volume <= 0.001:
        return "audio-volume-muted-symbolic"
    if volume < 0.34:
        return "audio-volume-low-symbolic"
    if volume < 0.67:
        return "audio-volume-medium-symbolic"
    return "audio-volume-high-symbolic"


def network_icon(info: dict, signal: int | None = None) -> str:
    if info.get("kind") == "ethernet" and info.get("connected"):
        return "network-wired-symbolic"
    if info.get("kind") == "wifi" and info.get("connected"):
        if signal is None:
            return "network-wireless-signal-good-symbolic"
        for threshold, name in ((80, "excellent"), (55, "good"), (30, "ok"), (0, "weak")):
            if signal >= threshold:
                return f"network-wireless-signal-{name}-symbolic"
    if info.get("kind") == "wifi":
        return "network-wireless-offline-symbolic"
    return "network-offline-symbolic"
