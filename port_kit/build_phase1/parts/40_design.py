

# ---------------------------------------------------------------------------
# Qt port: design system
# ---------------------------------------------------------------------------
# The same palette as the Tkinter panel (UI_* above) plus a few Qt-only tints,
# on top of Qt's Fusion style so it looks the same on any desktop. Rules kept
# from the Tk layout: one primary button per page, the danger style only for
# what can't be undone remotely, actions first and settings after, and long
# explanations behind a "?" button.
UI_SURFACE = "#FBFAF7"
UI_ACCENT_TINT = "#DCE8EA"
UI_SIDEBAR = "#EBE7E0"
UI_CONSOLE_BG = "#101412"
UI_CONSOLE_FG = "#D8E0DA"
UI_LOG_FAIL = "#ff6b6b"
UI_LOG_OK = "#6bcf6b"

UI_FONTS = ["Ubuntu Sans", "Ubuntu", "Noto Sans", "Cantarell", "DejaVu Sans"]
MONO_FONTS = ["Ubuntu Sans Mono", "Ubuntu Mono", "DejaVu Sans Mono", "Monospace"]

QSS = f"""
QMainWindow, QWidget#page {{ background: {UI_GROUND}; }}
QLabel {{ color: {UI_TEXT}; background: transparent; }}
QToolTip {{ color: {UI_TEXT}; background: #FFFFFF; border: 1px solid {UI_LINE}; padding: 4px; }}

QFrame#strip {{ background: {UI_HEAD}; border-bottom: 1px solid {UI_LINE}; }}
QFrame#strip[showmode="true"] {{ background: {UI_WARN_BG}; border-bottom: 1px solid #E3B58C; }}
QLabel#statValue {{ font-size: 13pt; font-weight: 700; }}
QLabel#statValue[warn="true"] {{ color: {UI_WARN}; }}
QLabel#statCaption {{ color: {UI_MUTED}; font-size: 8pt; }}
QLabel#wordmark {{ color: {UI_ACCENT}; font-size: 12pt; font-weight: 800; }}
QLabel#showModeLabel {{ font-weight: 700; }}
QLabel#showModeLabel[on="true"] {{ color: {UI_WARN}; }}
QLabel#showBar {{ background: {UI_WARN}; color: #FFFFFF; font-weight: 700; font-size: 9pt; padding: 5px 16px; }}

QFrame#sidebar {{ background: {UI_SIDEBAR}; border-right: 1px solid {UI_LINE}; }}
QScrollArea#sideScroll {{ background: {UI_SIDEBAR}; border: none; }}
QPushButton#nav {{ text-align: left; padding: 6px 10px 6px 14px; border: none;
    border-left: 3px solid transparent; border-radius: 0; background: transparent; color: {UI_TEXT}; }}
QPushButton#nav:hover {{ background: #E1DCD3; }}
QPushButton#nav:checked {{ background: {UI_ACCENT_TINT}; border-left: 3px solid {UI_ACCENT};
    color: {UI_ACCENT_DARK}; font-weight: 700; }}
QLabel#navBadge {{ background: {UI_WARN_BG}; color: {UI_WARN}; border-radius: 8px; padding: 0 6px;
    font-size: 8pt; font-weight: 700; }}
QLabel#navLater {{ color: #8C867C; font-size: 8pt; }}
QLabel#sideNote {{ color: {UI_MUTED}; font-size: 8pt; }}
QPushButton#paneToggle {{ text-align: left; padding: 3px 8px; border: 1px solid transparent; border-radius: 5px;
    color: {UI_MUTED}; background: transparent; font-size: 9pt; }}
QPushButton#paneToggle:hover {{ border-color: #C4BEB3; }}
QPushButton#paneToggle:checked {{ color: {UI_ACCENT_DARK}; background: {UI_ACCENT_TINT}; }}
QToolButton#stepBtn {{ border: 1px solid #C4BEB3; border-radius: 6px; background: #FFFFFF; min-width: 24px;
    min-height: 26px; font-weight: 700; color: {UI_TEXT}; }}
QToolButton#stepBtn:hover {{ border-color: {UI_ACCENT}; }}

QLabel#pageTitle {{ font-size: 15pt; font-weight: 700; }}
QLabel#caption {{ color: {UI_MUTED}; font-size: 9pt; }}
QLabel#caption[variant="italic"] {{ font-style: italic; }}
QLabel#caption[variant="notice"] {{ color: {UI_WARN}; font-style: italic; }}
QLabel#field {{ font-weight: 700; }}
QLabel#name {{ font-weight: 700; }}

QFrame#card {{ background: {UI_SURFACE}; border: 1px solid {UI_LINE}; border-radius: 8px; }}
QFrame#cardHead {{ background: transparent; border: none; border-bottom: 1px solid #E6E2DA; }}
QFrame#rule {{ background: #E6E2DA; border: none; max-height: 1px; min-height: 1px; }}
QFrame#sectionHead {{ background: transparent; border: none; }}
QFrame#sectionHead:hover {{ background: #F1EEE8; border-radius: 8px; }}
QFrame#banner {{ background: {UI_WARN_BG}; border: 1px solid {UI_WARN}; border-radius: 6px; }}
QFrame#banner QLabel {{ color: {UI_WARN}; }}
QFrame#placeholder {{ background: {UI_SURFACE}; border: 1px dashed #BDB6AA; border-radius: 8px; }}

QPushButton {{ background: #FFFFFF; border: 1px solid #C4BEB3; border-radius: 6px; padding: 6px 14px;
    color: {UI_TEXT}; }}
QPushButton:hover {{ border-color: {UI_ACCENT}; }}
QPushButton:pressed {{ background: #EFEDE8; }}
QPushButton:focus {{ border-color: {UI_ACCENT}; }}
QPushButton:disabled {{ color: #A8A298; border-color: #DDD8CF; background: #F7F5F1; }}
QPushButton#big {{ padding: 9px 14px; }}
QPushButton#primary {{ background: {UI_ACCENT}; color: #FFFFFF; border: 1px solid {UI_ACCENT_DARK};
    font-weight: 700; padding: 9px 14px; }}
QPushButton#primary:hover {{ background: {UI_ACCENT_DARK}; }}
QPushButton#primary:disabled {{ background: #9DB5BA; color: #EEF3F4; border-color: #9DB5BA; }}
QPushButton#danger {{ color: {UI_WARN}; border: 1px solid {UI_WARN}; font-weight: 700; padding: 9px 14px; }}
QPushButton#danger:hover {{ background: {UI_WARN_BG}; }}
QPushButton#danger:disabled {{ color: #C9A88C; border-color: #E3CDB8; background: #F7F5F1; }}
QPushButton#small {{ padding: 3px 10px; font-size: 9pt; }}
QPushButton#stripBtn {{ padding: 4px 10px; font-size: 9pt; background: #F7F5F1; }}
QPushButton#link {{ border: none; background: transparent; color: {UI_ACCENT}; padding: 2px 0; font-weight: 700;
    text-align: left; }}
QPushButton#link:hover {{ text-decoration: underline; }}
QPushButton#help {{ padding: 0; min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px;
    border-radius: 10px; font-weight: 700; color: {UI_MUTED}; font-size: 9pt; }}

QLabel#pill {{ border-radius: 8px; padding: 1px 8px; font-size: 8pt; font-weight: 700; }}
QLabel#pill[kind="run"] {{ background: {UI_ACCENT}; color: #FFFFFF; }}
QLabel#pill[kind="idle"] {{ background: {UI_PILL_IDLE_BG}; color: {UI_PILL_IDLE_FG}; }}
QLabel#pill[kind="armed"] {{ background: {UI_WARN_BG}; color: {UI_WARN}; }}
QLabel#pill[kind="chip"] {{ background: #F7F5F1; color: {UI_ACCENT_DARK}; border: 1px solid #BFD3D7; }}
QLabel#dot {{ border-radius: 4px; background: {UI_DOT_OFF}; }}
QLabel#dot[on="true"] {{ background: {UI_ACCENT}; }}

QLineEdit, QComboBox {{ background: #FFFFFF; border: 1px solid #C4BEB3; border-radius: 6px;
    padding: 4px 8px; min-height: 20px; color: {UI_TEXT}; }}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {UI_ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox:disabled, QLineEdit:disabled {{ color: #A8A298; background: #F4F2EE; }}
QCheckBox {{ spacing: 7px; }}

QScrollArea#pageScroll {{ border: none; background: {UI_GROUND}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #CFC9BF; border-radius: 3px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #CFC9BF; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QMainWindow::separator {{ background: {UI_LINE}; width: 4px; height: 4px; }}
QMainWindow::separator:hover {{ background: #B7B0A5; }}
QMainWindow > QTabBar::tab {{ background: {UI_HEAD}; color: {UI_MUTED}; padding: 5px 16px; border: none;
    font-weight: 700; font-size: 9pt; }}
QMainWindow > QTabBar::tab:selected {{ background: {UI_CONSOLE_BG}; color: #E8EEE9; }}
QFrame#dockTitle {{ background: {UI_HEAD}; border-bottom: 1px solid {UI_LINE}; }}
QToolButton#dockBtn {{ border: 1px solid transparent; border-radius: 4px; padding: 0 5px; color: {UI_MUTED};
    background: transparent; }}
QToolButton#dockBtn:hover {{ border-color: #C4BEB3; background: #F7F5F1; }}
QPlainTextEdit#console {{ background: {UI_CONSOLE_BG}; color: {UI_CONSOLE_FG}; border: none; padding: 4px 6px; }}
QFrame#consoleNote {{ background: {UI_CONSOLE_BG}; }}
QFrame#consoleNote QLabel {{ color: #AFC0B6; }}
"""


