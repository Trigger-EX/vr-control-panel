#!/usr/bin/env python3
"""
cxvr_pyside6_preview.py -- a LOOK-ONLY preview of the CXVR control panel
rebuilt in PySide6 (Qt). Everything in it is mock data: it never runs adb,
scrcpy or any script, and no button acts on a headset.

Run it: double-click it in the file manager, or start it with any Python 3.
If that Python doesn't have PySide6 (the system one usually doesn't), the file
starts itself again with ~/.pyvenv/bin/python, or with $CXVR_QT_PYTHON if set.
Screenshots:   add --screenshot OUT_DIR (SHOT_SIZE=1920x1080 to change the size)

What works in the preview: the sidebar, clicking/double-clicking headset
tiles, Prev/Next (also the arrow keys and the mouse wheel over the grid), the
filter box, the Double view and Show Mode switches, the Log/Terminal tabs and
dragging the divider above them.
"""
import os
import random
import sys


def _relaunch_with_venv_python():
    """Double-clicking this file in a file manager starts it with whatever Python
    the desktop picks -- normally the system one, which doesn't have PySide6.
    When that happens, start this same file again with the Python in ~/.pyvenv
    (or $CXVR_QT_PYTHON), which does.

    A venv's bin/python is a symlink to the system Python, so candidates are
    compared by where they live, never by the binary they resolve to. The
    CXVR_RELAUNCHED flag makes sure this re-launches at most once."""
    try:
        import PySide6
    except ImportError:
        PySide6 = None
    if PySide6 is not None:
        os.environ.pop("CXVR_RELAUNCHED", None)   # don't leak the flag to anything started from here
        return
    here = os.path.abspath(__file__)
    current = os.path.abspath(sys.executable)
    if not os.environ.get("CXVR_RELAUNCHED"):
        for candidate in (os.environ.get("CXVR_QT_PYTHON", ""), os.path.expanduser("~/.pyvenv/bin/python")):
            if candidate and os.path.abspath(candidate) != current and os.access(candidate, os.X_OK):
                os.environ["CXVR_RELAUNCHED"] = "1"
                os.execv(candidate, [candidate, here] + sys.argv[1:])
    message = (f"PySide6 isn't available to the Python that started this file:\n{sys.executable}\n\n"
               f"It normally runs with ~/.pyvenv/bin/python. Install PySide6 there with\n"
               f"    ~/.pyvenv/bin/pip install PySide6\n"
               f"or set CXVR_QT_PYTHON to a Python that has it.")
    print(message, file=sys.stderr)
    if os.environ.get("DISPLAY") and not os.environ.get("CXVR_NO_DIALOG"):
        try:   # launched from a file manager there's no terminal, so say it in a window too
            import tkinter
            from tkinter import messagebox
            root = tkinter.Tk()
            root.withdraw()
            messagebox.showerror("CXVR", message)
            root.destroy()
        except Exception:
            pass
    sys.exit(1)


_relaunch_with_venv_python()

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractSpinBox, QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QSplitter, QTabWidget, QTextEdit, QVBoxLayout, QWidget,
)

# Same palette as the Tkinter panel, so the two are directly comparable.
GROUND = "#F2F0EC"
HEAD = "#E6E2DB"
LINE = "#CDC8BF"
SURFACE = "#FBFAF7"
TEXT = "#1E1D1B"
MUTED = "#555149"
ACCENT = "#1D5C69"
ACCENT_DARK = "#143F48"
ACCENT_TINT = "#DCE8EA"
WARN = "#8A3F00"
WARN_BG = "#FBE6D2"
DOT_OFF = "#B3ADA3"
CONSOLE_BG = "#101412"
CONSOLE_FG = "#D8E0DA"

UI_FONTS = ["Ubuntu Sans", "Ubuntu", "Noto Sans", "Cantarell", "DejaVu Sans"]
MONO_FONTS = ["Ubuntu Sans Mono", "Ubuntu Mono", "DejaVu Sans Mono"]

