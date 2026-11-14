"""The window's look, in one of two styles, each light or dark.

Glass (the default) has frosted-glass panels over a soft, glowing backdrop.
Classic is the flat look the app had before, with the same theme families
(their colours are in ``classic_themes``). Colours come from the active ``Palette``, never from hex literals in the UI
code: a widget asks for a tone ("success", "danger", ...) with
``widgets.set_tone`` and the stylesheet built here colours it, so every panel
follows a theme switch. ``GlassWindow`` paints the backdrop the glass panels
sit on; on Windows 11 it can also let the desktop show through, blurred by the
system (``ThemeChoice.see_through``). The choice is remembered in a small JSON
settings file, which the update checker and the presets share (see
``read_settings``/``write_settings``).
"""

import ctypes
import json
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from string import Template

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPalette, QRadialGradient
from PySide6.QtWidgets import QApplication, QMainWindow

from .classic_themes import CLASSIC_THEMES

SETTINGS_PATH = Path.home() / ".shuffle_solver.json"
DEFAULT_FAMILY = "aurora"

# name -> (accent, the three colours glowing in the backdrop)
FAMILIES = {
    "aurora": ("#7c5cff", ("#7c5cff", "#00b4ff", "#ff4fa3")),
    "ocean": ("#0a84ff", ("#0a84ff", "#1fd1c1", "#5e5ce6")),
    "sunset": ("#f2622e", ("#ff6b3d", "#ff2d78", "#ffb020")),
    "forest": ("#24a356", ("#2fb560", "#0ea5a0", "#9bd43a")),
    "graphite": ("#5b6b82", ("#64748b", "#94a3b8", "#334155")),
}


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
    """The accent families the View menu offers, e.g. "aurora"."""
    return list(FAMILIES)


def display_name(family):
    return family.replace("-", " ").title()


def _mix(color, base, amount):
    """``amount`` of ``color`` blended into ``base`` (both "#rrggbb")."""
    a, b = (tuple(int(c[i:i + 2], 16) for i in (1, 3, 5)) for c in (color, base))
    return "#" + "".join(f"{round(x * amount + y * (1 - amount)):02x}" for x, y in zip(a, b))


def _rgba(color, alpha):
    """``color`` ("#rrggbb") at ``alpha`` (0..1), as a stylesheet rgba()."""
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {round(alpha * 255)})"


# Colours a user can give a group of steps. They are the user's choice, not part of
# the theme; ``tint`` shows them see-through, so they read well on any glass.
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
    """``color`` ("#rrggbb" or a GROUP_COLORS name) at ``amount`` opacity, over the glass."""
    c = QColor(GROUP_COLORS.get(color, color))
    c.setAlphaF(amount)
    return c


GLASS, CLASSIC = "glass", "classic"
STYLES = {GLASS: "Glass", CLASSIC: "Classic"}  # style -> its name in the View menu
DEFAULT_CLASSIC_FAMILY = "sandstone"


def classic_families():
    """The classic look's theme families (the ones the app had before), e.g. "sandstone"."""
    return sorted({name.rsplit("-", 1)[0] for name in CLASSIC_THEMES})


@dataclass(frozen=True)
class Palette:
    dark: bool
    accent: str
    glows: tuple
    bg: str  # the solid colour under everything (dialogs use it as is)
    fg: str
    muted: str
    success: str
    danger: str
    warning: str
    info: str
    style: str = GLASS
    # The classic look's own colours (the glass look derives these from the above).
    border: str = ""
    inputbg: str = ""
    inputfg: str = ""
    selectbg: str = ""
    selectfg: str = "#ffffff"

    @property
    def on_warning(self):
        return "#1b1d26"


def palette(family, dark, style=GLASS):
    if style == CLASSIC:
        c = CLASSIC_THEMES.get(f"{family}-{'dark' if dark else 'light'}") or CLASSIC_THEMES[
            f"{DEFAULT_CLASSIC_FAMILY}-{'dark' if dark else 'light'}"]
        return Palette(dark, c["primary"], (), bg=c["bg"], fg=c["fg"],
                       muted=_mix(c["fg"], c["bg"], 0.6), success=c["success"],
                       danger=c["danger"], warning=c["warning"], info=c["info"], style=CLASSIC,
                       border=c["border"], inputbg=c["inputbg"], inputfg=c["inputfg"],
                       selectbg=c["selectbg"], selectfg=c["selectfg"])
    accent, glows = FAMILIES.get(family, FAMILIES[DEFAULT_FAMILY])
    if dark:
        return Palette(True, accent, glows, bg="#11121b", fg="#eef0f7", muted="#9a9db0",
                       success="#34d17a", danger="#ff5a52", warning="#ffcf33", info="#5cc8ff")
    return Palette(False, accent, glows, bg="#e8ecf5", fg="#1b1d26", muted="#646a7d",
                   success="#13924a", danger="#d6332a", warning="#b07d00", info="#0b74d6")


