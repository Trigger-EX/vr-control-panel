

# ---------------------------------------------------------------------------
# Qt port: compatibility layer
# ---------------------------------------------------------------------------
# The logic at the bottom of ControlPanel is the Tkinter panel's own code. It
# still talks to settings variables, message boxes, file pickers and a handful
# of widgets the way it did under Tk (var.get()/set(), messagebox.askyesno(...),
# button.configure(state="disabled"), toggle.configure(text="Stop ..."),
# combo.configure(values=[...])). The classes here give it that same small API
# on top of Qt, so the logic itself never had to be rewritten.

LOG_MAX_LINES = 20000            # on-screen log only; the scripts' own log files are complete
LOG_PUMP_INTERVAL_MS = 100       # also what lets SIGTERM/SIGINT handlers run (see main())
LOG_PUMP_MAX_ITEMS = 2000        # per tick, so a flood of output can't freeze the window

_MAIN_THREAD = threading.main_thread()
# Tests set CXVR_ASSERT_MAIN_THREAD=1: anything that touches a widget from a
# worker thread then fails loudly instead of misbehaving later. (Tk tolerated
# some of that; Qt can crash.) The panel's worker threads only ever post to
# log_queue, which is what keeps them away from widgets.
ASSERT_MAIN_THREAD = os.environ.get("CXVR_ASSERT_MAIN_THREAD") == "1"
THREAD_VIOLATIONS = []


def _assert_main_thread(where):
    if ASSERT_MAIN_THREAD and threading.current_thread() is not _MAIN_THREAD:
        THREAD_VIOLATIONS.append(where)
        raise AssertionError(f"{where} called from worker thread {threading.current_thread().name}")


class Var:
    """A settings value shared by the logic and whichever widgets show it --
    the Qt stand-in for tk.StringVar / tk.BooleanVar. Plain Python, so a
    worker thread may read it (three settings are read from scrcpy threads).
    Widgets bind to it both ways; only the main thread ever sets one that a
    widget is bound to."""
    _default = ""

    def __init__(self, value=None):
        self._value = self._coerce(self._default if value is None else value)
        self._traces = {}
        self._next_token = 0

    @staticmethod
    def _coerce(value):
        return value

    def get(self):
        return self._value

    def set(self, value):
        value = self._coerce(value)
        if value == self._value and type(value) is type(self._value):
            return
        self._value = value
        if self._traces:
            _assert_main_thread("Var.set (bound to a widget)")
            for callback in list(self._traces.values()):
                callback(value)

    def trace_add(self, callback):
        token = self._next_token
        self._next_token += 1
        self._traces[token] = callback
        return token

    def trace_remove(self, token):
        self._traces.pop(token, None)

    def trace_count(self):
        return len(self._traces)


class StringVar(Var):
    _default = ""

    @staticmethod
    def _coerce(value):
        return value if isinstance(value, str) else str(value)


class BooleanVar(Var):
    _default = False

    @staticmethod
    def _coerce(value):
        # Same rules as Tcl's getboolean, which is what tk.BooleanVar.get() uses.
        if isinstance(value, str):
            text = value.strip().lower()
            if text in ("1", "true", "yes", "on"):
                return True
            if text in ("0", "false", "no", "off", ""):
                return False
            raise ValueError(f"expected a boolean, got {value!r}")
        return bool(value)


def _bind(widget, var, on_change):
    """Calls on_change(value) whenever var changes, for as long as the widget
    exists. The link is dropped when the widget is destroyed, so pages that are
    rebuilt every time they're opened never pile up stale bindings."""
    token = var.trace_add(lambda value: on_change(value) if _qt_alive(widget) else None)
    widget.destroyed.connect(lambda *_: var.trace_remove(token))
    widget._cxvr_var = var


def _mnemonic_safe(text):
    """Qt treats a single & in button and checkbox text as a keyboard-shortcut
    marker and hides it ("Purge & Reconnect" would lose its &)."""
    return str(text).replace("&", "&&")


# ------------------------------------------------------------------ dialogs
_dialog_parent_ref = []   # the main window, once it exists