def app_font():
    font = QFont()
    font.setFamilies(UI_FONTS)
    font.setPointSizeF(10)
    return font


def mono_font():
    font = QFont()
    font.setFamilies(MONO_FONTS)
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSizeF(10)
    return font


def restyle(widget):
    """Re-applies the style sheet after a dynamic property changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


def small_caps(text, size=8.0, color=UI_MUTED):
    label = QLabel(str(text).upper())
    font = label.font()
    font.setPointSizeF(size)
    font.setBold(True)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.9)
    label.setFont(font)
    label.setStyleSheet(f"color: {color};")
    return label


def rule():
    line = QFrame()
    line.setObjectName("rule")
    return line


class Caption(QLabel):
    """Muted explanatory text that wraps to whatever width it's given. Unlike
    Tk, Qt re-wraps word-wrapped labels natively, so none of the old re-wrap
    workarounds (and none of the freezes they caused) are needed."""

    def __init__(self, text="", var=None, variant=None, parent=None):
        super().__init__(parent)
        self.setObjectName("caption")
        self.setWordWrap(True)
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        if variant:
            self.setProperty("variant", variant)
        if var is not None:
            self.setText(var.get())
            _bind(self, var, self.setText)
        else:
            self.setText(str(text))


def field_label(text):
    label = QLabel(str(text))
    label.setObjectName("field")
    return label


def info_button(title, text):
    """The small ? that shows a longer explanation on demand (the HELP texts)."""
    return Button("?", lambda: messagebox.showinfo(title, text, parent=_dialog_parent()), kind="help",
                  tooltip="More about this")


class Card(QFrame):
    """A titled section: tinted title strip, then a padded body (card.body is a
    QVBoxLayout). `right` widgets go on the right of the title strip; `help`
    is a (title, text) pair shown by a ? button there."""

    def __init__(self, title, right=None, help=None, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.title = str(title)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        head = QFrame()
        head.setObjectName("cardHead")
        self.head_layout = QHBoxLayout(head)
        self.head_layout.setContentsMargins(14, 7, 10, 7)
        self.head_layout.setSpacing(6)
        self.head_layout.addWidget(small_caps(title))
        self.head_layout.addStretch(1)
        for widget in right or []:
            self.head_layout.addWidget(widget)
        if help:
            self.head_layout.addWidget(info_button(*help))
        outer.addWidget(head)
        self.body = QVBoxLayout()
        self.body.setContentsMargins(14, 11, 14, 13)
        self.body.setSpacing(9)
        outer.addLayout(self.body)


class Collapsible(QFrame):
    """A section that starts collapsed to one line (title and a summary).
    Open/closed is remembered for the session in `state` (a dict), so coming
    back to a page keeps it."""

    def __init__(self, key, title, summary, state, parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self._key, self._state = key, state
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header = QFrame()
        self.header.setObjectName("sectionHead")
        self.header.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.header.mousePressEvent = lambda event: self.invoke()
        self.header.keyPressEvent = self._header_key
        hl = QHBoxLayout(self.header)
        hl.setContentsMargins(14, 8, 12, 8)
        hl.setSpacing(10)
        self._arrow = QLabel()
        self._arrow.setFixedWidth(12)
        hl.addWidget(self._arrow, 0, Qt.AlignmentFlag.AlignTop)
        hl.addWidget(small_caps(title), 0, Qt.AlignmentFlag.AlignTop)
        self._summary = Caption(summary)
        hl.addWidget(self._summary, 1)
        outer.addWidget(self.header)
        self.body_widget = QWidget()
        self.body = QVBoxLayout(self.body_widget)
        self.body.setContentsMargins(14, 4, 14, 13)
        self.body.setSpacing(9)
        outer.addWidget(self.body_widget)
        self._render()

    def is_open(self):
        return bool(self._state.get(self._key, False))

    def _render(self):
        self._arrow.setText("▾" if self.is_open() else "▸")
        self.body_widget.setVisible(self.is_open())

    def invoke(self):
        self._state[self._key] = not self.is_open()
        self._render()

    def _header_key(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.invoke()
        else:
            QFrame.keyPressEvent(self.header, event)


def pill(text, kind):
    label = QLabel(str(text))
    label.setObjectName("pill")
    label.setProperty("kind", kind)
    label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    return label


class ModePill(QLabel):
    """Observe only / Armed, following a BooleanVar."""

    def __init__(self, var, armed_text="Armed", idle_text="Observe only", parent=None):
        super().__init__(parent)
        self.setObjectName("pill")
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._var, self._armed_text, self._idle_text = var, armed_text, idle_text
        _bind(self, var, lambda value: self.refresh())
        self.refresh()

    def refresh(self):
        armed = bool(self._var.get())
        self.setText(self._armed_text if armed else self._idle_text)
        self.setProperty("kind", "armed" if armed else "idle")
        restyle(self)


class ToggleRow(QWidget):
    """One long-running task: status dot, name (+ a Running pill and an
    optional ?), a caption, optional inline settings, and its ToggleSwitch on
    the right. `settings_layout` is where a page puts inline settings."""

    def __init__(self, title, caption=None, caption_var=None, info=None, running=False, parent=None):
        super().__init__(parent)
        self.title = str(title)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self._dot = QLabel()
        self._dot.setObjectName("dot")
        self._dot.setFixedSize(9, 9)
        dot_box = QVBoxLayout()
        dot_box.setContentsMargins(0, 6, 0, 0)
        dot_box.addWidget(self._dot)
        dot_box.addStretch(1)
        row.addLayout(dot_box)
        text = QVBoxLayout()
        text.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(8)
        name = QLabel(self.title)
        name.setObjectName("name")
        top.addWidget(name)
        self._pill = pill("Running", "run")
        top.addWidget(self._pill)
        if info:
            top.addWidget(info_button(title, info))
        top.addStretch(1)
        text.addLayout(top)
        if caption or caption_var is not None:
            text.addWidget(Caption(caption or "", var=caption_var))
        row.addLayout(text, 1)
        self.settings_layout = QHBoxLayout()
        self.settings_layout.setSpacing(6)
        row.addLayout(self.settings_layout)
        self._switch_box = QVBoxLayout()
        self._switch_box.setContentsMargins(0, 2, 0, 0)
        row.addLayout(self._switch_box)
        self.set_running(running)

    def set_switch(self, switch):
        self.switch = switch
        self._switch_box.addWidget(switch)
        self._switch_box.addStretch(1)

    def set_running(self, running):
        self._pill.setVisible(bool(running))
        self._dot.setProperty("on", bool(running))
        restyle(self._dot)


class TestingBanner(QFrame):
    """The amber strip on a page whose feature hasn't been marked tested yet."""

    def __init__(self, what, destination, on_mark, parent=None):
        super().__init__(parent)
        self.setObjectName("banner")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 8, 8)
        row.setSpacing(10)
        text = QLabel(f"{what} hasn't been marked tested yet, so it only lives under Testing. "
                      f"Marking it tested moves it to {destination}.")
        text.setWordWrap(True)
        text.setTextFormat(Qt.TextFormat.PlainText)
        row.addWidget(text, 1)
        row.addWidget(Button("Mark tested", on_mark, kind="small"), 0, Qt.AlignmentFlag.AlignVCenter)