_current = palette(DEFAULT_FAMILY, False)


def current():
    """The palette now in use."""
    return _current


# --- the stylesheet ------------------------------------------------------------------------

_QSS = Template("""
QWidget { color: $fg; }
QMainWindow, QWidget#central, QStackedWidget#tabBody, QSplitter, QScrollArea#plain,
QScrollArea#plain > QWidget > QWidget { background: transparent; }
QDialog, QWidget#cardViewer { background: $solid; }
QToolTip { background: $menu; color: $fg; border: 1px solid $edge; border-radius: 6px;
           padding: 4px 6px; }

QMenuBar { background: transparent; padding: 3px 6px; }
QMenuBar::item { background: transparent; padding: 4px 10px; border-radius: 7px; }
QMenuBar::item:selected, QMenuBar::item:pressed { background: $hover; }
QMenu { background: $menu; border: 1px solid $edge; border-radius: 10px; padding: 5px; }
QMenu::item { padding: 6px 26px 6px 14px; border-radius: 6px; background: transparent; }
QMenu::item:selected { background: $accent; color: white; }
QMenu::item:disabled { color: $muted; }
QMenu::separator { height: 1px; background: $edge; margin: 4px 8px; }
QMenu::indicator { width: 14px; height: 14px; left: 6px; }

QGroupBox { background: $panel; border: 1px solid $edge; border-top-color: $shine;
            border-radius: 16px; margin-top: 0px; padding: 34px 12px 12px 12px;
            font-weight: 600; }
QGroupBox::title { subcontrol-origin: border; subcontrol-position: top left;
                   left: 15px; top: 11px; padding: 0px; color: $fg; }
QGroupBox QLabel, QGroupBox QCheckBox, QGroupBox QRadioButton { font-weight: normal; }

QPushButton, QToolButton { background: $button; border: 1px solid $edge;
                           border-top-color: $shine; border-radius: 9px; padding: 5px 12px; }
QPushButton:hover, QToolButton:hover { background: $hover; }
QPushButton:pressed, QToolButton:pressed { background: $pressed; }
QPushButton:disabled, QToolButton:disabled { color: $muted; background: $faint; }
QPushButton[kind="primary"] { background: $accent; color: white; border-color: $accent_edge; }
QPushButton[kind="primary"]:hover { background: $accent_hover; }
QPushButton[kind="primary"]:disabled { background: $accent_off; color: $muted_on_accent; }
QPushButton[kind="danger"] { background: transparent; color: $danger; border-color: $danger; }
QPushButton[kind="danger"]:hover { background: $danger; color: white; }
QPushButton[kind="link"] { background: transparent; border: none; color: $accent;
                           text-decoration: underline; padding: 5px 4px; }
QPushButton[kind="big"] { background: $accent; color: white; border-color: $accent_edge;
                          font-size: 14pt; padding: 14px 36px; border-radius: 16px; }
QPushButton[kind="big"]:hover { background: $accent_hover; }
QPushButton::menu-indicator { subcontrol-origin: padding; subcontrol-position: right center;
                              right: 8px; }
QPushButton[menu="true"] { padding-right: 24px; }

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox, QTreeWidget {
    background: $field; border: 1px solid $edge; border-radius: 8px;
    selection-background-color: $accent; selection-color: white; }
QLineEdit, QSpinBox, QComboBox { padding: 3px 6px; min-height: 20px; }
QPlainTextEdit, QTextEdit { padding: 4px; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus,
QTreeWidget:focus { border: 1px solid $accent; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: $muted; background: $faint; }
QPlainTextEdit[readOnly="true"] { background: $field_ro; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { background: $menu; border: 1px solid $edge; border-radius: 8px;
                              selection-background-color: $accent; selection-color: white;
                              outline: none; padding: 3px; }
QComboBox[tone="dup"] { background: $dup; }
QComboBox[tone="bad"] { background: $bad; }
QSpinBox::up-button, QSpinBox::down-button { border: none; width: 16px; background: transparent; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover { background: $hover; }

QTreeWidget { padding: 2px; outline: none; }
QTreeWidget::item { padding: 3px 2px; border: none; }
QTreeWidget::item:selected { background: $accent; color: white; }
QHeaderView { background: transparent; }
QHeaderView::section { background: transparent; border: none; border-bottom: 1px solid $edge;
                       padding: 4px 6px; font-weight: 600; color: $muted; }

QTabBar { background: transparent; }
QTabBar::tab { background: $button; border: 1px solid $edge; border-top-color: $shine;
               border-radius: 10px; padding: 6px 6px 6px 14px; margin: 2px 3px; }
QTabBar::tab:hover:!selected { background: $hover; }
QTabBar::tab:selected { background: $accent; color: white; border-color: $accent_edge; }
QTabBar QToolButton { padding: 2px; border-radius: 8px; }
QToolButton#tabClose { background: transparent; border: none; border-radius: 9px;
                       padding: 0px; margin: 0px; font-size: 11pt; }
QToolButton#tabClose:hover { background: $danger; color: white; }
QToolButton#tabClose[onAccent="true"] { color: white; }
QToolButton#tabAdd { font-size: 13pt; padding: 1px 10px; border-radius: 10px; margin: 2px; }
QTabWidget::pane { border: none; background: transparent; }
QTabWidget > QTabBar::tab { padding: 4px 12px; border-radius: 8px; }

QSplitter::handle { background: transparent; }
QSplitter::handle:horizontal { width: 10px; }
QSplitter::handle:vertical { height: 10px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle { background: $scroll; border-radius: 3px; }
QScrollBar::handle:vertical { min-height: 24px; }
QScrollBar::handle:horizontal { min-width: 24px; }
QScrollBar::handle:hover { background: $scroll_hover; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QProgressBar { background: $field; border: 1px solid $edge; border-radius: 6px;
               max-height: 10px; text-align: center; color: transparent; }
QProgressBar::chunk { background: $accent; border-radius: 5px; }
QSlider::groove:horizontal { height: 6px; background: $field; border-radius: 3px; }
QSlider::sub-page:horizontal { background: $accent; border-radius: 3px; }
QSlider::handle:horizontal { background: white; border: 2px solid $accent; width: 12px;
                             margin: -6px 0px; border-radius: 8px; }
QSlider::handle:horizontal:disabled { border-color: $muted; }

""")