def _dialog_parent():
    parent = _dialog_parent_ref[0] if _dialog_parent_ref else None
    return parent if parent is not None and _qt_alive(parent) else None


class _MessageBoxShim:
    """tkinter.messagebox's names and wording, shown with QMessageBox. Every
    yes/no confirmation defaults to No, so a reflexive Enter never starts a
    sleep, a mute, a reboot or a delete (the Tkinter panel defaulted to Yes)."""

    @staticmethod
    def _show(icon, title, message, buttons, default, escape):
        _assert_main_thread("messagebox")
        box = QMessageBox(icon, str(title or ""), str(message or ""), buttons, _dialog_parent())
        box.setTextFormat(Qt.TextFormat.PlainText)
        box.setDefaultButton(default)
        box.setEscapeButton(escape)
        return box.exec()

    def showinfo(self, title=None, message=None, **options):
        self._show(QMessageBox.Icon.Information, title, message, QMessageBox.StandardButton.Ok,
                   QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Ok)
        return "ok"

    def showwarning(self, title=None, message=None, **options):
        self._show(QMessageBox.Icon.Warning, title, message, QMessageBox.StandardButton.Ok,
                   QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Ok)
        return "ok"

    def showerror(self, title=None, message=None, **options):
        self._show(QMessageBox.Icon.Critical, title, message, QMessageBox.StandardButton.Ok,
                   QMessageBox.StandardButton.Ok, QMessageBox.StandardButton.Ok)
        return "ok"

    def askyesno(self, title=None, message=None, **options):
        yes, no = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No
        return self._show(QMessageBox.Icon.Question, title, message, yes | no, no, no) == yes


class _FileDialogShim:
    """tkinter.filedialog's names; returns "" when cancelled, like Tk."""

    @staticmethod
    def askdirectory(title=None, **options):
        _assert_main_thread("filedialog")
        return QFileDialog.getExistingDirectory(_dialog_parent(), str(title or "")) or ""

    @staticmethod
    def askopenfilename(title=None, **options):
        _assert_main_thread("filedialog")
        path, _filter = QFileDialog.getOpenFileName(_dialog_parent(), str(title or ""))
        return path or ""


messagebox = _MessageBoxShim()
filedialog = _FileDialogShim()


# ------------------------------------------------------------------ widgets
class Button(QPushButton):
    """A push button that also answers the few Tk calls the logic makes:
    configure(state=/text=), cget("text"/"state") and invoke()."""

    def __init__(self, text="", command=None, kind=None, parent=None, tooltip=None):
        super().__init__(parent)
        self._label = ""
        self._command = command
        self.set_label(text)
        if kind:
            self.setObjectName(kind)
        if tooltip:
            self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(self._on_clicked)

    def _on_clicked(self, *_):
        if self._command is not None:
            self._command()

    def set_label(self, text):
        self._label = str(text)
        self.setText(_mnemonic_safe(text))

    def label(self):
        return self._label

    def configure(self, cnf=None, **kw):
        _assert_main_thread("Button.configure")
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        if "state" in kw:
            self.setEnabled(str(kw["state"]) != "disabled")
        if "text" in kw:
            self.set_label(kw["text"])
        if "command" in kw:
            self._command = kw["command"]

    config = configure

    def cget(self, key):
        if key == "text":
            return self._label
        if key == "state":
            return "normal" if self.isEnabled() else "disabled"
        raise KeyError(key)

    def invoke(self):
        if self.isEnabled():
            self.click()


class Entry(QLineEdit):
    """A text field bound to a StringVar (ttk.Entry with textvariable=)."""

    def __init__(self, var, chars=None, parent=None):
        super().__init__(parent)
        self._var = var
        self._syncing = False
        self.setText(var.get())
        self.textChanged.connect(self._to_var)
        _bind(self, var, self._from_var)
        if chars:
            self.setFixedWidth(self.fontMetrics().horizontalAdvance("0" * chars) + 22)

    def _to_var(self, text):
        if not self._syncing:
            self._var.set(text)

    def _from_var(self, value):
        if self.text() != value:
            self._syncing = True
            try:
                self.setText(value)
            finally:
                self._syncing = False


