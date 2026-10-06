import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, ".")
import cxvr_pyside6_preview as pv
from PySide6.QtWidgets import QApplication
app = QApplication([]); app.setStyle("Fusion"); app.setFont(pv.app_font()); app.setStyleSheet(pv.QSS)
w = pv.Preview(); w.resize(1280, 800); w.show(); app.processEvents()
res = []
def ck(n, c, x=""): res.append(bool(c)); print("PASS" if c else "FAIL", n, "" if c else x)
ck("70 tiles", len(w.tiles) == 70)
w.tiles["172.16.16.43:5555"].click(); app.processEvents()
ck("click selects", w.selected == "172.16.16.43:5555" and w.big_serial.text() == "172.16.16.43")
ck("not live -> status says no view", "No view open" in w.live_status.text())
w.tiles["172.16.16.43:5555"].doubleClicked.emit(); app.processEvents()
ck("double-click opens (replaces old view)", w.live == {"172.16.16.43:5555"} and w.tiles["172.16.16.28:5555"].property("live") is False)
before = w.selected; w.step(1); app.processEvents()
ck("Next steps and moves the open view", w.selected != before and w.live == {w.selected})
w.step(-1); ck("Prev returns", w.selected == before)
w.filter_box.setText("28"); app.processEvents()
ck("filter narrows to one and selects it", len(w.grid_host.shown) == 1 and w.selected == "172.16.16.28:5555")
w.filter_box.setText(""); app.processEvents()
ck("clearing filter restores all", len(w.grid_host.shown) == 70)
w.double_switch.setChecked(False); ck("double view off disables monitor picker", not w.monitor_combo.isEnabled())
w.show_switch.setChecked(True); app.processEvents(); ck("show mode bar", w.show_bar.isVisible())
for name in list(w.nav_buttons):
    w.nav_buttons[name].click(); app.processEvents()
ck("every sidebar page opens", True)
w.nav_buttons["Screen Capture"].click(); app.processEvents()
ck("screen capture rebuilds", len(w.tiles) == 70 and w.grid_host.isVisible())
print("preview", sum(res), "/", len(res))