_CLASSIC_QSS = Template("""
QWidget { color: $fg; }
QMainWindow, QWidget#central, QStackedWidget#tabBody, QSplitter { background: transparent; }
QDialog, QWidget#cardViewer { background: $bg; }
QToolTip { background: $inputbg; color: $fg; border: 1px solid $border; padding: 3px 5px; }

QMenuBar { background: $bg; }
QMenuBar::item { background: transparent; padding: 4px 9px; }
QMenuBar::item:selected, QMenuBar::item:pressed { background: $primary; color: $on_primary; }
QMenu { background: $bg; border: 1px solid $border; padding: 2px; }
QMenu::item { padding: 5px 24px 5px 12px; background: transparent; }
QMenu::item:selected { background: $primary; color: $on_primary; }
QMenu::item:disabled { color: $muted; }
QMenu::separator { height: 1px; background: $border; margin: 3px 6px; }

QGroupBox { background: transparent; border: 1px solid $border; border-radius: 4px;
            margin-top: 9px; padding: 14px 8px 8px 8px; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left; left: 8px;
                   padding: 0px 4px; color: $fg; }

QPushButton, QToolButton { background: $primary; color: $on_primary; border: 1px solid $primary;
                           border-radius: 3px; padding: 5px 12px; }
QPushButton:hover, QToolButton:hover { background: $primary_hover; border-color: $primary_hover; }
QPushButton:pressed, QToolButton:pressed { background: $primary_pressed; }
QPushButton:disabled, QToolButton:disabled { background: $disabled; border-color: $disabled;
                                             color: $muted; }
QPushButton[kind="danger"] { background: transparent; color: $secondary; border-color: $secondary; }
QPushButton[kind="danger"]:hover { background: $secondary; color: $on_primary; }
QPushButton[kind="danger"]:disabled { background: transparent; color: $disabled_text;
                                      border-color: $disabled; }
QPushButton[kind="link"] { background: transparent; border: none; color: $primary;
                           text-decoration: underline; padding: 5px 4px; }
QPushButton[kind="big"] { font-size: 14pt; padding: 14px 36px; }
QPushButton::menu-indicator { subcontrol-origin: padding; subcontrol-position: right center;
                              right: 8px; }
QPushButton[menu="true"] { background: transparent; color: $secondary; border-color: $secondary;
                           padding-right: 24px; }
QPushButton[menu="true"]:hover { background: $secondary; color: $on_primary; }

QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QComboBox, QTreeWidget {
    background: $inputbg; color: $inputfg; border: 1px solid $border; border-radius: 3px;
    selection-background-color: $selectbg; selection-color: $selectfg; }
QLineEdit, QSpinBox, QComboBox { padding: 3px 5px; min-height: 20px; }
QPlainTextEdit, QTextEdit { padding: 3px; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus,
QTreeWidget:focus { border: 1px solid $primary; }
QLineEdit:disabled, QSpinBox:disabled, QComboBox:disabled { color: $muted; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox QAbstractItemView { background: $inputbg; border: 1px solid $border;
                              selection-background-color: $selectbg; selection-color: $selectfg;
                              outline: none; }
QComboBox[tone="dup"] { background: $dup; }
QComboBox[tone="bad"] { background: $bad; }
QSpinBox::up-button, QSpinBox::down-button { border: none; width: 16px; background: transparent; }

QTreeWidget { outline: none; }
QTreeWidget::item { padding: 2px; border: none; }
QTreeWidget::item:selected { background: $selectbg; color: $selectfg; }
QHeaderView { background: $bg; }
QHeaderView::section { background: $heading; color: $fg; border: none;
                       border-bottom: 1px solid $border; padding: 4px 6px; }

QTabBar { background: transparent; }
QTabBar::tab { background: $tab; color: $fg; border: none; padding: 5px 4px 5px 10px;
               margin-right: 2px; }
QTabBar::tab:selected { background: $primary; color: $on_primary; }
QTabBar QToolButton { background: $tab; color: $fg; border: none; border-radius: 0px; }
QToolButton#tabClose { background: transparent; color: $fg; border: none; border-radius: 0px;
                       padding: 0px; margin: 0px; font-size: 11pt; }
QToolButton#tabClose:hover { background: $danger; color: $on_primary; }
QToolButton#tabClose[onAccent="true"] { color: $on_primary; }
QToolButton#tabAdd { background: $tab; color: $fg; border: none; font-size: 11pt;
                     padding: 1px 10px; }
QToolButton#tabAdd:hover { background: $tab_hover; }
QTabWidget::pane { border: 1px solid $border; top: -1px; }
QTabWidget > QTabBar::tab { background: $bg; border: 1px solid $border; padding: 4px 12px;
                            margin-right: -1px; }
QTabWidget > QTabBar::tab:selected { background: $bg; color: $fg; border-bottom-color: $bg; }
QTabWidget > QTabBar::tab:!selected { background: $tab; color: $muted; }

QSplitter::handle:horizontal { width: 6px; }
QSplitter::handle:vertical { height: 6px; }

QScrollBar:vertical { background: $bg; width: 12px; }
QScrollBar:horizontal { background: $bg; height: 12px; }
QScrollBar::handle { background: $scroll; border-radius: 0px; margin: 2px; }
QScrollBar::handle:vertical { min-height: 24px; }
QScrollBar::handle:horizontal { min-width: 24px; }
QScrollBar::handle:hover { background: $scroll_hover; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0px; height: 0px; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

QProgressBar { background: $tab; border: none; max-height: 10px; color: transparent; }
QProgressBar::chunk { background: $primary; }
QSlider::groove:horizontal { height: 4px; background: $border; }
QSlider::sub-page:horizontal { background: $primary; }
QSlider::handle:horizontal { background: $primary; width: 14px; margin: -6px 0px;
                             border-radius: 7px; }
QSlider::handle:horizontal:disabled { background: $muted; }
""")