class Check(QCheckBox):
    """A checkbox bound to a BooleanVar. Like a ttk.Checkbutton, clicking sets
    the variable first and then runs the command."""

    def __init__(self, text, var, command=None, parent=None):
        super().__init__(_mnemonic_safe(text), parent)
        self._label = str(text)
        self._var = var
        self._command = command
        self.setChecked(bool(var.get()))
        self.clicked.connect(self._on_clicked)
        _bind(self, var, lambda value: self.setChecked(bool(value)) if self.isChecked() != bool(value) else None)

    def _on_clicked(self, checked):
        self._var.set(bool(checked))
        if self._command is not None:
            self._command()

    def label(self):
        return self._label

    def invoke(self):
        self.click()


class Combo(QComboBox):
    """A read-only dropdown bound to a StringVar (a readonly ttk.Combobox).
    configure(values=[...]) replaces the list, as it did under Tk. A value the
    logic sets that isn't in the list (yet) is still shown, greyed, rather than
    silently replaced. The mouse wheel never changes it: scrolling the page
    over a headset picker must not quietly retarget an action."""

    def __init__(self, var, values=(), chars=24, parent=None):
        super().__init__(parent)
        self._var = var
        self._values = [str(v) for v in values]
        self.addItems(self._values)
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(chars)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.activated.connect(self._on_activated)
        _bind(self, var, self._show_value)
        self._show_value(var.get())

    def _on_activated(self, index):
        if 0 <= index < len(self._values):
            self._var.set(self._values[index])

    def _show_value(self, value):
        index = self._values.index(value) if value in self._values else -1
        self.setPlaceholderText("" if index >= 0 else str(value))
        self.setCurrentIndex(index)

    def configure(self, cnf=None, **kw):
        _assert_main_thread("Combo.configure")
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        if "values" in kw:
            self._values = [str(v) for v in kw["values"]]
            self.clear()
            self.addItems(self._values)
            self._show_value(self._var.get())
        if "state" in kw:
            self.setEnabled(str(kw["state"]) != "disabled")

    config = configure

    def cget(self, key):
        if key == "values":
            return tuple(self._values)
        raise KeyError(key)

    def choose(self, value):
        """What picking an entry with the mouse does (used by tests)."""
        self._on_activated(self._values.index(value))

    def wheelEvent(self, event):
        event.ignore()

    def paintEvent(self, event):
        super().paintEvent(event)
        # The style sheet hides the native drop-down arrow (it drew a dark edge);
        # draw a plain chevron instead so it still reads as a dropdown.
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = painter.pen()
        pen.setColor(QColor(UI_MUTED if self.isEnabled() else "#B8B2A8"))
        pen.setWidthF(1.6)
        painter.setPen(pen)
        cx, cy = self.width() - 13, self.height() / 2
        painter.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])


class SpinEntry(QWidget):
    """A number field with − and + buttons, bound to a StringVar -- the
    ttk.Spinbox equivalent. Like the Tk one it accepts any text, because the
    logic validates the text itself and reports a bad value in its own words.
    Up/Down in the field step it too; the mouse wheel never does."""

    def __init__(self, var, lo, hi, chars=4, parent=None):
        super().__init__(parent)
        self._lo, self._hi = lo, hi
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(3)
        self.down_button = QToolButton()
        self.down_button.setObjectName("stepBtn")
        self.down_button.setText("\u2212")
        self.down_button.setAutoRepeat(True)
        self.down_button.clicked.connect(lambda: self.step(-1))
        self.entry = Entry(var, chars=chars)
        self.entry.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.entry.keyPressEvent = self._entry_key
        self.up_button = QToolButton()
        self.up_button.setObjectName("stepBtn")
        self.up_button.setText("+")
        self.up_button.setAutoRepeat(True)
        self.up_button.clicked.connect(lambda: self.step(1))
        for widget in (self.down_button, self.entry, self.up_button):
            row.addWidget(widget)
        self._cxvr_var = var

    def step(self, steps):
        try:
            value = int(self.entry.text().strip())
        except ValueError:
            value = self._lo if steps > 0 else self._hi
        else:
            value += steps
        self.entry.setText(str(min(self._hi, max(self._lo, value))))

    def _entry_key(self, event):
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self.step(1 if event.key() == Qt.Key.Key_Up else -1)
            return
        QLineEdit.keyPressEvent(self.entry, event)


