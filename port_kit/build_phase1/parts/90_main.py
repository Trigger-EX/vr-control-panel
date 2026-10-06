

_active_panel = None  # set by main(); read by _handle_termination_signal


def _handle_termination_signal(signum, frame):
    """SIGTERM (a task manager or `kill`), SIGINT (Ctrl+C, or an IDE's Stop
    button) and SIGHUP (the terminal that started it closed): clean up every
    process the panel started, then ask Qt to quit. It never raises -- an
    exception here would surface inside some Qt callback instead of ending the
    program. Python only gets to run this handler while Python code is running,
    which the log pump's 100 ms timer guarantees; each daemon's own --parent-pid
    check covers whatever this can't reach (SIGKILL, a hard crash)."""
    if _active_panel is not None:
        try:
            _active_panel._cleanup_subprocesses()
        except Exception:
            pass
    app = QApplication.instance()
    if app is not None:
        app.quit()


def _report_unhandled(exc_type, exc, tb):
    """An error inside a Qt callback doesn't stop the panel; Python prints it and
    carries on. Double-clicked, there's no terminal to print to, so it also goes
    into the live log, where it can be seen and reported."""
    sys.__excepthook__(exc_type, exc, tb)
    panel = _active_panel
    if panel is not None:
        import traceback
        text = "".join(traceback.format_exception(exc_type, exc, tb)).rstrip()
        panel.log_queue.put(("line", f"\n[panel error -- please report this]\n{text}\n"))


def make_app(argv=None):
    """The QApplication with the panel's look (Fusion style, fonts, style sheet).
    Tests use this too, so they see exactly what the user sees."""
    app = QApplication.instance() or QApplication(list(argv if argv is not None else sys.argv))
    app.setApplicationName("CXVR Control Panel")
    app.setStyle("Fusion")
    app.setFont(app_font())
    app.setStyleSheet(QSS)
    return app


def _save_screenshots(app, panel, out_dir):
    """--screenshot DIR: every ported page as a PNG, then exit. Starts nothing."""
    os.makedirs(out_dir, exist_ok=True)
    width, height = (int(v) for v in os.environ.get("SHOT_SIZE", "1280x860").split("x"))
    panel.resize(width, height)
    panel.show()
    for name, opener in (("connect", panel.show_menu_connect), ("volume", panel.show_menu_volume),
                         ("power", panel.show_menu_power), ("heartbeat", panel.show_menu_heartbeat),
                         ("testing", panel.show_menu_testing)):
        opener()
        for _ in range(6):
            app.processEvents()
        panel.grab().save(os.path.join(out_dir, f"{name}_{width}x{height}.png"))
    panel.close()


def main():
    global _active_panel
    shots = None
    if "--screenshot" in sys.argv:
        index = sys.argv.index("--screenshot")
        shots = sys.argv[index + 1] if index + 1 < len(sys.argv) else "cxvr_screenshots"
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = make_app()
    panel = ControlPanel(safe_preview=shots is not None)
    _active_panel = panel

    for name in ("SIGTERM", "SIGINT", "SIGHUP"):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), _handle_termination_signal)
            except (ValueError, OSError):
                pass  # e.g. not running in the main thread -- skip, other layers still apply

    # Final fallback: fires on normal interpreter shutdown, sys.exit(), and
    # most unhandled exceptions (not on SIGKILL/os._exit(), which is exactly
    # why the --parent-pid self-check in each daemon exists as a backstop
    # that doesn't depend on this process getting to clean up at all).
    atexit.register(panel._cleanup_subprocesses)
    sys.excepthook = _report_unhandled

    if shots is not None:
        _save_screenshots(app, panel, shots)
        return 0
    panel.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
