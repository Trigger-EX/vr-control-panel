

# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------
# Sidebar: (section, ((page key, label), ...)). Delete Video only shows once
# it's marked tested; Testing carries a badge with the number still untested.
NAV_SECTIONS = (
    ("Fleet", (("connect", "Connect"), ("sleepwake", "Sleep / Wake"), ("volume", "Volume"),
               ("power", "Power"), ("heartbeat", "Heartbeat"))),
    ("Content", (("sync", "Content Sync"), ("delete_video", "Delete Video"))),
    ("View & debug", (("screencap", "Screen Capture"), ("debug", "Debug Tools"))),
    ("Not yet tested", (("testing", "Testing"),)),
)
NAV_OPENERS = {
    "connect": "show_menu_connect", "sleepwake": "show_menu_sleepwake", "volume": "show_menu_volume",
    "power": "show_menu_power", "heartbeat": "show_menu_heartbeat", "sync": "show_menu_sync",
    "delete_video": "show_menu_delete_video", "screencap": "show_menu_screencap", "debug": "show_menu_debug",
    "testing": "show_menu_testing",
}
# Pages still on their way over from the Tkinter panel -> the port phase that brings them.
PAGES_NOT_YET_PORTED = {"sleepwake": 2, "sync": 2, "delete_video": 2, "debug": 2, "screencap": 3}

# Friendlier names for the background-task chips (the Tk panel showed the raw names).
TASK_LABELS = {
    "htWatchdog": "Headtracking", "stayAwake": "Stay-Awake", "keepalive": "Keepalive",
    "popupWatchdog": "Popup recovery", "overheatWatchdog": "Overheat", "blackScreenProbe": "Black-screen probe",
    "heartbeat": "Heartbeat",
}

SIDEBAR_WIDTH = 172
STRIP_WIDE_MIN = 1200        # narrower than this, the top strip uses its compact two-row layout
WINDOW_STATE_VERSION = 1     # bump if the dock layout changes shape, so an old saved layout is ignored

SHOW_MODE_HELP = ("While on, the overheat and black-screen watchdogs keep watching and logging but send "
                  "nothing to any headset. Monitoring continues; only the corrective actions stop. Survives "
                  "restarting the panel.\n\nThe other watchdogs (Stay-Awake, Keepalive, Headtracking, Popup "
                  "recovery) don't read Show Mode and keep running as they are.")


def _page(builder):
    """Marks a page builder. The page is put on screen only once the builder
    has filled it, so everything on it appears at once."""
    @functools.wraps(builder)
    def build(self, *args, **kwargs):
        try:
            return builder(self, *args, **kwargs)
        finally:
            self._finish_page()
    return build


