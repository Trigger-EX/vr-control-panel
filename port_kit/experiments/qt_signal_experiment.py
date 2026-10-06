import os, sys, signal, time, subprocess
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication, QMainWindow, QDockWidget, QPlainTextEdit, QLabel
from PySide6.QtCore import QTimer, Qt
import PySide6.QtTest as QtTest
mode = sys.argv[1]
app = QApplication([])
w = QMainWindow(); w.setCentralWidget(QLabel("x"))
for name in ("Live log", "Terminal"):
    d = QDockWidget(name, w); d.setObjectName(name); d.setWidget(QPlainTextEdit()); w.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, d)
docks = w.findChildren(QDockWidget); w.tabifyDockWidget(docks[0], docks[1])
w.show()
child = subprocess.Popen(["sleep", "300"], start_new_session=True)
print("child", child.pid, flush=True)
def cleanup():
    os.killpg(child.pid, signal.SIGKILL); print("cleanup ran", flush=True)
if mode == "sysexit":
    def h(signum, frame):
        cleanup(); sys.exit(0)
elif mode == "quit":
    def h(signum, frame):
        cleanup(); QTimer.singleShot(0, app.quit)
signal.signal(signal.SIGTERM, h)
if "tick" in sys.argv:
    t = QTimer(); t.timeout.connect(lambda: None); t.start(100)
state = w.saveState()
print("dock state bytes", len(bytes(state)), "QtTest ok", hasattr(QtTest, "QTest"), flush=True)
rc = app.exec()
print("exec returned", rc, flush=True)
