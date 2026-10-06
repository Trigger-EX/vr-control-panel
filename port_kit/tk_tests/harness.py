import importlib.util, os, sys, tempfile, types, subprocess, time
HOME = os.environ.setdefault("CXVR_TEST_HOME", tempfile.mkdtemp(prefix="cxvrhome_"))
os.environ["HOME"] = HOME
real_run = subprocess.run

def load(path):
    spec = importlib.util.spec_from_file_location("pm_" + str(abs(hash(path)))[:6], path)
    pm = importlib.util.module_from_spec(spec); spec.loader.exec_module(pm)
    pm.spawned = []; pm.killed = []; pm.dialogs = []
    class FakeProc:
        pid = 999999
        def __init__(self): self.stdout = iter(()); self.returncode = None
        def poll(self): return None
        def wait(self, timeout=None): return 0
    def fake_popen(cmd, **kw):
        pm.spawned.append(cmd); return FakeProc()
    pm.popen_in_own_group = fake_popen
    pm.kill_process_group = lambda proc, force: pm.killed.append((proc, force))
    pm.DEVICES = ["172.16.16.28:5555", "172.16.16.31:5555"]
    def fake_run(cmd, *a, **kw):
        if cmd[:2] == ["adb", "devices"]:
            out = "List of devices attached\n" + "".join(f"{d}\tdevice\n" for d in pm.DEVICES)
            return subprocess.CompletedProcess(cmd, 0, out, "")
        if cmd and cmd[0] == "ps":
            return subprocess.CompletedProcess(cmd, 0, "PID ARGS\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    pm.subprocess = types.SimpleNamespace(**{k: getattr(subprocess, k) for k in dir(subprocess) if not k.startswith("__")})
    pm.subprocess.run = fake_run
    pm.ASK = True
    mb = pm.messagebox
    for name in ("showinfo", "showerror", "showwarning"):
        setattr(mb, name, (lambda n: lambda *a, **k: pm.dialogs.append((n, a)))(name))
    mb.askyesno = lambda *a, **k: (pm.dialogs.append(("askyesno", a)), pm.ASK)[1]
    return pm

def pump(root, secs=0.3):
    end = time.time() + secs
    while time.time() < end:
        root.update(); time.sleep(0.02)

def wait_for(root, cond, secs=5):
    end = time.time() + secs
    while time.time() < end:
        root.update()
        if cond(): return True
        time.sleep(0.03)
    return False