_COMMON = Template("""
QLabel[tone="success"] { color: $success; }
QLabel[tone="danger"] { color: $danger; }
QLabel[tone="warning"] { color: $warning; }
QLabel[tone="info"] { color: $info; }
QLabel[tone="muted"] { color: $muted; }
QLabel[role="badge"] { border-radius: $r_badge; padding: 3px 12px; font-weight: 700;
                       font-size: 11pt; color: white; background: $muted; }
QLabel[role="badge"][tone="success"] { background: $success; color: white; }
QLabel[role="badge"][tone="danger"] { background: $danger; color: white; }
QLabel[role="badge"][tone="warning"] { background: $warning; color: $on_warning; }
QLabel[role="badge"][tone="info"] { background: $info; color: white; }
QLabel[role="question"] { font-size: 18pt; font-weight: 700; }
QLabel[role="heading"] { font-size: 16pt; font-weight: 600; }
""")


_ICONS = {  # name -> SVG; $c is the colour it's drawn in
    "check": '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
             '<path d="M3.5 8.5l3 3 6-7" fill="none" stroke="$c" stroke-width="2.2" '
             'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "dot": '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 16 16">'
           '<circle cx="8" cy="8" r="3.4" fill="$c"/></svg>',
    "down": '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 10 10">'
            '<path d="M2 3.5l3 3 3-3" fill="none" stroke="$c" stroke-width="1.6" '
            'stroke-linecap="round" stroke-linejoin="round"/></svg>',
    "up": '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10" viewBox="0 0 10 10">'
          '<path d="M2 6.5l3-3 3 3" fill="none" stroke="$c" stroke-width="1.6" '
          'stroke-linecap="round" stroke-linejoin="round"/></svg>',
}