QSS = f"""
QWidget#ground, QWidget#page {{ background: {GROUND}; }}
QLabel {{ color: {TEXT}; background: transparent; }}

QFrame#strip {{ background: {HEAD}; border-bottom: 1px solid {LINE}; }}
QFrame#strip[showmode="true"] {{ background: {WARN_BG}; border-bottom: 1px solid #E3B58C; }}
QLabel#statValue {{ font-size: 14pt; font-weight: 700; }}
QLabel#statValue[warn="true"] {{ color: {WARN}; }}
QLabel#statCaption {{ color: {MUTED}; font-size: 8pt; }}
QLabel#wordmark {{ color: {ACCENT}; font-size: 12pt; font-weight: 800; }}
QLabel#showModeLabel {{ font-weight: 700; }}
QLabel#showBar {{ background: {WARN}; color: #FFFFFF; font-weight: 700; font-size: 9pt; padding: 5px 16px; }}
QLabel#showModeLabel[on="true"] {{ color: {WARN}; }}

QFrame#sidebar {{ background: #EBE7E0; border-right: 1px solid {LINE}; }}
QPushButton#nav {{ text-align: left; padding: 7px 12px 7px 15px; border: none;
    border-left: 3px solid transparent; border-radius: 0; background: transparent; color: {TEXT}; }}
QPushButton#nav:hover {{ background: #E1DCD3; }}
QPushButton#nav:checked {{ background: {ACCENT_TINT}; border-left: 3px solid {ACCENT};
    color: {ACCENT_DARK}; font-weight: 700; }}
QLabel#navBadge {{ background: {WARN_BG}; color: {WARN}; border-radius: 8px; padding: 0 6px;
    font-size: 8pt; font-weight: 700; }}
QLabel#previewNote {{ color: {MUTED}; font-size: 8pt; }}

QLabel#pageTitle {{ font-size: 16pt; font-weight: 700; }}
QLabel#pageSub, QLabel#caption {{ color: {MUTED}; }}
QLabel#caption {{ font-size: 9pt; }}

QFrame#card {{ background: {SURFACE}; border: 1px solid {LINE}; border-radius: 8px; }}
QFrame#cardHead {{ background: transparent; border: none; border-bottom: 1px solid #E6E2DA; }}
QFrame#rule {{ background: #E6E2DA; border: none; max-height: 1px; min-height: 1px; }}

QPushButton {{ background: #FFFFFF; border: 1px solid #C4BEB3; border-radius: 6px; padding: 6px 14px;
    color: {TEXT}; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:pressed {{ background: #EFEDE8; }}
QPushButton:disabled {{ color: #A8A298; border-color: #DDD8CF; }}
QPushButton#primary {{ background: {ACCENT}; color: #FFFFFF; border: 1px solid {ACCENT_DARK}; font-weight: 700; }}
QPushButton#primary:hover {{ background: {ACCENT_DARK}; }}
QPushButton#small {{ padding: 3px 10px; font-size: 9pt; }}
QPushButton#stripBtn {{ padding: 4px 11px; font-size: 9pt; background: #F7F5F1; }}
QPushButton#help {{ padding: 0; min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px;
    border-radius: 10px; font-weight: 700; color: {MUTED}; font-size: 9pt; }}

QPushButton#tile {{ background: #FFFFFF; border: 1px solid #D3CEC5; border-radius: 6px; padding: 0;
    min-height: 30px; font-size: 10pt; }}
QPushButton#tile:hover {{ border: 1px solid {ACCENT}; }}
QPushButton#tile[attention="true"] {{ background: {WARN_BG}; border: 1px solid #E3B58C; color: {WARN}; }}
QPushButton#tile[live="true"] {{ background: {ACCENT}; border: 1px solid {ACCENT_DARK}; color: #FFFFFF;
    font-weight: 700; }}
QPushButton#tile:checked {{ border: 2px solid {ACCENT_DARK}; font-weight: 700; }}
QLabel#swatch {{ border-radius: 3px; min-width: 12px; max-width: 12px; min-height: 12px; max-height: 12px; }}

QPushButton#seg {{ border-radius: 0; padding: 5px 14px; background: #FFFFFF; }}
QPushButton#seg[pos="first"] {{ border-top-left-radius: 6px; border-bottom-left-radius: 6px; }}
QPushButton#seg[pos="last"] {{ border-top-right-radius: 6px; border-bottom-right-radius: 6px; border-left: none; }}
QPushButton#seg:checked {{ background: {ACCENT}; color: #FFFFFF; border-color: {ACCENT_DARK}; font-weight: 700; }}

QLabel#bigSerial {{ font-size: 20pt; font-weight: 700; }}
QLabel#port {{ color: {MUTED}; font-size: 12pt; }}
QLabel#name {{ font-weight: 700; }}

QLabel#pill {{ border-radius: 8px; padding: 1px 8px; font-size: 8pt; font-weight: 700; }}
QLabel#pill[kind="run"] {{ background: {ACCENT}; color: #FFFFFF; }}
QLabel#pill[kind="idle"] {{ background: #E0DCD4; color: #45413B; }}
QLabel#pill[kind="armed"] {{ background: {WARN_BG}; color: {WARN}; }}
QLabel#pill[kind="chip"] {{ background: #F7F5F1; color: {ACCENT_DARK}; border: 1px solid #BFD3D7; }}
QLabel#pill[kind="paused"] {{ background: {WARN}; color: #FFFFFF; }}

QLineEdit, QComboBox, QSpinBox {{ background: #FFFFFF; border: 1px solid #C4BEB3; border-radius: 6px;
    padding: 4px 8px; min-height: 20px; color: {TEXT}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {ACCENT}; }}
QComboBox:disabled {{ color: #A8A298; background: #F4F2EE; }}
QCheckBox {{ spacing: 7px; }}

QScrollArea {{ border: none; background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #CFC9BF; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: {LINE}; }}
QTabWidget#dock::pane {{ border: none; background: {CONSOLE_BG}; }}
QTabWidget#dock > QTabBar::tab {{ background: {HEAD}; color: {MUTED}; padding: 6px 16px; border: none;
    font-weight: 700; font-size: 9pt; }}
QTabWidget#dock > QTabBar::tab:selected {{ background: {CONSOLE_BG}; color: #E8EEE9; }}
QWidget#dockCorner {{ background: {HEAD}; }}
QTextEdit#console {{ background: {CONSOLE_BG}; color: {CONSOLE_FG}; border: none; padding: 6px 8px; }}
QLineEdit#termInput {{ background: {CONSOLE_BG}; color: {CONSOLE_FG}; border: none; border-top: 1px solid #243029;
    border-radius: 0; padding: 6px 8px; }}
QFrame#termBar {{ background: #1A201D; border-left: 1px solid #243029; }}
QFrame#termBar QLabel {{ color: #AFC0B6; }}
QFrame#termBar QPushButton {{ background: #26302B; color: {CONSOLE_FG}; border: 1px solid #36433C; }}
QFrame#termBar QPushButton:hover {{ border-color: #7FB3BD; }}
QFrame#termBar QComboBox {{ background: #26302B; color: {CONSOLE_FG}; border: 1px solid #36433C; }}
"""