class Switch(QAbstractButton):
    """The on/off switch drawing shared by ToggleSwitch and VarSwitch.
    `warn=True` turns amber when on (Show Mode); everything else uses the accent."""

    def __init__(self, warn=False, parent=None):
        super().__init__(parent)
        self._warn = warn
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setFixedSize(40, 22)

    def _is_on(self):
        return self.isChecked()

    def sizeHint(self):
        return QSize(40, 22)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self._is_on()
        track = QColor(UI_WARN if (on and self._warn) else UI_ACCENT if on else "#C9C3B8")
        if not self.isEnabled():
            track.setAlpha(110)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        knob = rect.height() - 6
        x = rect.right() - knob - 3 if on else rect.left() + 3
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(QRectF(x, rect.top() + 3, knob, knob))
        if self.hasFocus():
            painter.setPen(QColor(UI_ACCENT_DARK))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5),
                                    rect.height() / 2 + 1, rect.height() / 2 + 1)


class ToggleSwitch(Switch):
    """Start/Stop for anything long-running (watchdogs, batch preview, the ADB
    debug log) -- the Qt stand-in for the Tk panel's ToggleButton.

    It never flips itself when clicked: the click only runs the action, and
    the action says what happened by relabelling it the way the Tk code always
    has -- configure(text="Stop ...") means running, "Start ..." means stopped.
    So a start that's refused (a bad interval, an arm confirmation answered No)
    leaves it off. cget("text") answers "Start" or "Stop", like ToggleButton."""

    def __init__(self, running=False, on_change=None, command=None, parent=None):
        super().__init__(parent=parent)
        self._running = bool(running)
        self._on_change = on_change
        self._command = command
        self.clicked.connect(self._on_clicked)
        self._refresh_tip()

    def _is_on(self):
        return self._running

    def _on_clicked(self, *_):
        if self._command is not None:
            self._command()

    def _refresh_tip(self):
        self.setToolTip("Running — click to stop" if self._running else "Stopped — click to start")
        self.setAccessibleName("Stop" if self._running else "Start")

    def configure(self, cnf=None, **kw):
        _assert_main_thread("ToggleSwitch.configure")
        if isinstance(cnf, dict):
            kw = {**cnf, **kw}
        if "text" in kw:
            self._running = str(kw["text"]).strip().lower().startswith("stop")
            self._refresh_tip()
            self.update()
            if self._on_change is not None:
                try:
                    self._on_change(self._running)
                except RuntimeError:
                    pass   # its row was already torn down by a page switch
        if "command" in kw:
            self._command = kw["command"]
        if "state" in kw:
            self.setEnabled(str(kw["state"]) != "disabled")

    config = configure

    def cget(self, key):
        if key == "text":
            return "Stop" if self._running else "Start"
        if key == "state":
            return "normal" if self.isEnabled() else "disabled"
        raise KeyError(key)

    def invoke(self):
        if self.isEnabled():
            self.click()


class VarSwitch(Switch):
    """A switch bound to a BooleanVar (the Show Mode switch). Like a
    ttk.Checkbutton: clicking sets the variable, then runs the command."""

    def __init__(self, var, command=None, warn=False, parent=None):
        super().__init__(warn=warn, parent=parent)
        self._var = var
        self._command = command
        self.setCheckable(True)
        self.setChecked(bool(var.get()))
        self.clicked.connect(self._on_clicked)
        _bind(self, var, lambda value: self.setChecked(bool(value)) if self.isChecked() != bool(value) else None)

    def _on_clicked(self, checked):
        self._var.set(bool(checked))
        if self._command is not None:
            self._command()

    def invoke(self):
        self.click()