def _icons(p):
    """Write the stylesheet's little pictures in this palette's colours; name -> url path."""
    folder = Path(tempfile.gettempdir()) / "shuffle_solver_icons"
    paths = {}
    for name, svg in _ICONS.items():
        for variant, color in (("", p.fg), ("_white", "#ffffff"), ("_muted", p.muted)):
            path = folder / f"{name}{variant}_{color.lstrip('#')}.svg"
            if not path.is_file():
                try:
                    folder.mkdir(exist_ok=True)
                    path.write_text(Template(svg).substitute(c=color), encoding="utf-8")
                except OSError:
                    continue  # the style then simply goes without the picture
            paths[f"{name}{variant}"] = path.as_posix()
    return paths


_INDICATORS = Template("""
QCheckBox::indicator, QMenu::indicator:non-exclusive { width: 16px; height: 16px;
    border-radius: $r_check; border: 1px solid $edge_strong; background: $field; }
QRadioButton::indicator, QMenu::indicator:exclusive { width: 16px; height: 16px;
    border-radius: 9px; border: 1px solid $edge_strong; background: $field; }
QCheckBox::indicator:checked, QMenu::indicator:non-exclusive:checked {
    background: $accent; border-color: $accent; image: url($check_white); }
QRadioButton::indicator:checked, QMenu::indicator:exclusive:checked {
    background: $accent; border-color: $accent; image: url($dot_white); }
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled { background: $faint; }
QMenu::indicator { left: 6px; }
QComboBox::down-arrow { image: url($down); width: 10px; height: 10px; }
QComboBox::down-arrow:disabled { image: url($down_muted); }
QSpinBox::up-arrow { image: url($up); width: 10px; height: 10px; }
QSpinBox::down-arrow { image: url($down); width: 10px; height: 10px; }
QSpinBox::up-arrow:disabled, QSpinBox::down-arrow:disabled { image: url($down_muted); }
""")


