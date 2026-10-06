"""Qt harness: loads the PySide6 panel with the shared stubs and drives its real
widgets offscreen (QT_QPA_PLATFORM=offscreen). Same adapter API as harness_tk.py.

Run it with the Python 3.11 venv that has PySide6-Essentials 6.11.2, like the
laptop. HOME is pointed at a temporary folder before the panel is loaded, and
CXVR_ASSERT_MAIN_THREAD=1 makes any widget access from a worker thread fail."""
import importlib.util
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "common"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["HOME"] = os.environ.get("CXVR_TEST_HOME") or tempfile.mkdtemp(prefix="cxvr_qt_home_")
os.environ["CXVR_ASSERT_MAIN_THREAD"] = "1"
import panel_stubs  # noqa: E402


def first_line(text):
    return str(text).split("\n")[0]


class QtPanel:
    kind = "qt"

    def __init__(self, path):
        spec = importlib.util.spec_from_file_location("cxvr_qt_panel", path)
        self.pm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.pm)
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QWidget
        self.QTest, self.QWidget = QTest, QWidget
        self.app = self.pm.make_app(["cxvr-test"])
        self.rec = None
        self.p = None

    # ------------------------------------------------------------ lifecycle
    def install_stubs(self):
        self.rec = panel_stubs.install(self.pm)
        return self.rec

    def start(self, size=(1280, 860)):
        self.p = self.pm.ControlPanel()
        self.p.resize(*size)
        self.p.show()
        self.pump(0.2)

    def stop(self):
        try:
            self.p.close()
            self.p.deleteLater()
        finally:
            self.pump(0.05)

    def pump(self, secs=0.25):
        """Runs the Qt loop until the log queue is empty and at least `secs` passed."""
        end = time.time() + secs
        hard_end = time.time() + 10
        while time.time() < hard_end:
            self.app.processEvents()
            if time.time() >= end and self.p.log_queue.empty():
                self.app.processEvents()
                return
            time.sleep(0.01)

    # ------------------------------------------------------------ traversal
    def controls(self, where=None):
        pm = self.pm
        out = []
        for w in (where if where is not None else self.p.page).findChildren(self.QWidget):
            if isinstance(w, pm.ToggleSwitch):
                out.append(("switch", w.cget("text"), w.isEnabled(), w))
            elif isinstance(w, pm.Button):
                out.append(("button", w.label(), w.isEnabled(), w))
            elif isinstance(w, pm.Check):
                out.append(("check", w.label(), w.isEnabled(), w))
        return out

    def _find(self, label, where=None, kinds=("button", "check", "switch"), nth=0):
        hits = [c for c in self.controls(where) if c[0] in kinds and
                (c[1] == label or first_line(c[1]) == label)]
        if len(hits) <= nth:
            raise AssertionError(f"[qt] no control {label!r} (found {[c[1] for c in self.controls(where)]})")
        if nth == 0 and len(hits) > 1:
            raise AssertionError(f"[qt] {len(hits)} controls labelled {label!r}")
        return hits[nth][3]

    def _bound(self, var, classes):
        for w in self.p.findChildren(self.QWidget):
            if isinstance(w, classes) and getattr(w, "_cxvr_var", None) is var and w.isVisibleTo(self.p):
                return w
        raise AssertionError(f"[qt] no {classes} bound to that variable")

    # --------------------------------------------------------------- actions
    def open(self, page):
        if page == "testing_power":
            self.open("testing")
            self.row_click("Power Off" if self.p._is_tested("power.reboot") else "Reboot", "Open")
            return
        self.p.nav_buttons[page].click()
        self.pump(0.1)

    def click(self, label, nth=0):
        self._find(label, nth=nth).invoke()
        self.pump(0.05)

    def click_in(self, card_title, label):
        cards = [c for c in self.p.page.findChildren(self.pm.Card) if c.title == card_title]
        if len(cards) != 1:
            raise AssertionError(f"[qt] card {card_title!r}: {len(cards)} found")
        self._find(label, where=cards[0]).invoke()
        self.pump(0.05)

    def strip(self, label):
        for w in self.p.strip.findChildren(self.pm.Button):
            if w.label() == label:
                w.invoke()
                self.pump(0.05)
                return
        raise AssertionError(f"[qt] no strip control {label!r}")

    def row_click(self, item_name, label):
        from PySide6.QtWidgets import QLabel
        rows = [w for w in self.p.page.findChildren(self.QWidget) if hasattr(w, "testing_key") and
                any(lbl.text() == item_name for lbl in w.findChildren(QLabel))]
        if len(rows) != 1:
            raise AssertionError(f"[qt] testing row {item_name!r}: {len(rows)} found")
        self._find(label, where=rows[0]).invoke()
        self.pump(0.05)

    def toggle(self, key, pump=True):
        self.p.toggle_buttons[key].invoke()
        if pump:
            self.pump(0.15)   # at least one log-pump tick, so the result doesn't depend on timing

    def type_into(self, var_name, text):
        w = self._bound(getattr(self.p, var_name), (self.pm.Entry,))
        w.setFocus()
        w.selectAll()
        self.QTest.keyClick(w, self.pm.Qt.Key.Key_Delete)
        self.QTest.keyClicks(w, text)
        self.pump(0.02)

    def check(self, var_name, value):
        var = getattr(self.p, var_name)
        w = self._bound(var, (self.pm.Check,))
        if bool(var.get()) != bool(value):
            w.invoke()
        self.pump(0.02)

    def choose(self, var_name, value):
        w = self._bound(getattr(self.p, var_name), (self.pm.Combo,))
        values = list(w.cget("values"))
        if value not in values:
            raise AssertionError(f"[qt] {value!r} isn't in the {var_name} list {values}")
        w.choose(value)
        self.pump(0.02)

    def refresh(self, var_name):
        w = self._bound(getattr(self.p, var_name), (self.pm.Combo,))
        w.refresh_button.invoke()
        self.pump(0.05)

    def picker_values(self, var_name):
        return list(self._bound(getattr(self.p, var_name), (self.pm.Combo,)).cget("values"))

    def set_show_mode(self, on):
        if bool(self.p.show_mode_var.get()) != bool(on):
            self.p.show_mode_switch.invoke()
        self.pump(0.05)

    def nav_items(self):
        keys = sorted(k for k, b in self.p.nav_buttons.items() if b.isVisibleTo(self.p))
        return keys, self.p.menu_title_var.get()

    # ---------------------------------------------------------------- state
    def log_text(self):
        return self.p.log_text.toPlainText()

    def page_actions(self):
        return [(k, label, enabled) for k, label, enabled, _w in self.controls()]

    def failed_flagged(self):
        return bool(self.p.failed_value_label.value.property("warn"))

    def strip_enabled(self):
        return {w.label(): w.isEnabled() for w in self.p.strip.findChildren(self.pm.Button)}
