import os
from harness import load
pm = load(os.environ.get("CXVR_PANEL", "cxvr_control_panel.py"))
S = pm.TerminalStream
def run(chunks):
    s = S(); ops = []
    for c in chunks: ops += s.feed(c)
    return ops
checks = []
def ck(name, got, want):
    checks.append(got == want); print(("PASS" if got == want else "FAIL"), name, "" if got == want else f"got={got!r} want={want!r}")
ck("plain", run([b"hi\r\n"]), [("text","hi"),("nl",)])
ck("color stripped", run([b"\x1b[01;32muser@h\x1b[00m:~$ "]), [("text","user@h:~$ ")])
ck("split CSI", run([b"a\x1b[3", b"1mb"]), [("text","a"),("text","b")])
ck("OSC title", run([b"\x1b]0;user@h: ~\x07$ "]), [("text","$ ")])
ck("bracketed paste", run([b"\x1b[?2004h$ \x1b[?2004l"]), [("text","$ ")])
ck("split utf8", run([b"caf\xc3", b"\xa9\n"]), [("text","caf"),("text","é"),("nl",)])
ck("cr progress", run([b"10%\r20%"]), [("text","10%"),("cr",),("text","20%")])
ck("split crlf", run([b"x\r", b"\ny"]), [("text","x"),("cr",),("nl",),("text","y")])
ck("backspace+bell", run([b"ab\x08\x07c"]), [("text","ab"),("bs",),("text","c")])
ck("tab kept", run([b"a\tb"]), [("text","a\tb")])
ck("lone ESC at end held", run([b"ok\x1b"]), [("text","ok")])
ck("charset", run([b"\x1b(Bz"]), [("text","z")])
print("stream", sum(checks), "/", len(checks))