def _glass_values(p):
    white, black = "#ffffff", "#000000"
    if p.dark:
        glass = dict(panel=_rgba(white, 0.07), edge=_rgba(white, 0.13), shine=_rgba(white, 0.24),
                     button=_rgba(white, 0.09), hover=_rgba(white, 0.17),
                     pressed=_rgba(white, 0.05), faint=_rgba(white, 0.04),
                     field=_rgba(black, 0.28), field_ro=_rgba(black, 0.18),
                     menu=_mix(p.bg, white, 0.9), scroll=_rgba(white, 0.22),
                     scroll_hover=_rgba(white, 0.4))
    else:
        glass = dict(panel=_rgba(white, 0.5), edge=_rgba(black, 0.09), shine=_rgba(white, 0.9),
                     button=_rgba(white, 0.62), hover=_rgba(white, 0.92),
                     pressed=_rgba(white, 0.4), faint=_rgba(white, 0.3),
                     field=_rgba(white, 0.72), field_ro=_rgba(white, 0.5),
                     menu=_mix(p.bg, white, 0.35), scroll=_rgba(black, 0.2),
                     scroll_hover=_rgba(black, 0.35))
    glass["edge_strong"] = _rgba(white, 0.3) if p.dark else _rgba(black, 0.25)
    values = dict(
        fg=p.fg, muted=p.muted, solid=p.bg, accent=p.accent,
        accent_edge=_mix(p.accent, black, 0.85), accent_hover=_mix(p.accent, white, 0.85),
        accent_off=_rgba(p.accent, 0.35), muted_on_accent=_rgba(white, 0.6),
        success=p.success, danger=p.danger, warning=p.warning, info=p.info,
        on_warning=p.on_warning, dup=_rgba(p.danger, 0.35), bad=_rgba(p.warning, 0.35),
        **glass)
    values.update(r_badge="10px", r_check="5px")
    return values


def _classic_values(p):
    white, black = "#ffffff", "#000000"
    on_primary = p.selectfg if p.dark else white
    return dict(
        bg=p.bg, fg=p.fg, muted=p.muted, primary=p.accent, on_primary=on_primary,
        primary_hover=_mix(p.accent, white if p.dark else black, 0.88),
        primary_pressed=_mix(p.accent, black, 0.8), secondary=p.selectbg,
        disabled=_mix(p.fg, p.bg, 0.15), disabled_text=_mix(p.fg, p.bg, 0.35),
        border=p.border, inputbg=p.inputbg, inputfg=p.inputfg, selectbg=p.selectbg,
        selectfg=p.selectfg, heading=_mix(p.fg, p.bg, 0.06), tab=_mix(p.fg, p.bg, 0.12),
        tab_hover=_mix(p.fg, p.bg, 0.22), scroll=_mix(p.fg, p.bg, 0.3),
        scroll_hover=_mix(p.fg, p.bg, 0.45),
        dup=_mix(p.danger, p.inputbg, 0.35), bad=_mix(p.warning, p.inputbg, 0.35),
        success=p.success, danger=p.danger, warning=p.warning, info=p.info,
        on_warning=p.on_warning, r_badge="0px", r_check="2px",
        # the names the shared indicator rules use
        edge_strong=p.border, field=p.inputbg, accent=p.accent, faint=_mix(p.fg, p.bg, 0.1))


def stylesheet(p):
    if p.style == CLASSIC:
        values = _classic_values(p)
        sheet = _CLASSIC_QSS.substitute(values)
    else:
        values = _glass_values(p)
        sheet = _QSS.substitute(values)
    sheet += _COMMON.substitute(values)
    icons = _icons(p)
    if len(icons) == 3 * len(_ICONS):
        sheet += _INDICATORS.substitute(values, **icons)
    return sheet


def qpalette(p):
    """A QPalette for the bits the style draws itself (check boxes, arrows, ...)."""
    pal = QPalette()
    solid_field = p.inputbg or (_mix("#000000", p.bg, 0.25) if p.dark else "#ffffff")
    for role, color in ((QPalette.Window, p.bg), (QPalette.WindowText, p.fg),
                        (QPalette.Base, solid_field), (QPalette.AlternateBase, p.bg),
                        (QPalette.Text, p.fg), (QPalette.Button, p.bg),
                        (QPalette.ButtonText, p.fg), (QPalette.Highlight, p.selectbg or p.accent),
                        (QPalette.HighlightedText, "#ffffff"), (QPalette.ToolTipBase, p.bg),
                        (QPalette.ToolTipText, p.fg), (QPalette.PlaceholderText, p.muted),
                        (QPalette.Link, p.accent), (QPalette.BrightText, "#ffffff")):
        pal.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(p.muted))
    return pal


# --- the window backdrop --------------------------------------------------------------------

DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_SYSTEMBACKDROP_TYPE = 38
BACKDROP_NONE, BACKDROP_ACRYLIC = 1, 3


class _Margins(ctypes.Structure):
    _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int),
                ("top", ctypes.c_int), ("bottom", ctypes.c_int)]


def see_through_supported():
    """Whether the system can blur the desktop behind the window (Windows 11 22H2+)."""
    if sys.platform != "win32" or QApplication.platformName() != "windows":
        return False
    return sys.getwindowsversion().build >= 22621


