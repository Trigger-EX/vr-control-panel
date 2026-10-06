"""Stubs shared by the Tk and Qt harnesses. Installed into a freshly loaded
panel module *before* ControlPanel is constructed, so nothing ever reaches a
real headset, a real adb or a real process group:

  popen_in_own_group  -> records the command, returns a FakeProc
  kill_process_group  -> records only. ALWAYS stubbed: a fake process with a
                         real-looking pid once made the real one signal the
                         test's own process group.
  threading.Thread    -> _run_command's worker runs synchronously (or, for a
                         "held" run, on a real thread that waits to be
                         released); every other worker (toggle readers, scrcpy)
                         is a no-op, so a started watchdog stays "running".
  subprocess.run      -> canned `adb devices` / `ps` output; everything recorded
  messagebox.*        -> recorded; askyesno answers from a queue (No if none left)
  filedialog.*        -> recorded; answers from a queue ("" if none left)

Everything the panel does is appended to Recorder.events in order, with paths,
the Python executable, the panel's pid and clock times normalized, so two
panels can be compared line for line.
"""
import os
import re
import subprocess
import sys
import threading
import types

REAL_THREADING = threading
DEFAULT_DEVICES = ["172.16.16.28:5555", "172.16.16.31:5555"]


class FakeProc:
    def __init__(self, rec, index, cmd, lines, hold_event=None):
        self.pid = 999999
        self.returncode = None
        self.index = index
        self.cmd = cmd
        self._rec = rec
        self.stdout = self._stream(list(lines), hold_event)

    def _stream(self, lines, hold_event):
        for line in lines:
            yield line + "\n"
        if hold_event is not None:
            hold_event.wait(30)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self):
        self._rec.events.append(("proc.kill", self._rec.proc_name(self)))
        self.returncode = -9

    def terminate(self):
        self.kill()

    def send_signal(self, sig):
        self._rec.events.append(("proc.signal", self._rec.proc_name(self), int(sig)))


