"""Tk harness: loads the frozen Tkinter panel with the shared stubs and drives
its real widgets under Xvfb. Same adapter API as harness_qt.py.

Run it with a Python 3.11 that has Tkinter (uv's standalone build), under
xvfb-run. HOME is pointed at a temporary folder before the panel is loaded, so
nothing touches a real config."""
import importlib.util
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "common"))
os.environ["HOME"] = os.environ.get("CXVR_TEST_HOME") or tempfile.mkdtemp(prefix="cxvr_tk_home_")
import panel_stubs  # noqa: E402

# Main-menu button label -> page key (the Qt panel's sidebar uses the same keys).
MAIN_MENU = {
    "Connect / Reconnect Headsets": "connect", "Sleep / Wake Management": "sleepwake",
    "Volume Control": "volume", "Power Management": "power", "Connection Heartbeat Monitor": "heartbeat",
    "Content Sync": "sync", "Debug Tools": "debug", "Screen Capture": "screencap", "Delete Video": "delete_video",
    "Testing (not yet marked tested)": "testing",
}


def first_line(text):
    return str(text).split("\n")[0]


class TkPanel:
    kind = "tk"

    def __init__(self, path):
        import tkinter
        self.tk = tkinter
        spec = importlib.util.spec_from_file_location("cxvr_tk_panel", path)
        self.pm = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.pm)
        self.rec = None
        self.root = None
        self.p = None

    # ------------------------------------------------------------ lifecycle
    def install_stubs(self):
        self.rec = panel_stubs.install(self.pm)
        return self.rec

    def start(self):
        self.root = self.tk.Tk()
        self.p = self.pm.ControlPanel(self.root)
        self.root.geometry("920x760+0+0")   # after construction: __init__ resets it
        self.pump(0.2)

    def stop(self):
        try:
            self.p._on_close()
        except Exception:
            try:
                self.root.destroy()
            except Exception:
                pass

    def pump(self, secs=0.25):
        """Runs the Tk loop until the log queue is empty and at least `secs` passed."""
        end = time.time() + secs
        hard_end = time.time() + 10
        while time.time() < hard_end:
            self.root.update()
            if time.time() >= end and self.p.log_queue.empty():
                self.root.update()
                return
            time.sleep(0.01)

    # ------------------------------------------------------------ traversal
    def _walk(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self._walk(child)

    @staticmethod
    def _text(widget):
        try:
            return str(widget.cget("text"))
        except Exception:
            return None

    def controls(self, where=None):
        """(kind, label, enabled, widget) for every button/checkbox under `where`."""
        out = []
        for w in self._walk(where if where is not None else self.p.actions_container):
            cls = w.winfo_class()
            if cls in ("TButton", "TCheckbutton"):
                kind = "check" if cls == "TCheckbutton" else (
                    "switch" if isinstance(w, self.pm.ToggleButton) else "button")
                out.append((kind, self._text(w), not w.instate(["disabled"]), w))
        return out

    def _find(self, label, where=None, kinds=("button", "check", "switch"), nth=0):
        hits = [c for c in self.controls(where) if c[0] in kinds and
                (c[1] == label or first_line(c[1]) == label)]
        if len(hits) <= nth:
            raise AssertionError(f"[tk] no control {label!r} (found {[c[1] for c in self.controls(where)]})")
        if nth == 0 and len(hits) > 1:
            raise AssertionError(f"[tk] {len(hits)} controls labelled {label!r}")
        return hits[nth][3]

    def _bound(self, var, classes):
        name = str(var)
        for w in self._walk(self.root):
            if w.winfo_class() in classes:
                for option in ("textvariable", "variable"):
                    try:
                        if str(w.cget(option)) == name:
                            return w
                    except Exception:
                        pass
        raise AssertionError(f"[tk] no {classes} bound to {name}")

    # --------------------------------------------------------------- actions
    def open(self, page):
        if page == "testing_power":
            self.open("testing")
            self.row_click("Power Off" if self.p._is_tested("power.reboot") else "Reboot", "Open")
            return
        self.p.show_main_menu()
        self.pump(0.05)
        label = next(k for k, v in MAIN_MENU.items() if v == page)
        self._find(label).invoke()
        self.pump(0.1)

    def click(self, label, nth=0):
        self._find(label, nth=nth).invoke()
        self.pump(0.05)

    def click_in(self, card_title, label):
        head = [w for w in self._walk(self.p.actions_container)
                if w.winfo_class() == "TLabel" and self._text(w) == card_title.upper()]
        if len(head) != 1:
            raise AssertionError(f"[tk] card {card_title!r}: {len(head)} found")
        shell = head[0].master.master
        self._find(label, where=shell).invoke()
        self.pump(0.05)

    def strip(self, label):
        strip_widgets = [w for w in self.root.winfo_children()]
        for top in strip_widgets:
            if top is self.p.actions_frame:
                continue
            for c in self.controls(top):
                if c[1] == label:
                    c[3].invoke()
                    self.pump(0.05)
                    return
        raise AssertionError(f"[tk] no strip control {label!r}")

    def row_click(self, item_name, label):
        names = [w for w in self._walk(self.p.actions_container)
                 if w.winfo_class() == "TLabel" and self._text(w) == item_name]
        if len(names) != 1:
            raise AssertionError(f"[tk] testing row {item_name!r}: {len(names)} found")
        text_frame = names[0].master
        row = int(text_frame.grid_info()["row"])
        body = text_frame.master
        for w in body.winfo_children():
            if w.winfo_class() == "TButton" and self._text(w) == label and int(w.grid_info()["row"]) == row:
                w.invoke()
                self.pump(0.05)
                return
        raise AssertionError(f"[tk] no {label!r} in row {item_name!r}")

    def toggle(self, key, pump=True):
        self.p.toggle_buttons[key].invoke()
        if pump:
            self.pump(0.15)   # at least one log-pump tick, so the result doesn't depend on timing

    def type_into(self, var_name, text):
        w = self._bound(getattr(self.p, var_name), ("TEntry", "TSpinbox"))
        w.delete(0, "end")
        w.insert(0, text)
        self.pump(0.02)

    def check(self, var_name, value):
        var = getattr(self.p, var_name)
        w = self._bound(var, ("TCheckbutton",))
        if bool(var.get()) != bool(value):
            w.invoke()
        self.pump(0.02)

    def choose(self, var_name, value):
        var = getattr(self.p, var_name)
        w = self._bound(var, ("TCombobox",))
        values = [str(v) for v in w.cget("values")]
        if value not in values:
            raise AssertionError(f"[tk] {value!r} isn't in the {var_name} list {values}")
        var.set(value)
        w.event_generate("<<ComboboxSelected>>")
        self.pump(0.02)

    def refresh(self, var_name):
        combo = self._bound(getattr(self.p, var_name), ("TCombobox",))
        row = int(combo.grid_info()["row"])
        for w in combo.master.winfo_children():
            if w.winfo_class() == "TButton" and self._text(w) == "Refresh" and int(w.grid_info()["row"]) == row:
                w.invoke()
                self.pump(0.05)
                return
        raise AssertionError(f"[tk] no Refresh next to {var_name}")

    def picker_values(self, var_name):
        combo = self._bound(getattr(self.p, var_name), ("TCombobox",))
        return [str(v) for v in combo.cget("values")]

    def set_show_mode(self, on):
        self.p.show_main_menu()
        self.pump(0.05)
        cb = [c for c in self.controls() if c[0] == "check" and "SHOW MODE" in c[1]][0]
        if bool(self.p.show_mode_var.get()) != bool(on):
            cb[3].invoke()
        self.pump(0.05)

    def nav_items(self):
        current = self.p.menu_title_var.get()
        self.p.show_main_menu()
        self.pump(0.05)
        keys = sorted(MAIN_MENU[c[1]] for c in self.controls() if c[0] == "button" and c[1] in MAIN_MENU)
        return keys, current

    # ---------------------------------------------------------------- state
    def log_text(self):
        return self.p.log_text.get("1.0", "end-1c")

    def page_actions(self):
        return [(k, label, enabled) for k, label, enabled, _w in self.controls()]

    def failed_flagged(self):
        return bool(str(self.p.failed_value_label.cget("foreground")))

    def strip_enabled(self):
        return {label: enabled for top in self.root.winfo_children() if top is not self.p.actions_frame
                for _k, label, enabled, _w in self.controls(top)
                if label in ("Stop all tasks", "Interrupt script", "Kill ADB server")}