def _dwm(hwnd, attr, value):
    v = ctypes.c_int(value)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))


class GlassWindow(QMainWindow):
    """A main window that paints the glowing backdrop the glass panels sit on.

    With ``see_through`` on (and supported) the backdrop is partly transparent
    and Windows fills in the blurred desktop behind it ("acrylic").
    """

    def __init__(self):
        super().__init__()
        self._see_through = False
        if see_through_supported():
            # Must be set before the window is first shown; with see-through off the
            # backdrop is painted fully opaque, so it then looks like any window.
            self.setAttribute(Qt.WA_TranslucentBackground)

    def set_see_through(self, on):
        on = bool(on) and see_through_supported()
        self._see_through = on
        if see_through_supported():
            hwnd = int(self.winId())
            _dwm(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, 1 if _current.dark else 0)
            _dwm(hwnd, DWMWA_SYSTEMBACKDROP_TYPE, BACKDROP_ACRYLIC if on else BACKDROP_NONE)
            m = -1 if on else 0
            ctypes.windll.dwmapi.DwmExtendFrameIntoClientArea(
                hwnd, ctypes.byref(_Margins(m, m, m, m)))
        self.update()

    @property
    def see_through(self):
        return self._see_through

    def paintEvent(self, _event):
        p = _current
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        painter.setCompositionMode(QPainter.CompositionMode_Source)
        base = QColor(p.bg)
        if self._see_through:
            base.setAlphaF(0.62 if p.dark else 0.55)
        painter.fillRect(self.rect(), base)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        # Three soft glows in the family's colours; the panels' frosted glass sits on them.
        spots = ((0.08, 0.05, 0.55), (0.95, 0.25, 0.5), (0.45, 1.05, 0.6))
        strength = (0.42 if p.dark else 0.34) * (0.8 if self._see_through else 1)
        for (fx, fy, fr), color in zip(spots, p.glows):
            radius = max(w, h) * fr
            g = QRadialGradient(QPointF(w * fx, h * fy), radius)
            inner, outer = QColor(color), QColor(color)
            inner.setAlphaF(strength)
            outer.setAlphaF(0)
            g.setColorAt(0, inner)
            g.setColorAt(1, outer)
            painter.fillRect(self.rect(), g)
        painter.end()


@dataclass
class ThemeChoice:
    """The look: glass or classic, each with its own theme family, light or dark.

    Each style remembers its own family, so switching back and forth keeps both.
    In the settings file the classic family is kept under "theme", where the app
    kept it before it had the glass look, so an old choice comes back as it was.
    """
    style: str = GLASS
    glass_family: str = DEFAULT_FAMILY
    classic_family: str = DEFAULT_CLASSIC_FAMILY
    dark: bool = False
    see_through: bool = True

    @property
    def family(self):
        """The theme family of the style in use."""
        return self.classic_family if self.style == CLASSIC else self.glass_family

    def families(self):
        """The theme families the style in use offers."""
        return classic_families() if self.style == CLASSIC else families()

    def with_family(self, family):
        """This choice with ``family`` for the style in use."""
        if self.style == CLASSIC:
            return replace(self, classic_family=family)
        return replace(self, glass_family=family)

    def apply(self, window=None):
        """Restyle the whole app; ``window`` (a GlassWindow) also gets its backdrop."""
        global _current
        _current = palette(self.family, self.dark, self.style)
        app = QApplication.instance()
        app.setPalette(qpalette(_current))
        app.setStyleSheet(stylesheet(_current))
        if window is not None:
            window.set_see_through(self.see_through and self.style == GLASS)

    @classmethod
    def load(cls, path):
        """The choice saved at ``path``, or the default if missing or unreadable."""
        data = read_settings(path)
        dark = data.get("dark")
        if not isinstance(dark, bool):
            return cls()
        theme, glass = data.get("theme"), data.get("glass_theme")
        if glass not in FAMILIES:
            glass = theme if theme in FAMILIES else DEFAULT_FAMILY
        style = data.get("style") if data.get("style") in STYLES else GLASS
        return cls(style, glass,
                   theme if theme in classic_families() else DEFAULT_CLASSIC_FAMILY, dark,
                   data.get("see_through", True) is not False)

    def save(self, path):
        write_settings(path, style=self.style, glass_theme=self.glass_family,
                       theme=self.classic_family, dark=self.dark, see_through=self.see_through)
