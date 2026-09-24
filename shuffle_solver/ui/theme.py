"""The window's look: a ttkbootstrap theme family, shown in light or dark mode.

Colours come from the active theme through bootstyles ("success", "danger",
...), never from hex literals in the UI code, so every panel follows a theme
switch. The choice is remembered in a small JSON settings file, which the
update checker shares (see ``read_settings``/``write_settings``).
"""

import json
from dataclasses import dataclass
from pathlib import Path

import ttkbootstrap as tb

SETTINGS_PATH = Path.home() / ".shuffle_solver.json"
DEFAULT_FAMILY = "sandstone"


def read_settings(path):
    """Everything saved at ``path``, or ``{}`` if missing, unreadable or not a JSON object."""
    if path is None:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_settings(path, **values):
    """Save ``values`` at ``path``, keeping the other settings already there."""
    if path is None:
        return
    try:
        Path(path).write_text(json.dumps({**read_settings(path), **values}), encoding="utf-8")
    except OSError:
        pass  # failing to remember a setting only costs its default next time


def families():
    """Theme families that come in both a light and a dark variant, e.g. "nord"."""
    names = set(tb.Style().theme_names())
    return sorted(n[:-len("-light")] for n in names
                  if n.endswith("-light") and n[:-len("-light")] + "-dark" in names)


def display_name(family):
    return family.replace("-", " ").title()


def _mix(color, base, amount):
    """``amount`` of ``color`` blended into ``base`` (both "#rrggbb")."""
    a, b = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (color, base))
    return "#" + "".join(f"{round(x * amount + y * (1 - amount)):02x}" for x, y in zip(a, b))


# Colours a user can give a group of steps. They are the user's choice, not part of
# the theme, so they are shown through ``tint`` to stay readable in every theme.
GROUP_COLORS = {
    "Red": "#d9534f",
    "Orange": "#f0883e",
    "Yellow": "#e3b505",
    "Green": "#4caf50",
    "Blue": "#3b82f6",
    "Purple": "#9b59b6",
    "Gray": "#8a8a8a",
}


def tint(color, amount):
    """``color`` ("#rrggbb" or a GROUP_COLORS name) blended into the theme's background."""
    return _mix(GROUP_COLORS.get(color, color), tb.Style().colors.bg, amount)


def _configure_custom_styles(style):
    # Dimmed hint text (Muted), and tinted fields for a duplicated card (Dup) and an
    # unreadable entry (Bad). A theme switch rebuilds every style, so these are redone
    # after each one.
    c = style.colors
    style.configure("Muted.TLabel", foreground=_mix(c.fg, c.bg, 0.6))
    style.configure("Dup.TCombobox", fieldbackground=_mix(c.danger, c.inputbg, 0.35),
                    foreground=c.inputfg)
    style.configure("Bad.TCombobox", fieldbackground=_mix(c.warning, c.inputbg, 0.35),
                    foreground=c.inputfg)


@dataclass
class ThemeChoice:
    family: str = DEFAULT_FAMILY
    dark: bool = False

    @property
    def theme_name(self):
        return f"{self.family}-{'dark' if self.dark else 'light'}"

    def apply(self):
        style = tb.Style()
        style.theme_use(self.theme_name)
        _configure_custom_styles(style)

    @classmethod
    def load(cls, path):
        """The choice saved at ``path``, or the default if missing or unreadable."""
        data = read_settings(path)
        family, dark = data.get("theme"), data.get("dark")
        if family not in families() or not isinstance(dark, bool):
            return cls()
        return cls(family, dark)

    def save(self, path):
        write_settings(path, theme=self.family, dark=self.dark)