class TargetRow(QWidget):
    """The "Target: [headset] Refresh" row at the top of a page, with room for
    a page's own buttons after it. Everything sits to the left; the row never
    stretches the dropdown across the page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(8)
        self.row.addStretch(1)

    def add(self, widget, stretch=0):
        self.row.insertWidget(self.row.count() - 1, widget, stretch)
        return widget


class ControlPanel(QMainWindow):
    """The panel window. Everything above the line "logic copied from the
    Tkinter panel" is Qt (the window, the pages, the log); everything below it
    is the Tk panel's own logic, unchanged."""

    def __init__(self, safe_preview=False):
        super().__init__()
        _dialog_parent_ref[:] = [self]
        # --screenshot: open the window for a picture only -- start no watchdog,
        # query nothing, save nothing.
        self._safe_preview = safe_preview
        self.setWindowTitle("CXVR Headset Control Panel (Qt)")
        self.setMinimumSize(800, 640)

        # The same state as the Tkinter panel's __init__.
        self.cfg = load_config()
        self.scripts_dir = materialize_scripts()
        self.log_queue: queue.Queue = queue.Queue()
        self.current_proc = None          # a one-shot foreground action, if any
        self._interrupt_attempts = 0      # tracks escalation: 1st click = graceful, 2nd = force-kill
        self.toggle_procs = {}            # name -> subprocess.Popen, for background watchdogs
        self.scrcpy_procs = {}            # device serial -> subprocess.Popen, for open screen-capture windows
        self.batch_scrcpy_procs = {}      # slot key -> subprocess.Popen, for batch-preview's currently-open windows
        self.batch_slot_threads = []      # one independent thread per rolling slot
        self.batch_cycle_stop_event = None
        self.batch_queue_lock = threading.Lock()      # guards the shared rolling device queue below
        self.batch_launch_lock = threading.Lock()     # ensures only one slot is mid-launch-setup at a time
        self._batch_device_list = []      # current known device list for the rolling queue
        self._batch_device_index = 0      # next position to hand out in that list
        self._batch_status_text = "Batch preview stopped."
        self.toggle_buttons = {}          # name -> ToggleSwitch, so re-entering a page shows correct state
        self.action_buttons = []          # one-shot buttons on the CURRENT page, disabled while busy
        # The built-in terminal's session state (the Tk panel set these up in _build_terminal).
        self._term = None
        self._terminal_unlocked = False   # opened from Testing for this session only
        self._term_pane_enabled = None

        self._build_ui()
        # The log pump. Its 100 ms tick is also what lets Python signal handlers
        # run at all while Qt's event loop is idle (see main()).
        self._pump_timer = QTimer(self)
        self._pump_timer.timeout.connect(self._poll_log_queue)
        self._pump_timer.start(LOG_PUMP_INTERVAL_MS)
        self._restore_window_state()
        self.show_menu_connect()
        self._update_terminal_visibility()
        self._append_log(f"[startup] Qt panel on Python {sys.version.split()[0]} ({sys.executable}), "
                         f"PySide6 {PYSIDE6_VERSION}, Qt {qVersion()}, platform {QApplication.platformName()}")
        old_package = str(self.cfg.get("package") or "").strip()
        if old_package and old_package != APP_PACKAGE:
            self._append_log(f"[settings] Your saved App package was {old_package!r}; the panel now always "
                             f"uses the built-in {APP_PACKAGE!r}. Change APP_PACKAGE at the top of the "
                             f"panel file if that's wrong.")
        if self._safe_preview:
            return
        self._warn_if_other_instance_running()

        # Headtracking watchdog runs by default -- no manual Start needed.
        # The script itself waits for at least one headset to connect before
        # doing anything, so it's safe to fire immediately at launch even
        # with nothing connected yet.
        self.action_toggle_ht_watchdog()

    # =================================================================== chrome
    def _build_ui(self):
        self._init_settings_vars()
        self.menu_title_var = StringVar(value="")
        self.status_vars = {key: StringVar(value="—") for key in ("connected", "confirmed", "failed", "total")}
        self.bg_tasks_var = StringVar(value="none running")

        top = QWidget()
        top_layout = QVBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)
        top_layout.addWidget(self._build_strip())
        self.show_bar = QLabel("SHOW MODE IS ON — the overheat and black-screen watchdogs keep logging but "
                               "send nothing to any headset. Other watchdogs aren't affected.")
        self.show_bar.setObjectName("showBar")
        self.show_bar.setWordWrap(True)
        top_layout.addWidget(self.show_bar)
        self.setMenuWidget(top)
        _bind(self.show_bar, self.show_mode_var, lambda value: self._render_show_mode())
        self._render_show_mode()

        self._build_sidebar()
        self.page_scroll = QScrollArea()
        self.page_scroll.setObjectName("pageScroll")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setCentralWidget(self.page_scroll)
        self.page = None
        self.page_layout = None
        self._build_docks()

    def _build_strip(self):
        """Status numbers, background tasks, Show Mode and the three always-available
        controls. Wide windows get one row; narrower ones (the show layout on half
        the laptop screen, or the 800 px minimum) get a compact two-row version."""
        self.strip = QFrame()
        self.strip.setObjectName("strip")
        outer = QVBoxLayout(self.strip)
        outer.setContentsMargins(14, 6, 12, 6)
        outer.setSpacing(4)
        self._strip_row1 = QHBoxLayout()
        self._strip_row1.setSpacing(12)
        self._strip_row2 = QHBoxLayout()
        self._strip_row2.setSpacing(8)
        outer.addLayout(self._strip_row1)
        outer.addLayout(self._strip_row2)

        self._brand = QWidget()
        brand = QVBoxLayout(self._brand)
        brand.setContentsMargins(0, 0, 6, 0)
        brand.setSpacing(0)
        wordmark = QLabel("CXVR")
        wordmark.setObjectName("wordmark")
        brand.addWidget(wordmark)
        sub = QLabel("Fleet control")
        sub.setObjectName("statCaption")
        brand.addWidget(sub)

        self._stats = QWidget()
        self._stats_grid = QGridLayout(self._stats)
        self._stats_grid.setContentsMargins(0, 0, 0, 0)
        self._stats_grid.setHorizontalSpacing(16)
        self._stats_grid.setVerticalSpacing(0)
        self._stat_cells = []
        for caption, key in (("connected & stable", "connected"), ("failed to confirm", "failed"),
                             ("fixed this run", "confirmed"), ("total fixed / connected", "total")):
            cell = StatCell(self.status_vars[key], caption)
            self._stat_cells.append(cell)
            if key == "failed":
                self.failed_value_label = cell

        self._tasks = QWidget()
        self._tasks_layout = QBoxLayout(QBoxLayout.Direction.TopToBottom, self._tasks)
        self._tasks_layout.setContentsMargins(0, 0, 0, 0)
        self._tasks_layout.setSpacing(2)
        tasks_caption = QLabel("Background tasks")
        tasks_caption.setObjectName("statCaption")
        self._tasks_layout.addWidget(tasks_caption)
        self._chips = ChipRow()
        self._tasks_layout.addWidget(self._chips, 1)
        _bind(self._chips, self.bg_tasks_var, self._render_bg_tasks)

        self._show_box = QWidget()
        show = QHBoxLayout(self._show_box)
        show.setContentsMargins(0, 0, 4, 0)
        show.setSpacing(7)
        self.show_mode_switch = VarSwitch(self.show_mode_var, command=self._toggle_show_mode, warn=True)
        self.show_mode_switch.setToolTip(SHOW_MODE_HELP)
        self._show_label = QLabel("Show mode")
        self._show_label.setObjectName("showModeLabel")
        self._show_label.setToolTip(SHOW_MODE_HELP)
        show.addWidget(self.show_mode_switch)
        show.addWidget(self._show_label)

        # Interrupt is ALWAYS enabled, deliberately never gated on state -- it's
        # the manual escape hatch for a hung script and must never be unusable.
        self.stop_all_btn = Button("Stop all tasks", self._stop_all_toggles, "stripBtn",
                                   tooltip="Stops every background watchdog this panel started.")
        self.interrupt_btn = Button("Interrupt script", self._interrupt_current, "stripBtn",
                                    tooltip="Interrupts the running one-shot script (and everything it started). "
                                            "Click again to force-kill it.")
        self.kill_adb_btn = Button("Kill ADB server", self.action_kill_adb_server, "stripBtn",
                                   tooltip="Restarts the local adb server. Every connection drops (asks first).")
        self._strip_wide = None
        self._apply_strip_mode(True)
        return self.strip

    def _apply_strip_mode(self, wide):
        if wide == self._strip_wide:
            return
        self._strip_wide = wide
        for row in (self._strip_row1, self._strip_row2):
            while row.count():
                row.takeAt(0)
        for i, cell in enumerate(self._stat_cells):
            self._stats_grid.removeWidget(cell)
            self._stats_grid.addWidget(cell, *((0, i) if wide else divmod(i, 2)))
            cell.set_compact(not wide)
        self._brand.setVisible(wide)
        self._tasks_layout.setDirection(QBoxLayout.Direction.TopToBottom if wide
                                        else QBoxLayout.Direction.LeftToRight)
        self._tasks_layout.setSpacing(2 if wide else 8)
        buttons = (self.stop_all_btn, self.interrupt_btn, self.kill_adb_btn)
        if wide:
            for widget, stretch in ((self._brand, 0), (self._stats, 0), (self._tasks, 1), (self._show_box, 0)):
                self._strip_row1.addWidget(widget, stretch)
        else:
            self._strip_row1.addWidget(self._stats)
            self._strip_row1.addStretch(1)
            self._strip_row1.addWidget(self._show_box)
            self._strip_row2.addWidget(self._tasks, 1)
        for button in buttons:
            self._strip_row1.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        self._strip_row1.setSpacing(12 if wide else 8)
        self.strip.layout().setSpacing(0 if wide else 3)

    def _render_bg_tasks(self, value):
        names = [] if value == "none running" else [n for n in str(value).split(", ") if n]
        self._chips.set_names([TASK_LABELS.get(name, name) for name in names])

    def _render_show_mode(self):
        on = bool(self.show_mode_var.get())
        self.strip.setProperty("showmode", on)
        self._show_label.setProperty("on", on)
        restyle(self.strip)
        restyle(self._show_label)
        self.show_bar.setVisible(on)

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        lay = QVBoxLayout(side)
        lay.setContentsMargins(0, 4, 0, 8)
        lay.setSpacing(1)
        self.nav_buttons = {}
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        for section, items in NAV_SECTIONS:
            head = small_caps(section, 7.5)
            head.setContentsMargins(16, 11, 0, 3)
            lay.addWidget(head)
            for key, text in items:
                button = QPushButton()
                button.setObjectName("nav")
                button.setCheckable(True)
                button.setCursor(Qt.CursorShape.PointingHandCursor)
                button.setMinimumHeight(30)
                button.setAccessibleName(text)
                row = QHBoxLayout(button)
                row.setContentsMargins(14, 0, 10, 0)
                label = QLabel(text)
                label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                row.addWidget(label)
                row.addStretch(1)
                if key in PAGES_NOT_YET_PORTED:
                    later = QLabel("later")
                    later.setObjectName("navLater")
                    later.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                    row.addWidget(later)
                    button.setToolTip(f"Moves over to the Qt panel in phase {PAGES_NOT_YET_PORTED[key]} of the "
                                      f"port. Until then, use the Tkinter panel for it.")
                if key == "testing":
                    self._testing_badge = QLabel("")
                    self._testing_badge.setObjectName("navBadge")
                    self._testing_badge.setFixedHeight(18)
                    self._testing_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
                    self._testing_badge.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
                    row.addWidget(self._testing_badge)
                button.label_widget = label
                button.clicked.connect(lambda _checked=False, k=key: getattr(self, NAV_OPENERS[k])())
                self._nav_group.addButton(button)
                self.nav_buttons[key] = button
                lay.addWidget(button)
        lay.addStretch(1)
        panes = small_caps("Panes", 7.5)
        panes.setContentsMargins(16, 8, 0, 3)
        lay.addWidget(panes)
        self._pane_box = QVBoxLayout()
        self._pane_box.setContentsMargins(10, 0, 10, 4)
        self._pane_box.setSpacing(1)
        lay.addLayout(self._pane_box)
        note = QLabel("Qt port \u00b7 phase 1")
        note.setObjectName("sideNote")
        note.setToolTip("Pages marked \u201clater\u201d haven't moved to the Qt panel yet; they still run in the "
                        "Tkinter panel.")
        note.setContentsMargins(16, 6, 8, 0)
        lay.addWidget(note)
        side_scroll = QScrollArea()
        side_scroll.setObjectName("sideScroll")
        side_scroll.setWidget(side)
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_scroll.setFixedWidth(SIDEBAR_WIDTH)

        self.sidebar_dock = QDockWidget("Navigation", self)
        self.sidebar_dock.setObjectName("sidebarDock")
        self.sidebar_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.sidebar_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.sidebar_dock.setTitleBarWidget(QWidget())
        self.sidebar_dock.setWidget(side_scroll)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.sidebar_dock)
        # The sidebar runs the full height; the log/terminal panes sit to its right.
        self.setCorner(Qt.Corner.TopLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setCorner(Qt.Corner.BottomLeftCorner, Qt.DockWidgetArea.LeftDockWidgetArea)

    def _set_nav_current(self, key):
        for name, button in self.nav_buttons.items():
            current = name == key
            button.setChecked(current)
            font = button.label_widget.font()
            font.setBold(current)
            button.label_widget.setFont(font)
            button.label_widget.setStyleSheet(f"color: {UI_ACCENT_DARK if current else UI_TEXT};")

    def _refresh_nav(self):
        self.nav_buttons["delete_video"].setVisible(self._is_tested("delete_video.delete"))
        pending = sum(1 for key in GATED_FEATURES if not self._is_tested(key))
        self._testing_badge.setText(str(pending))
        self._testing_badge.setVisible(pending > 0)

    def _build_docks(self):
        """The live log and the terminal are dock panes: tabbed along the bottom by
        default, or side by side, or floated onto another monitor. The arrangement
        is saved in the config (dock_state) when the panel closes."""
        self.setDockOptions(QMainWindow.DockOption.AnimatedDocks | QMainWindow.DockOption.AllowTabbedDocks
                            | QMainWindow.DockOption.AllowNestedDocks)
        for area in (Qt.DockWidgetArea.BottomDockWidgetArea, Qt.DockWidgetArea.RightDockWidgetArea,
                     Qt.DockWidgetArea.TopDockWidgetArea):
            self.setTabPosition(area, QTabWidget.TabPosition.North)
        areas = (Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea
                 | Qt.DockWidgetArea.TopDockWidgetArea)
        features = (QDockWidget.DockWidgetFeature.DockWidgetClosable
                    | QDockWidget.DockWidgetFeature.DockWidgetMovable
                    | QDockWidget.DockWidgetFeature.DockWidgetFloatable)

        self.log_dock = QDockWidget("Live log", self)
        self.log_dock.setObjectName("logDock")
        self.log_dock.setAllowedAreas(areas)
        self.log_dock.setFeatures(features)
        self.log_text = QPlainTextEdit()
        self.log_text.setObjectName("console")
        self.log_text.setReadOnly(True)
        self.log_text.setUndoRedoEnabled(False)
        self.log_text.setMaximumBlockCount(LOG_MAX_LINES + 1)   # + the empty line after the last newline
        self.log_text.setFont(mono_font())
        self.log_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.log_text.setMinimumHeight(60)
        self.log_dock.setWidget(self.log_text)
        self.log_dock.setTitleBarWidget(
            DockTitle(self.log_dock, "Live log", extras=[Button("Clear", self._clear_log, "small")]))
        self._log_formats = {}
        for tag, colour in ((None, UI_CONSOLE_FG), ("fail", UI_LOG_FAIL), ("ok", UI_LOG_OK)):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(colour))
            self._log_formats[tag] = fmt

        self.term_dock = QDockWidget("Terminal", self)
        self.term_dock.setObjectName("terminalDock")
        self.term_dock.setAllowedAreas(areas)
        self.term_dock.setFeatures(features)
        holder = QFrame()
        holder.setObjectName("consoleNote")
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(14, 12, 14, 12)
        note = QLabel("The built-in terminal moves over to the Qt panel in phase 2 of the port. Until then, "
                      "use it in the Tkinter panel.")
        note.setWordWrap(True)
        holder_layout.addWidget(note)
        holder_layout.addStretch(1)
        self.term_dock.setWidget(holder)
        self.term_title = DockTitle(self.term_dock, "Terminal")
        self.term_dock.setTitleBarWidget(self.term_title)

        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.log_dock)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.term_dock)
        self.tabifyDockWidget(self.log_dock, self.term_dock)
        self.log_dock.raise_()
        self.resizeDocks([self.log_dock], [190], Qt.Orientation.Vertical)

        self._pane_toggles = {}
        for dock, text in ((self.log_dock, "Live log"), (self.term_dock, "Terminal")):
            action = dock.toggleViewAction()   # tracks shown/closed, not which tab is in front
            toggle = QPushButton(text)
            toggle.setObjectName("paneToggle")
            toggle.setCheckable(True)
            toggle.setChecked(action.isChecked())
            toggle.setCursor(Qt.CursorShape.PointingHandCursor)
            toggle.setToolTip(f"Show or hide the {text.lower()} pane")
            toggle.clicked.connect(lambda _checked=False, a=action: a.trigger())
            action.toggled.connect(toggle.setChecked)
            self._pane_box.addWidget(toggle)
            self._pane_toggles[dock.objectName()] = toggle

    # ------------------------------------------------------ window state
    def _restore_window_state(self):
        """Window size/position and the dock arrangement from the last session
        (config keys window_geometry and dock_state, which the Tkinter panel
        keeps but ignores)."""
        self._restored_dock_state = False
        restored_geometry = False
        geometry = self.cfg.get("window_geometry")
        if isinstance(geometry, str) and geometry:
            try:
                restored_geometry = self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            except Exception:
                restored_geometry = False
        if not restored_geometry:
            self._apply_default_geometry()
        state = self.cfg.get("dock_state")
        if isinstance(state, str) and state:
            try:
                self._restored_dock_state = bool(
                    self.restoreState(QByteArray.fromBase64(state.encode("ascii")), WINDOW_STATE_VERSION))
            except Exception:
                self._restored_dock_state = False
        self.sidebar_dock.show()
        if not self._restored_dock_state:
            self.resizeDocks([self.log_dock], [max(170, int(self.height() * 0.28))], Qt.Orientation.Vertical)
        self._rescue_offscreen_docks()

    def _apply_default_geometry(self):
        width, height = 1280, 860
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            width, height = min(width, area.width()), min(height, area.height())
            self.resize(max(width, 800), max(height, 640))
            self.move(area.x() + max(0, (area.width() - self.width()) // 2),
                      area.y() + max(0, (area.height() - self.height()) // 2))
        else:
            self.resize(width, height)

    def _rescue_offscreen_docks(self):
        """A pane floated onto a second monitor that isn't connected this time
        would otherwise reopen off-screen, out of reach. Dock it back instead."""
        screens = [s.availableGeometry() for s in QApplication.screens()]
        for dock in (self.log_dock, self.term_dock):
            if dock.isFloating() and not any(area.intersects(dock.geometry()) for area in screens):
                dock.setFloating(False)

    def _save_window_state(self):
        self.cfg["window_geometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
        self.cfg["dock_state"] = bytes(self.saveState(WINDOW_STATE_VERSION).toBase64()).decode("ascii")
        save_config(self.cfg)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_strip_mode(self.width() >= STRIP_WIDE_MIN)

    def closeEvent(self, event):
        if not self._safe_preview:
            try:
                self._save_window_state()
            except Exception as e:   # never let a settings problem block closing
                print(f"[cxvr] couldn't save the window layout: {e}", file=sys.stderr)
        self._cleanup_subprocesses()
        event.accept()

    # ============================================================ page frame
    def _begin_page(self, nav_key, title):
        """Replaces the page area with a fresh, empty page and returns its layout.
        Every page is rebuilt when it's opened (so gating changes show at once);
        the old page is deleted once control has left it."""
        old = self.page_scroll.takeWidget()
        if old is not None:
            old.hide()
            old.deleteLater()
        self.action_buttons = []
        # Only switches on the page being built belong here -- the previous
        # page's are going away, and relabeling a deleted widget is an error.
        self.toggle_buttons = {}
        self._set_menu_title(title)
        page = QWidget()
        page.setObjectName("page")
        outer = QVBoxLayout(page)
        outer.setContentsMargins(22, 14, 20, 18)
        outer.setSpacing(12)
        heading = QLabel(self.menu_title_var.get())
        heading.setObjectName("pageTitle")
        heading.setWordWrap(True)
        _bind(heading, self.menu_title_var, heading.setText)
        outer.addWidget(heading)
        content = QVBoxLayout()
        content.setSpacing(12)
        outer.addLayout(content)
        outer.addStretch(1)
        self.page = page
        self.page_layout = content
        self._set_nav_current(nav_key)
        self._refresh_nav()
        # Another panel instance (or the Tk panel) may have changed it meanwhile.
        self.show_mode_var.set(SHOW_MODE_FILE.exists())
        return content

    def _finish_page(self):
        if self.page is not None and self.page_scroll.widget() is not self.page:
            self.page_scroll.setWidget(self.page)

    # ============================================================ components
    def _card(self, title, right=None, help=None, layout=None):
        card = Card(title, right=right, help=help)
        (layout if layout is not None else self.page_layout).addWidget(card)
        return card

    def _mark_tested_button(self, key, refresh):
        return Button("Mark tested", lambda: self._mark_tested(key, refresh), kind="small")

    def _testing_banner(self, what, key, refresh, destination):
        self.page_layout.addWidget(TestingBanner(what, destination, lambda: self._mark_tested(key, refresh)))

    def _back_to_testing(self):
        self.page_layout.addWidget(Button("‹ Testing", self.show_menu_testing, kind="link"), 0,
                                   Qt.AlignmentFlag.AlignLeft)

    def _device_picker(self, layout, variable, label="Headset:", include_all=True, on_refresh=None):
        """A label, a read-only dropdown of connected headsets (plus ALL) and a
        Refresh button, added to `layout`; returns the dropdown. Every page that
        can target a single headset uses this, never a free-text box, so a typo
        can't send a command to the wrong place.

        The list starts with just the ALL entry and is filled in on Refresh:
        `adb devices` blocks, and running it while a page opens would make the
        whole window hitch every time."""
        layout.addWidget(field_label(label.rstrip(":")))
        values = [ALL_DEVICES_LABEL] if include_all else []
        combo = Combo(variable, values, chars=24)
        layout.addWidget(combo)
        if not variable.get() and values:
            variable.set(values[0])

        def refresh():
            devices, err = self._query_connected_devices()
            if err:
                messagebox.showerror("Refresh failed", f"Could not query adb devices: {err}")
                return
            new_values = ([ALL_DEVICES_LABEL] if include_all else []) + devices
            combo.configure(values=new_values)
            if variable.get() not in new_values:
                variable.set(new_values[0] if new_values else "")
            self._append_log(f"\n[devices] {len(devices)} connected: {', '.join(devices) or 'none'}\n")
            if on_refresh:
                on_refresh(devices)

        btn = Button("Refresh", refresh, kind="small")
        layout.addWidget(btn)
        self._register(btn)
        combo.refresh_button = btn
        return combo

    def _target_row(self, variable, note=None):
        """The same headset picker at the top of every page that can act on a
        single headset."""
        row = TargetRow()
        picker = QHBoxLayout()
        picker.setSpacing(8)
        self._device_picker(picker, variable, label="Target:")
        row.row.insertLayout(0, picker)
        if note:
            row.add(Caption(note), 1)
        self.page_layout.addWidget(row)
        return row

    def _toggle_row(self, layout, key, title, action, caption=None, caption_var=None,
                    settings=None, info=None, running=None):
        """One long-running task per row, ending in its Start/Stop switch.
        `action` is called with the switch, as the Tk panel's actions expect."""
        if running is None:
            running = bool(key) and key in self.toggle_procs
        row = ToggleRow(title, caption=caption, caption_var=caption_var, info=info, running=running)
        if settings is not None:
            settings(row.settings_layout)
        btn = ToggleSwitch(running=running, on_change=row.set_running)
        btn.configure(command=lambda: action(btn))
        row.set_switch(btn)
        layout.addWidget(row)
        if key:
            self.toggle_buttons[key] = btn
        return btn

    def _placeholder_page(self, nav_key, title, what, phase, back=False):
        """A page that hasn't been ported yet: says so, and where to find it."""
        lay = self._begin_page(nav_key, title)
        if back:
            self._back_to_testing()
        box = QFrame()
        box.setObjectName("placeholder")
        inner = QVBoxLayout(box)
        inner.setContentsMargins(16, 14, 16, 14)
        inner.setSpacing(6)
        name = QLabel(f"{what} isn't in the Qt panel yet")
        name.setObjectName("name")
        inner.addWidget(name)
        inner.addWidget(Caption(f"It moves over in phase {phase} of the port. Until then, use the Tkinter panel "
                                f"(cxvr_control_panel.py) for it — close this panel first, since the two "
                                f"shouldn't run at the same time. Both use the same settings."))
        lay.addWidget(box)

    # ================================================================ pages
    @_page
    def show_menu_connect(self):
        lay = self._begin_page("connect", "Connect / Reconnect Headsets")
        card = self._card("Connect headsets")
        row = QHBoxLayout()
        row.setSpacing(8)
        for label, cmd, kind in (("Normal Connect\nfixes broken or missing", self.action_connect, "primary"),
                                 ("Full Scan\nadds a subnet scan", self.action_full_scan, "big"),
                                 ("Purge & Reconnect All\ndisconnects all first", self.action_purge, "big")):
            row.addWidget(self._register(Button(label, cmd, kind)), 1)
        card.body.addLayout(row)

        opts = self._card("Options")
        opts.body.addWidget(Check("20 s tablet visual-check delay during the headtracking fix",
                                  self.visual_check_var, self._save_settings))
        opts.body.addWidget(Caption("Off by default."))
        return lay

    @_page
    def show_menu_heartbeat(self):
        self._begin_page("heartbeat", "Connection Heartbeat Monitor")
        card = self._card("Monitor")
        self._toggle_row(card.body, "heartbeat", "Connection Heartbeat", self.action_toggle_heartbeat,
                         caption="Polls every connected headset and logs reachability. Monitoring only — "
                                 "never sleeps, wakes or changes a headset.")

    @_page
    def show_menu_volume(self):
        lay = self._begin_page("volume", "Volume Control")
        last = self.cfg.get("last_volume_op") or "no volume operation run yet"
        self.volume_last_var = StringVar(value=f"Last requested: {last}")
        lay.addWidget(Caption(var=self.volume_last_var, variant="italic"))
        target = self._target_row(self.volume_target_var)
        target.add(self._register(Button("Check current volume", self.action_volume_check, kind="small")))

        presets = self._card("Presets")
        row = QHBoxLayout()
        row.setSpacing(8)
        for label, level in VOLUME_PRESETS:
            row.addWidget(self._register(Button(label, lambda lv=level, lbl=label: self.action_volume_preset(lv, lbl),
                                                kind="big")), 1)
        presets.body.addLayout(row)
        presets.body.addWidget(Caption("Each preset is measured, corrected and re-checked per headset, so a dropped "
                                       "keypress over wifi gets fixed instead of leaving one headset out of step."))

        exact = self._card("Exact level")
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(field_label("Level (0–15)"))
        row.addWidget(SpinEntry(self.volume_level_var, 0, 15))
        row.addWidget(self._register(Button("Set Volume", self.action_volume_set, kind="primary")))
        row.addSpacing(6)
        row.addWidget(Caption("An absolute level, not a reduction amount."), 1)
        exact.body.addLayout(row)

    @_page
    def show_menu_power(self):
        lay = self._begin_page("power", "Power Management")
        reboot_ok = self._is_tested("power.reboot")
        poweroff_ok = self._is_tested("power.poweroff")
        if not (reboot_ok or poweroff_ok):
            card = self._card("Power")
            card.body.addWidget(Caption("Reboot and Power Off are in Testing — open Testing in the sidebar.",
                                        variant="notice"))
            return lay
        self._target_row(self.power_target_var)
        card = self._card("Power")
        row = QHBoxLayout()
        row.setSpacing(8)
        if reboot_ok:
            button = self._register(Button("Reboot", self.action_reboot_all, kind="big"))
            button.setMinimumWidth(150)
            row.addWidget(button)
        if poweroff_ok:
            button = self._register(Button("Power Off", self.action_power_off_all, kind="danger"))
            button.setMinimumWidth(150)
            row.addWidget(button)
        row.addStretch(1)
        card.body.addLayout(row)
        if reboot_ok and poweroff_ok:
            note = ("Both ask for confirmation naming exactly which headsets are affected. Power Off can't be "
                    "undone remotely — each headset has to be turned back on by hand.")
        elif reboot_ok:
            note = ("Asks for confirmation naming exactly which headsets are affected. "
                    "Power Off is still in Testing — open Testing in the sidebar.")
        else:
            note = ("Asks for confirmation naming exactly which headsets are affected, and can't be undone "
                    "remotely. Reboot is still in Testing — open Testing in the sidebar.")
        card.body.addWidget(Caption(note))
        return lay

    @_page
    def show_menu_testing(self):
        lay = self._begin_page("testing", "Testing")
        lay.addWidget(Caption("Not yet confirmed on real headsets. Each works exactly as it will after testing "
                              "— this is only where you find it until then."))
        any_left = False
        for group, items in self._testing_items():
            pending = [item for item in items if not self._is_tested(item[0])]
            if not pending:
                continue
            any_left = True
            card = self._card(group)
            for i, (key, name, destination, opener) in enumerate(pending):
                if i:
                    card.body.addWidget(rule())
                row = QHBoxLayout()
                row.setContentsMargins(0, 0, 0, 0)
                row.setSpacing(8)
                text = QVBoxLayout()
                text.setSpacing(1)
                title = QLabel(name)
                title.setObjectName("name")
                text.addWidget(title)
                text.addWidget(Caption(f"Moves to {destination} once marked tested"))
                row.addLayout(text, 1)
                open_btn = Button("Open", opener)
                open_btn.setMinimumWidth(70)
                row.addWidget(open_btn, 0, Qt.AlignmentFlag.AlignVCenter)
                row.addWidget(Button("Mark tested", lambda k=key: self._mark_tested(k, self.show_menu_testing),
                                     kind="small"), 0, Qt.AlignmentFlag.AlignVCenter)
                holder = QWidget()
                holder.setLayout(row)
                holder.testing_key = key
                card.body.addWidget(holder)
        if not any_left:
            lay.addWidget(Caption("Nothing left to test — every gated feature has been marked tested and "
                                  "lives in its normal place now."))

    @_page
    def _render_testing_power(self):
        """Only the untested power actions, each with its own Mark tested --
        a separate page from the real Power page on purpose, so an untested
        action can never appear there before it's been confirmed."""
        lay = self._begin_page("testing", "Testing › Power Management")
        self._back_to_testing()
        pending = [(key, label, kind, cmd) for key, label, kind, cmd in (
            ("power.reboot", "Reboot", "big", self.action_reboot_all),
            ("power.poweroff", "Power Off", "danger", self.action_power_off_all))
            if not self._is_tested(key)]
        if not pending:
            lay.addWidget(Caption("Both are already marked tested — they're in Power Management now."))
            return
        self._target_row(self.power_target_var)
        for key, label, kind, cmd in pending:
            card = self._card(label, right=[self._mark_tested_button(key, self.show_menu_testing)])
            row = QHBoxLayout()
            row.setSpacing(12)
            button = self._register(Button(label, cmd, kind=kind))
            button.setMinimumWidth(150)
            row.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(Caption("Same confirmation as the real page, naming exactly which headsets are "
                                  "affected."), 1)
            card.body.addLayout(row)

    # Pages that arrive in later phases of the port.
    @_page
    def show_menu_sleepwake(self):
        self._placeholder_page("sleepwake", "Sleep / Wake Management", "Sleep / Wake", 2)

    @_page
    def show_menu_sync(self):
        self._placeholder_page("sync", "Content Sync", "Content Sync", 2)

    @_page
    def show_menu_delete_video(self):
        self._placeholder_page("delete_video", "Delete Video", "Delete Video", 2,
                               back=not self._is_tested("delete_video.delete"))

    @_page
    def show_menu_debug(self):
        self._placeholder_page("debug", "Debug Tools", "Debug Tools", 2)

    @_page
    def show_menu_screencap(self):
        self._placeholder_page("screencap", "Screen Capture", "Screen Capture", 3)

    @_page
    def _render_testing_sleepwake(self):
        self._placeholder_page("testing", "Testing › Sleep / Wake Management",
                               "Testing › Sleep / Wake", 2, back=True)

    @_page
    def _render_testing_snapshot(self):
        self._placeholder_page("testing", "Testing › Diagnostic Snapshot", "The Diagnostic Snapshot", 2,
                               back=True)

    @_page
    def _render_testing_terminal(self):
        self._placeholder_page("testing", "Testing › Terminal", "The terminal", 2, back=True)

    # ================================================================== log
    def _clear_log(self):
        self.log_text.clear()

    def _append_log(self, line):
        self._append_log_lines([line])

    def _append_log_lines(self, lines):
        """Adds lines exactly as the Tk log did (each one followed by a newline;
        a line containing FAIL in red, one saying confirmed / connect phase
        finished in green) and keeps the view at the bottom. Only the last
        LOG_MAX_LINES lines stay on screen."""
        _assert_main_thread("_append_log")
        cursor = QTextCursor(self.log_text.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.beginEditBlock()
        for line in lines:
            tag = None
            if "FAIL" in line:
                tag = "fail"
            elif "confirmed" in line.lower() or "connect phase finished" in line.lower():
                tag = "ok"
            cursor.insertText(line + "\n", self._log_formats[tag])
        cursor.endEditBlock()
        bar = self.log_text.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _poll_log_queue(self):
        """Runs every LOG_PUMP_INTERVAL_MS on the main thread: the only place
        worker-thread output reaches the window. Same handlers as the Tk panel's
        loop, but at most LOG_PUMP_MAX_ITEMS per tick (the rest waits for the
        next one), and runs of plain lines are added to the log in one go."""
        lines = []
        try:
            for _ in range(LOG_PUMP_MAX_ITEMS):
                item = self.log_queue.get_nowait()
                if item[0] == "line":
                    lines.append(item[1])
                    continue
                if lines:
                    self._append_log_lines(lines)
                    lines = []
                if item[0] == "done":
                    self._on_process_done(item[1])
                elif item[0] == "watchdog_summary":
                    self._parse_and_show_summary(item[1])
                elif item[0] == "batch_status":
                    self._batch_status_text = item[1]
                    if hasattr(self, "batch_status_var"):
                        self.batch_status_var.set(item[1])
                elif item[0] == "screencap_status_refresh":
                    if hasattr(self, "screencap_status_var"):
                        self.screencap_status_var.set(self._screencap_status_text())
                elif item[0] == "term_data":
                    if self._term is not None and item[1] == self._term["sid"]:
                        self._term_apply(item[2])
                elif item[0] == "term_exit":
                    self._term_on_exit(item[1], item[2])
        except queue.Empty:
            pass
        if lines:
            self._append_log_lines(lines)
        if TERMINAL_SUPPORTED and self._term is not None:
            self._term_update_echo_mask()
        self._refresh_toggle_state()

    # ============================================================= terminal
    # Phase 1 of the port: the Terminal pane exists (so its place in the saved
    # layout is kept) and appears exactly when the Tk terminal would, but the
    # terminal itself moves over in phase 2. No session is ever started here,
    # so the three hooks below are never reached yet.
    def _update_terminal_visibility(self):
        """The Terminal pane only exists once terminal.shell is marked tested, or
        after Show terminal on its Testing page for this session. Turning it off
        also ends any running session, so nothing keeps running unseen."""
        enabled = self._terminal_enabled()
        self._pane_toggles["terminalDock"].setVisible(enabled)
        if enabled:
            if self._term_pane_enabled is None and not self._restored_dock_state:
                self.term_dock.show()          # first run: there, but behind the live log
                self.log_dock.raise_()
            elif self._term_pane_enabled is False:
                self.term_dock.show()          # just switched on: bring it to the front
                self.term_dock.raise_()
        else:
            self.term_dock.hide()
            self._term_close_session()
        self._term_pane_enabled = enabled
        self._refresh_nav()

    def _term_apply(self, data):
        pass   # phase 2

    def _term_on_exit(self, sid, code):
        pass   # phase 2

    def _term_update_echo_mask(self):
        pass   # phase 2

    # ==================================================================
    # Everything below this line is logic copied from the Tkinter panel
    # (cxvr_control_panel.py), unchanged apart from the three substitutions
    # listed at the top of this file. The port kit's integrity test checks it.
    # ==================================================================