class ChipRow(QWidget):
    """The running background tasks as chips, in one line. If they don't all
    fit, the last visible chip becomes "+N more" (its tooltip lists them all),
    so a long list can never force the window wider."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(5)
        self._chips = []
        self._more = pill("", "chip")
        self._none = QLabel("none running")
        self._none.setObjectName("statCaption")
        self._row.addWidget(self._none)
        self._row.addWidget(self._more)
        self._row.addStretch(1)
        self._names = []
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def set_names(self, names):
        for chip in self._chips:
            self._row.removeWidget(chip)
            chip.hide()
            chip.deleteLater()
        self._names = list(names)
        self._chips = [pill(name, "chip") for name in self._names]
        for i, chip in enumerate(self._chips):
            self._row.insertWidget(1 + i, chip)
            chip.ensurePolished()   # measure with the style sheet applied, not the bare label
        self.setToolTip("\n".join(self._names))
        self._fit()
        QTimer.singleShot(0, self._fit)

    def names(self):
        return list(self._names)

    def minimumSizeHint(self):
        return QSize(60, max(self._more.sizeHint().height(), self._none.sizeHint().height()))

    def sizeHint(self):
        width = sum(c.sizeHint().width() + 5 for c in self._chips) or self._none.sizeHint().width()
        return QSize(width, self.minimumSizeHint().height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def _fit(self):
        if not _qt_alive(self):
            return
        self._more.ensurePolished()
        self._none.setVisible(not self._chips)
        available = self.width()
        used, shown = 0, 0
        for i, chip in enumerate(self._chips):
            need = chip.sizeHint().width() + 5
            rest = len(self._chips) - i - 1
            reserve = 0
            if rest:
                self._more.setText(f"+{rest} more")
                reserve = self._more.sizeHint().width() + 5
            if used + need + reserve <= available or (i == 0 and not rest and need <= available):
                chip.show()
                used += need
                shown += 1
            else:
                break
        for chip in self._chips[shown:]:
            chip.hide()
        hidden = len(self._chips) - shown
        self._more.setText(f"+{hidden} more")
        self._more.setVisible(hidden > 0)


class StatCell(QWidget):
    """One status number with its caption: value above caption (wide strip) or
    side by side (compact strip). configure(foreground=...) is what the Tk
    logic calls to flag a non-zero 'failed' count."""

    def __init__(self, var, caption, parent=None):
        super().__init__(parent)
        self.value = QLabel()
        self.value.setObjectName("statValue")
        self.value.setText(var.get())
        _bind(self.value, var, self.value.setText)
        self.caption = QLabel(caption)
        self.caption.setObjectName("statCaption")
        for label in (self.value, self.caption):
            label.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        self._layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._layout.addWidget(self.value, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self._layout.addWidget(self.caption, 0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.set_compact(False)

    def set_compact(self, compact):
        self._layout.setDirection(QBoxLayout.Direction.LeftToRight if compact
                                  else QBoxLayout.Direction.TopToBottom)
        self._layout.setSpacing(6 if compact else 0)

    def configure(self, cnf=None, **kw):
        _assert_main_thread("StatCell.configure")
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        if "foreground" in kw:
            self.value.setProperty("warn", bool(kw["foreground"]))
            restyle(self.value)

    config = configure


class DockTitle(QFrame):
    """A compact title bar for the Live log / Terminal panes: name, any extra
    buttons (Clear), then float and close. Dragging it or double-clicking it
    works as on any dock, because it leaves those mouse events to the dock."""

    def __init__(self, dock, title, extras=(), parent=None):
        super().__init__(parent)
        self.setObjectName("dockTitle")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 2, 6, 2)
        row.setSpacing(4)
        row.addWidget(small_caps(title, 7.5))
        self.status = QLabel("")
        self.status.setObjectName("statCaption")
        row.addWidget(self.status)
        row.addStretch(1)
        for widget in extras:
            row.addWidget(widget)
        float_btn = QToolButton()
        float_btn.setObjectName("dockBtn")
        float_btn.setText("⧉")
        float_btn.setToolTip("Float this pane (drag it to the other monitor); double-click its title to dock it again")
        float_btn.clicked.connect(lambda: dock.setFloating(not dock.isFloating()))
        close_btn = QToolButton()
        close_btn.setObjectName("dockBtn")
        close_btn.setText("✕")
        close_btn.setToolTip("Hide this pane (bring it back from the bottom of the sidebar)")
        close_btn.clicked.connect(dock.close)
        row.addWidget(float_btn)
        row.addWidget(close_btn)