# ----------------------------------------------------------------- widgets
class Switch(QAbstractButton):
    """An on/off switch for anything long-running. `warn=True` turns amber
    when on (Show Mode), everything else uses the accent."""

    def __init__(self, checked=False, warn=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self._warn = warn
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)

    def sizeHint(self):
        return QSize(40, 22)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        track = QColor(WARN if (on and self._warn) else ACCENT if on else "#C9C3B8")
        if not self.isEnabled():
            track.setAlpha(110)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.right() - d - 3 if on else r.left() + 3
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))


class GridHost(QWidget):
    """Holds the headset tiles and re-flows them into as many columns as fit,
    so a wide window shows the whole fleet in fewer rows instead of
    stretching every tile."""
    TILE_MIN = 58
    SPACING = 6

    def __init__(self, on_wheel):
        super().__init__()
        self._on_wheel = on_wheel
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(self.SPACING)
        self.grid.setVerticalSpacing(self.SPACING)
        self.items = []
        self.shown = []
        self._cols = 0

    def set_items(self, widgets):
        self.items = list(widgets)
        self.shown = list(widgets)
        self._cols = 0
        self.reflow(force=True)

    def show_only(self, widgets):
        self.shown = list(widgets)
        self.reflow(force=True)

    def reflow(self, force=False):
        visible = self.shown
        cols = max(5, (self.width() + self.SPACING) // (self.TILE_MIN + self.SPACING)) if self.width() > 50 else 10
        if cols == self._cols and not force:
            return
        self._cols = cols
        for w in self.items:
            self.grid.removeWidget(w)
            w.setVisible(w in visible)
        for c in range(self.grid.columnCount()):
            self.grid.setColumnStretch(c, 0)
        for i, w in enumerate(visible):
            self.grid.addWidget(w, i // cols, i % cols)
        for c in range(cols):
            self.grid.setColumnStretch(c, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def wheelEvent(self, event):
        self._on_wheel(event)


class Tile(QPushButton):
    """One headset in the grid."""
    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


def restyle(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def label(text, name=None, **props):
    lbl = QLabel(text)
    if name:
        lbl.setObjectName(name)
    for key, value in props.items():
        lbl.setProperty(key, value)
    return lbl


def pill(text, kind):
    p = label(text, "pill", kind=kind)
    p.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return p


def caption(text):
    lbl = label(text, "caption")
    lbl.setWordWrap(True)
    return lbl


def small_caps(text, size=8.0, color=MUTED):
    lbl = QLabel(text.upper())
    font = lbl.font()
    font.setPointSizeF(size)
    font.setBold(True)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.9)
    lbl.setFont(font)
    lbl.setStyleSheet(f"color: {color};")
    return lbl


def button(text, name=None, width=None):
    btn = QPushButton(text)
    if name:
        btn.setObjectName(name)
    if width:
        btn.setMinimumWidth(width)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    return btn


def dot(on):
    d = QLabel()
    d.setFixedSize(9, 9)
    d.setStyleSheet(f"background: {ACCENT if on else DOT_OFF}; border-radius: 4px;")
    return d


def rule():
    line = QFrame()
    line.setObjectName("rule")
    return line


class Card(QFrame):
    """The 'sectioned card' from the Tkinter panel: title strip + body."""

    def __init__(self, title, right=None, help_text=None):
        super().__init__()
        self.setObjectName("card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QFrame()
        head.setObjectName("cardHead")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(14, 9, 10, 9)
        hl.addWidget(small_caps(title))
        hl.addStretch(1)
        for widget in right or []:
            hl.addWidget(widget)
        if help_text:
            hb = button("?", "help")
            hb.setToolTip(help_text)
            hl.addWidget(hb)
        outer.addWidget(head)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(14, 12, 14, 14)
        self.body.setSpacing(10)
        outer.addLayout(self.body)


# ------------------------------------------------------------------ mock data
def mock_fleet():
    rng = random.Random(7)
    pool = [o for o in range(11, 111) if o not in (28, 43, 87)]
    octets = set(rng.sample(pool, 67)) | {28, 43, 87}
    return [f"172.16.16.{o}:5555" for o in sorted(octets)]


FLEET = mock_fleet()
ATTENTION = {"172.16.16.43:5555": "Failed to confirm on last connect",
             "172.16.16.87:5555": "Battery 44 °C"}


# ---------------------------------------------------------------- the window
class Preview(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CXVR Headset Control Panel — PySide6 preview (mock data)")
        self.resize(1280, 800)
        self.selected = "172.16.16.28:5555"
        self.live = {"172.16.16.28:5555"}
        self.tiles = {}

        ground = QWidget()
        ground.setObjectName("ground")
        self.setCentralWidget(ground)
        root = QVBoxLayout(ground)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_strip())
        self.show_bar = label("SHOW MODE IS ON \u2014 watchdogs keep monitoring and logging, but no "
                              "automated action is sent to any headset.", "showBar")
        self.show_bar.hide()
        root.addWidget(self.show_bar)

        body = QHBoxLayout()
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())

        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setHandleWidth(5)
        self.pages = {}
        self.page_host = QWidget()
        self.page_host.setObjectName("page")
        self.page_layout = QVBoxLayout(self.page_host)
        self.page_layout.setContentsMargins(0, 0, 0, 0)
        self.splitter.addWidget(self.page_host)
        self.splitter.addWidget(self._build_dock())
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setSizes([520, 215])
        body.addWidget(self.splitter, 1)
        root.addLayout(body, 1)

        self.show_page("Screen Capture")

    # ---------------------------------------------------------- top strip
    def _build_strip(self):
        self.strip = QFrame()
        self.strip.setObjectName("strip")
        lay = QHBoxLayout(self.strip)
        lay.setContentsMargins(16, 8, 14, 8)
        lay.setSpacing(22)

        brand = QVBoxLayout()
        brand.setSpacing(0)
        brand.addWidget(label("CXVR", "wordmark"))
        brand.addWidget(label("Fleet control", "statCaption"))
        lay.addLayout(brand)

        for value, text, warn in (("68", "connected & stable", False), ("2", "failed to confirm", True),
                                  ("5", "fixed this run", False), ("5 / 70", "total fixed / connected", False)):
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(label(value, "statValue", warn=warn))
            col.addWidget(label(text, "statCaption"))
            lay.addLayout(col)

        tasks = QVBoxLayout()
        tasks.setSpacing(3)
        tasks.addWidget(label("Background tasks", "statCaption"))
        chips = QHBoxLayout()
        chips.setSpacing(5)
        for name in ("Headtracking", "Popup recovery", "Stay awake"):
            chips.addWidget(pill(name, "chip"))
        tasks.addLayout(chips)
        lay.addLayout(tasks)
        lay.addStretch(1)

        show = QHBoxLayout()
        show.setSpacing(8)
        self.show_switch = Switch(warn=True)
        self.show_label = label("Show mode", "showModeLabel", on=False)
        show.addWidget(self.show_switch)
        show.addWidget(self.show_label)
        self.show_switch.toggled.connect(self.set_show_mode)
        lay.addLayout(show)

        for text in ("Stop all tasks", "Interrupt script", "Kill ADB server"):
            lay.addWidget(button(text, "stripBtn"))
        lay.setSpacing(10)
        return self.strip

    def set_show_mode(self, on):
        self.strip.setProperty("showmode", on)
        self.show_label.setProperty("on", on)
        self.show_bar.setVisible(on)
        restyle(self.strip)
        restyle(self.show_label)

    # ------------------------------------------------------------ sidebar
    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(196)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 6, 0, 10)
        lay.setSpacing(1)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = {}
        sections = (("Fleet", ("Connect", "Sleep / Wake", "Volume", "Power", "Heartbeat")),
                    ("Content", ("Content Sync",)),
                    ("View & debug", ("Screen Capture", "Debug Tools")),
                    ("Not yet tested", ("Testing",)))
        for head, items in sections:
            h = small_caps(head, 7.5)
            h.setContentsMargins(18, 14, 0, 4)
            lay.addWidget(h)
            for item in items:
                btn = QPushButton()
                btn.setObjectName("nav")
                btn.setCheckable(True)
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                row = QHBoxLayout(btn)
                row.setContentsMargins(15, 0, 12, 0)
                text = QLabel(item)
                text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                row.addWidget(text)
                row.addStretch(1)
                if item == "Testing":
                    badge = label("7", "navBadge")
                    badge.setFixedHeight(18)
                    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                    row.addWidget(badge)
                btn.setMinimumHeight(33)
                btn._text = text
                self.nav_group.addButton(btn)
                self.nav_buttons[item] = btn
                btn.clicked.connect(lambda _=False, name=item: self.show_page(name))
                lay.addWidget(btn)
        lay.addStretch(1)
        note = label("PySide6 preview · mock data.\nNothing here talks to a headset.", "previewNote")
        note.setContentsMargins(18, 0, 10, 0)
        lay.addWidget(note)
        return side

    def show_page(self, name):
        for key, btn in self.nav_buttons.items():
            btn.setChecked(key == name)
            font = btn._text.font()
            font.setBold(key == name)
            btn._text.setFont(font)
            btn._text.setStyleSheet(f"color: {ACCENT_DARK if key == name else TEXT};")
        while self.page_layout.count():
            w = self.page_layout.takeAt(0).widget()
            if w:
                w.setParent(None)
        builder = {"Screen Capture": self._page_screencap, "Sleep / Wake": self._page_sleepwake}.get(
            name, lambda lay: self._page_placeholder(lay, name))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName("page")
        builder_layout = QVBoxLayout(page)
        builder_layout.setContentsMargins(24, 18, 22, 18)
        builder_layout.setSpacing(14)
        builder(builder_layout)
        builder_layout.addStretch(1)
        scroll.setWidget(page)
        self.page_layout.addWidget(scroll)

    def _page_header(self, lay, title, sub):
        head = QVBoxLayout()
        head.setSpacing(2)
        head.addWidget(label(title, "pageTitle"))
        s = label(sub, "pageSub")
        s.setWordWrap(True)
        head.addWidget(s)
        lay.addLayout(head)

    def _page_placeholder(self, lay, name):
        self._page_header(lay, name, "Not part of this preview \u2014 only Screen Capture and Sleep / Wake "
                                     "are mocked up. The real port would carry every menu over.")

    # ---------------------------------------------------- Screen Capture
    def _page_screencap(self, lay):
        self._page_header(lay, "Screen Capture",
                          f"{len(FLEET)} headsets connected · click to select, double-click to open, "
                          f"← → or the mouse wheel to step through.")
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(self._grid_card(), 1, Qt.AlignmentFlag.AlignTop)
        row.addWidget(self._live_card(), 0, Qt.AlignmentFlag.AlignTop)
        lay.addLayout(row)
        lay.addWidget(self._batch_card())

    def _grid_card(self):
        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("Filter — type 28")
        self.filter_box.setFixedWidth(170)
        self.filter_box.textChanged.connect(self.apply_filter)
        self.filter_box.returnPressed.connect(self.open_selected)
        card = Card("Headsets", right=[self.filter_box, button("Refresh", "small")],
                    help_text="Every connected headset, by the last number of its address.")
        self.grid_host = grid_host = GridHost(self._grid_wheel)
        self.tile_group = QButtonGroup(self)
        self.tile_group.setExclusive(True)
        self.tiles = {}
        for serial in FLEET:
            octet = serial.split(":")[0].rsplit(".", 1)[1]
            t = Tile(f".{octet}")
            t.setObjectName("tile")
            t.setCheckable(True)
            t.setCursor(Qt.CursorShape.PointingHandCursor)
            t.setProperty("live", serial in self.live)
            t.setProperty("attention", serial in ATTENTION)
            t.setToolTip(serial + (f"\n{ATTENTION[serial]}" if serial in ATTENTION else ""))
            t.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            t.setMinimumWidth(GridHost.TILE_MIN)
            t.clicked.connect(lambda _=False, s=serial: self.select(s))
            t.doubleClicked.connect(lambda s=serial: (self.select(s), self.open_selected()))
            self.tile_group.addButton(t)
            self.tiles[serial] = t
        grid_host.set_items(list(self.tiles.values()))
        card.body.addWidget(grid_host)

        legend = QHBoxLayout()
        legend.setSpacing(6)
        for color, border, text in ((ACCENT, ACCENT_DARK, "View open"), ("#FFFFFF", ACCENT_DARK, "Selected"),
                                    (WARN_BG, "#E3B58C", "Needs attention")):
            sw = QLabel()
            sw.setObjectName("swatch")
            sw.setStyleSheet(f"background: {color}; border: {2 if text == 'Selected' else 1}px solid {border};")
            legend.addWidget(sw)
            legend.addWidget(caption(text))
            legend.addSpacing(10)
        legend.addStretch(1)
        card.body.addLayout(legend)
        self.tiles[self.selected].setChecked(True)
        return card

    def _live_card(self):
        card = Card("Live view", help_text="One window per headset. Prev/Next swap the open window to the "
                                          "neighbouring headset in the same place on screen.")
        card.setFixedWidth(330)
        b = card.body
        head = QHBoxLayout()
        head.setSpacing(0)
        ip, port = self.selected.split(":")
        self.big_serial = label(ip, "bigSerial")
        head.addWidget(self.big_serial)
        head.addWidget(label(f":{port}", "port"), 0, Qt.AlignmentFlag.AlignBottom)
        head.addStretch(1)
        b.addLayout(head)
        status = QHBoxLayout()
        status.setSpacing(7)
        status.addWidget(dot(True))
        self.live_status = caption("View open on the laptop screen (eDP-1)")
        status.addWidget(self.live_status, 1)
        b.addLayout(status)

        steps = QHBoxLayout()
        steps.setSpacing(8)
        prev_b, next_b = button("‹  Prev"), button("Next  ›")
        prev_b.clicked.connect(lambda: self.step(-1))
        next_b.clicked.connect(lambda: self.step(1))
        steps.addWidget(prev_b, 1)
        steps.addWidget(next_b, 1)
        b.addLayout(steps)
        acts = QHBoxLayout()
        acts.setSpacing(8)
        open_b = button("Open view", "primary")
        open_b.clicked.connect(self.open_selected)
        acts.addWidget(open_b, 2)
        acts.addWidget(button("Close"), 1)
        b.addLayout(acts)
        b.addWidget(rule())

        dv = QHBoxLayout()
        dv.addWidget(label("Double view", "name"))
        dv.addStretch(1)
        self.double_switch = Switch(checked=True)
        dv.addWidget(self.double_switch)
        b.addLayout(dv)
        b.addWidget(caption("Shows the same picture on a second monitor, view-only. It reuses the one "
                            "connection, so the headset only encodes once."))
        mon = QVBoxLayout()
        mon.setSpacing(4)
        mon.addWidget(caption("Second monitor"))
        self.monitor_combo = QComboBox()
        self.monitor_combo.addItems(["HDMI-1 — 1920×1080, right of laptop", "eDP-1 — laptop screen"])
        mon.addWidget(self.monitor_combo)
        b.addLayout(mon)
        self.double_switch.toggled.connect(self.monitor_combo.setEnabled)
        b.addWidget(rule())

        pic = QHBoxLayout()
        pic.addWidget(caption("Picture"))
        pic.addStretch(1)
        seg_group = QButtonGroup(self)
        for i, text in enumerate(("Single eye", "Full feed")):
            s = QPushButton(text)
            s.setObjectName("seg")
            s.setCheckable(True)
            s.setProperty("pos", "first" if i == 0 else "last")
            s.setChecked(i == 0)
            s.setMinimumWidth(96)
            seg_group.addButton(s)
            pic.addWidget(s)
        pic.setSpacing(0)
        b.addLayout(pic)
        return card

    def _batch_card(self):
        card = Card("Batch preview — rolling, 4 at a time",
                    help_text="Keeps 4 windows open and swaps each one to the next headset on its own timer.")
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(dot(False), 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(label("Batch preview", "name"))
        text.addWidget(caption(f"Stopped. Cycles through all {len(FLEET)} headsets on the right half of the "
                               f"screen, four windows at a time."))
        row.addLayout(text, 1)
        row.addWidget(caption("swap every"))
        spin = QSpinBox()
        spin.setRange(3, 600)
        spin.setValue(10)
        spin.setSuffix(" s")
        spin.setFixedWidth(64)
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        row.addWidget(spin)
        row.addSpacing(10)
        row.addWidget(Switch(False))
        card.body.addLayout(row)
        card.body.addWidget(QCheckBox("Group batch windows under one taskbar item"))
        return card

    # ---------------------------------------------------- Sleep / Wake
    def _page_sleepwake(self, lay):
        self._page_header(lay, "Sleep / Wake", "Put headsets to sleep, wake them, and run the watchdogs "
                                               "that keep them awake and in the app.")
        target = QHBoxLayout()
        target.setSpacing(8)
        target.addWidget(label("Target", "name"))
        combo = QComboBox()
        combo.addItems(["All connected headsets (70)"] + FLEET)
        combo.setMinimumWidth(260)
        target.addWidget(combo)
        target.addWidget(button("Refresh", "small"))
        target.addStretch(1)
        lay.addLayout(target)

        acts = Card("Actions")
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(button("Wake", "primary", 150))
        row.addWidget(button("Sleep", None, 150))
        row.addWidget(button("Screen refresh", None, 150))
        row.addStretch(1)
        acts.body.addLayout(row)
        acts.body.addWidget(caption("Screen refresh sleeps then wakes each headset — the fix for a "
                                    "headset stuck on a black screen."))
        lay.addWidget(acts)

        dogs = Card("Watchdogs", help_text="Long-running helpers. Each keeps going until you switch it off "
                                           "or close the panel.")
        rows = (("Headtracking watchdog", "Re-applies the headtracking fix when a headset reconnects.",
                 True, None, None),
                ("Popup / crash recovery", "Sends HOME when something other than the app is in front.",
                 True, "every", 10),
                ("Stay awake", "Keeps screens from timing out between showings.", True, None, None),
                ("Keepalive pulse", "Wakes every headset on a timer and logs any that stop answering.",
                 False, "every", 1200))
        for i, (name, cap, on, unit, value) in enumerate(rows):
            if i:
                dogs.body.addWidget(rule())
            r = QHBoxLayout()
            r.setSpacing(10)
            r.addWidget(dot(on), 0, Qt.AlignmentFlag.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(2)
            top = QHBoxLayout()
            top.setSpacing(8)
            top.addWidget(label(name, "name"))
            if on:
                top.addWidget(pill("Running", "run"))
            top.addStretch(1)
            col.addLayout(top)
            col.addWidget(caption(cap))
            r.addLayout(col, 1)
            if unit:
                r.addWidget(caption(unit))
                spin = QSpinBox()
                spin.setRange(1, 7200)
                spin.setValue(value)
                spin.setSuffix(" s")
                spin.setFixedWidth(70)
                spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
                r.addWidget(spin)
                r.addSpacing(10)
            r.addWidget(Switch(on))
            dogs.body.addLayout(r)
        lay.addWidget(dogs)

    # -------------------------------------------------------------- dock
    def _build_dock(self):
        self.dock = QTabWidget()
        self.dock.setObjectName("dock")
        self.dock.setDocumentMode(True)
        corner = QWidget()
        corner.setObjectName("dockCorner")
        cl = QHBoxLayout(corner)
        cl.setContentsMargins(0, 3, 10, 3)
        cl.setSpacing(6)
        cl.addWidget(button("Clear", "small"))
        cl.addWidget(button("Hide", "small"))
        self.dock.setCornerWidget(corner, Qt.Corner.TopRightCorner)

        mono = QFont()
        mono.setFamilies(MONO_FONTS)
        mono.setPointSizeF(10)

        log = QTextEdit()
        log.setObjectName("console")
        log.setReadOnly(True)
        log.setFont(mono)
        lines = [
            ("#8FA39A", "[10:41:58] [devices] 70 connected"),
            ("#8FB8C2", "$ scrcpy -s 172.16.16.28:5555 --port 27183:27282 --crop 1224:1232:0:104 "
                        "--v4l2-sink=/dev/video10 --window-x 0 --window-y 0"),
            (CONSOLE_FG, "[scrcpy:172.16.16.28:5555] INFO: Device: [Oculus] Pacific (Android 7.1.2)"),
            (CONSOLE_FG, "[scrcpy:172.16.16.28:5555] INFO: v4l2 sink started to device: /dev/video10"),
            ("#8FB8C2", "$ ffplay -f v4l2 -i /dev/video10 -left 1920 -top 0 -noborder "
                        "-window_title \"CXVR 172.16.16.28 (second view)\""),
            ("#6BCF6B", "[double view] 172.16.16.28:5555 showing on HDMI-1 (view-only)"),
            ("#FF6B6B", "[connect] 172.16.16.43:5555 FAILED to confirm after 3 attempts"),
            (CONSOLE_FG, "[popupWatchdog] 172.16.16.87:5555 expected app not in foreground -- sending HOME"),
        ]
        log.setHtml("<br>".join(f'<span style="color:{c}; white-space:pre-wrap">{t.replace("<", "&lt;")}</span>'
                            for c, t in lines))
        self.dock.addTab(log, "Live log")

        term = QWidget()
        tl = QHBoxLayout(term)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        left = QVBoxLayout()
        left.setSpacing(0)
        console = QTextEdit()
        console.setObjectName("console")
        console.setReadOnly(True)
        console.setFont(mono)
        session = [
            ("#8FA39A", "[── shell on 172.16.16.28:5555 ──]"),
            (CONSOLE_FG, "pacific:/ $ dumpsys battery | grep temperature"),
            (CONSOLE_FG, "  temperature: 331"),
            (CONSOLE_FG, "pacific:/ $ getprop ro.build.version.release"),
            (CONSOLE_FG, "7.1.2"),
            (CONSOLE_FG, "pacific:/ $"),
        ]
        console.setHtml("<br>".join(f'<span style="color:{c}; white-space:pre">{t}</span>' for c, t in session))
        left.addWidget(console, 1)
        entry = QLineEdit()
        entry.setObjectName("termInput")
        entry.setFont(mono)
        entry.setPlaceholderText("›  type a command, Enter to run  (preview: nothing runs)")
        left.addWidget(entry)
        tl.addLayout(left, 1)
        bar = QFrame()
        bar.setObjectName("termBar")
        bar.setFixedWidth(210)
        bl = QGridLayout(bar)
        bl.setContentsMargins(12, 10, 12, 10)
        bl.setHorizontalSpacing(6)
        bl.setVerticalSpacing(6)
        bl.addWidget(QLabel("Shell on"), 0, 0, 1, 2)
        target = QComboBox()
        target.addItems(["172.16.16.28:5555", "This computer"] + FLEET)
        bl.addWidget(target, 1, 0, 1, 2)
        for i, text in enumerate(("Refresh", "Open", "Ctrl+C", "Clear")):
            bl.addWidget(button(text, "small"), 2 + i // 2, i % 2)
        bl.setRowStretch(4, 1)
        tl.addWidget(bar)
        self.dock.addTab(term, "Terminal")
        return self.dock

    # ------------------------------------------------------ interactions
    def select(self, serial):
        self.selected = serial
        if serial in self.tiles:
            self.tiles[serial].setChecked(True)
        if hasattr(self, "big_serial"):
            self.big_serial.setText(serial.split(":")[0])
            open_now = serial in self.live
            self.live_status.setText("View open on the laptop screen (eDP-1)" if open_now
                                     else "No view open — double-click, Enter or Open view")

    def open_selected(self):
        # Stepping replaces the open view rather than adding another window.
        for s in list(self.live):
            self.live.discard(s)
            if s in self.tiles:
                self.tiles[s].setProperty("live", False)
                restyle(self.tiles[s])
        self.live.add(self.selected)
        if self.selected in self.tiles:
            self.tiles[self.selected].setProperty("live", True)
            restyle(self.tiles[self.selected])
        self.select(self.selected)

    def step(self, delta):
        shown = set(self.grid_host.shown)
        visible = [s for s in FLEET if self.tiles[s] in shown] or FLEET
        i = visible.index(self.selected) if self.selected in visible else -1
        self.select(visible[(i + delta) % len(visible)])
        if self.live:
            self.open_selected()

    def _grid_wheel(self, event):
        self.step(1 if event.angleDelta().y() < 0 else -1)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right) and not isinstance(
                QApplication.focusWidget(), (QLineEdit, QSpinBox, QComboBox)):
            self.step(-1 if event.key() == Qt.Key.Key_Left else 1)
            return
        super().keyPressEvent(event)

    def apply_filter(self, text):
        text = text.strip().lstrip(".")
        matches = [serial for serial in FLEET
                   if not text or text in serial.split(":")[0].rsplit(".", 1)[1]]
        self.grid_host.show_only([self.tiles[s] for s in matches])
        if text and len(matches) == 1:
            self.select(matches[0])


def app_font():
    font = QFont()
    font.setFamilies(UI_FONTS)
    font.setPointSizeF(10)
    return font


def main():
    shots = None
    if "--screenshot" in sys.argv:
        shots = sys.argv[sys.argv.index("--screenshot") + 1]
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setFont(app_font())
    app.setStyleSheet(QSS)
    win = Preview()
    if not shots:
        win.show()
        sys.exit(app.exec())

    os.makedirs(shots, exist_ok=True)
    size = tuple(int(v) for v in os.environ.get("SHOT_SIZE", "1280x800").split("x"))
    win.resize(*size)
    win.show()

    def settle():
        for _ in range(8):
            app.processEvents()

    settle()
    win.grab().save(os.path.join(shots, f"1_screen_capture_{size[0]}x{size[1]}.png"))
    win.show_page("Sleep / Wake")
    win.dock.setCurrentIndex(1)
    win.show_switch.setChecked(True)
    settle()
    win.grab().save(os.path.join(shots, f"2_sleep_wake_terminal_show_mode_{size[0]}x{size[1]}.png"))
    QTimer.singleShot(0, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