class Recorder:
    def __init__(self, pm):
        self.pm = pm
        self.events = []
        self.answers = []          # queued askyesno answers
        self.file_answers = []     # queued filedialog answers
        self.devices = list(DEFAULT_DEVICES)
        self.devices_error = None  # an exception to raise from `adb devices`
        self.ps_lines = []         # extra lines for `ps -eo pid,args`
        self.next_outputs = []     # stdout lines for the next spawned processes, in order
        self.hold_next_run = False
        self.hold_event = None
        self.procs = []
        self.real_threads = []
        self.noop_threads = []
        self.home = os.path.expanduser("~")

    # -------------------------------------------------------- normalizing
    def norm(self, value):
        text = str(value)
        replacements = [
            (str(self.pm.SCRIPTS_CACHE_DIR), "<SCRIPTS>"),
            (str(self.pm.CONFIG_DIR), "<CFG>"),
            (sys.executable, "<PY>"),
            (self.home, "<HOME>"),
        ]
        for old, new in replacements:
            text = text.replace(old, new)
        text = re.sub(r"\b\d{2}:\d{2}:\d{2}\b", "<TIME>", text)
        text = re.sub(r"\b\d{8}_\d{6}\b", "<STAMP>", text)
        return text

    def norm_cmd(self, cmd):
        pid = str(os.getpid())
        return ["<PID>" if str(part) == pid else self.norm(part) for part in cmd]

    def proc_name(self, proc):
        if isinstance(proc, FakeProc):
            script = next((os.path.basename(str(p)) for p in proc.cmd
                           if str(p).endswith((".sh", ".py"))), str(proc.cmd[0]))
            return f"#{proc.index}:{script}"
        return repr(proc)

    def sentinels(self):
        return {"show_mode": self.pm.SHOW_MODE_FILE.exists(),
                "sync_in_progress": self.pm.SYNC_IN_PROGRESS_FILE.exists()}

    # ------------------------------------------------------------ stubs
    def popen(self, cmd, **kwargs):
        index = len(self.procs)
        lines = self.next_outputs.pop(0) if self.next_outputs else []
        proc = FakeProc(self, index, list(cmd), lines, self.hold_event if self._holding_spawn else None)
        self._holding_spawn = False
        self.procs.append(proc)
        meta = {"cwd": self.norm(kwargs["cwd"]) if kwargs.get("cwd") else None,
                "at_spawn": self.sentinels()}
        env = kwargs.get("env")
        if env is not None:
            meta["env"] = {k: env[k] for k in sorted(env) if k.startswith("SDL_")}
        self.events.append(("spawn", self.norm_cmd(cmd), meta))
        return proc

    _holding_spawn = False

    def kill(self, proc, force):
        self.events.append(("kill", self.proc_name(proc), bool(force)))

    def run(self, cmd, *args, **kwargs):
        self.events.append(("run", self.norm_cmd(cmd)))
        if list(cmd[:2]) == ["adb", "devices"]:
            if self.devices_error is not None:
                raise self.devices_error
            out = "List of devices attached\n" + "".join(f"{d}\tdevice\n" for d in self.devices)
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if cmd and cmd[0] == "ps":
            return subprocess.CompletedProcess(cmd, 0, "    PID ARGS\n" + "".join(self.ps_lines), "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def dialog(self, kind):
        def show(title=None, message=None, **options):
            if kind == "askyesno":
                if self.answers:
                    answer = bool(self.answers.pop(0))
                    self.events.append(("dialog", kind, self.norm(title), self.norm(message), answer))
                else:
                    answer = False
                    self.events.append(("dialog", kind, self.norm(title), self.norm(message), "UNSCRIPTED->No"))
                return answer
            self.events.append(("dialog", kind, self.norm(title), self.norm(message)))
            return "ok"
        return show

    def file_dialog(self, kind):
        def ask(title=None, **options):
            answer = self.file_answers.pop(0) if self.file_answers else ""
            self.events.append(("filedialog", kind, self.norm(title), self.norm(answer)))
            return answer
        return ask

    def thread_class(self):
        rec = self

        class ThreadStub:
            def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
                self._target, self._args, self._kwargs = target, args, kwargs or {}
                qualname = getattr(target, "__qualname__", repr(target))
                self._qualname = qualname
                self._real = None
                if "_run_command" in qualname:
                    self.mode = "real" if rec.hold_next_run else "sync"
                    if rec.hold_next_run:
                        rec.hold_next_run = False
                        rec._holding_spawn = True
                else:
                    self.mode = "noop"

            def start(self):
                if self.mode == "sync":
                    self._target(*self._args, **self._kwargs)
                elif self.mode == "real":
                    self._real = REAL_THREADING.Thread(target=self._target, args=self._args,
                                                       kwargs=self._kwargs, daemon=True)
                    rec.real_threads.append(self._real)
                    self._real.start()
                else:
                    rec.noop_threads.append(self._qualname)

            def is_alive(self):
                return self._real is not None and self._real.is_alive()

            def join(self, timeout=None):
                if self._real is not None:
                    self._real.join(timeout)

        return ThreadStub


def install(pm):
    """Installs every stub into the loaded panel module `pm`; returns the Recorder."""
    rec = Recorder(pm)
    pm.popen_in_own_group = rec.popen
    pm.kill_process_group = rec.kill
    pm.subprocess = types.SimpleNamespace(**{k: getattr(subprocess, k) for k in dir(subprocess)
                                             if not k.startswith("__")})
    pm.subprocess.run = rec.run
    fake_threading = types.SimpleNamespace(**{k: getattr(threading, k) for k in dir(threading)
                                              if not k.startswith("__")})
    fake_threading.Thread = rec.thread_class()
    pm.threading = fake_threading
    for kind in ("showinfo", "showwarning", "showerror", "askyesno"):
        setattr(pm.messagebox, kind, rec.dialog(kind))
    for kind in ("askdirectory", "askopenfilename"):
        setattr(pm.filedialog, kind, rec.file_dialog(kind))
    if hasattr(pm, "spawn_terminal_session"):
        def fake_session(argv, rows=24, cols=80, cwd=None):
            rec.events.append(("terminal_session", rec.norm_cmd(argv)))
            proc = FakeProc(rec, len(rec.procs), list(argv), [])
            rec.procs.append(proc)
            return proc, os.open(os.devnull, os.O_RDWR)
        pm.spawn_terminal_session = fake_session
    return rec
