"""What the Qt panel copies from the Tkinter panel, and how.

Used by build/assemble.py (Phase 1 built cxvr_control_panel_qt.py from it) and
by t_integrity.py, which every later phase runs: it re-checks that each copied
block and method in the Qt file is still character-for-character the Tk one
(after the substitutions below), and that every Tk method is accounted for.

If a critical fix is ever made to the frozen Tk panel, mirror it into the Qt
file, log it in the plan's status log, and the integrity test keeps passing
only if both files got the same change.
"""

# Module-level blocks copied verbatim. Each is located in a file by a start
# anchor and the AST node it ends with:
#   ("line", text)   -- the block starts at the one line equal to `text` (stripped)
#   ("banner", text) -- the block starts at the rule line (# --- / # ===) just above
#                       the one line equal to `text`
VERBATIM_BLOCKS = [
    ("constants", ("line", "APP_DIR = Path(__file__).resolve().parent"), "DEFAULT_CONFIG"),
    ("embedded_scripts", ("banner", "# EMBEDDED SCRIPTS -- exact byte-for-byte copies of the tested"),
     "EMBEDDED_SCRIPTS"),
    ("process_helpers", ("line", "def materialize_scripts():"), "save_config"),
    ("terminal_backend", ("banner", "# Built-in terminal (pinned under the live log)"), "end_terminal_session"),
    ("palette_and_help", ("banner", "# Look & feel -- the \"sectioned cards\" layout"), "HELP"),
]

# Applied, in this order, to every copied ControlPanel method.
GLOBAL_SUBSTITUTIONS = [
    ("tk.StringVar(", "StringVar("),
    ("tk.BooleanVar(", "BooleanVar("),
    ("tk.TclError", "RuntimeError"),     # Qt raises RuntimeError for a widget that's been deleted
]

# Per-method extras -- each one an intentional difference from the plan's section 6.
EXTRA_SUBSTITUTIONS = {
    # 6.7: once tested, Delete Video appears in the sidebar rather than on a main menu.
    "_testing_items": [('"the main menu"', '"the sidebar"')],
}

# ControlPanel methods copied from the Tk panel, in the Tk file's order.
COPIED = [
    "_set_menu_title", "_refresh_toggle_state", "_testing_items", "show_menu_testing_category",
    "_sleepwake_target", "_volume_target", "_init_settings_vars", "_is_tested", "_mark_tested",
    "_unmark_tested", "_resolve_target", "_browse_content_dir", "_browse_connect_file", "_browse_state_dir",
    "_save_settings", "_script", "_toggle_show_mode", "_load_video_catalog_from_content_dir",
    "action_delete_video_refresh_catalog", "action_delete_video_refresh_devices", "_delete_video_cmd",
    "action_delete_video", "action_capture_diagnostics", "_register", "_toggle_label", "_set_actions_enabled",
    "_run_command", "_interrupt_current", "_on_process_done", "_parse_and_show_summary", "_update_bg_tasks_label",
    "_start_toggle", "_stop_all_toggles", "action_kill_adb_server", "_massconnect_cmd", "action_connect",
    "action_full_scan", "action_purge", "action_sleep_all", "action_wake_all", "action_screen_refresh",
    "action_toggle_stayawake", "action_toggle_keepalive", "action_toggle_ht_watchdog",
    "action_toggle_popup_watchdog", "action_toggle_overheat_watchdog", "action_toggle_blackscreen_probe",
    "_record_volume_op", "action_volume_check", "action_volume_preset", "action_volume_set", "action_reboot_all",
    "action_power_off_all", "action_toggle_heartbeat", "_remote_target_matches_package", "_sync_cmd",
    "_confirm_prune_if_needed", "action_sync", "action_sync_verify", "action_sync_dryrun",
    "action_diagnose_bandwidth", "action_toggle_debug_daemon", "_titlebar_height", "_screencap_status_text",
    "action_screencap_refresh", "_scrcpy_env", "_launch_scrcpy_core", "_launch_scrcpy_and_wait_ready",
    "_launch_scrcpy", "action_screencap_connect", "_query_connected_devices", "action_screencap_connect_all",
    "action_screencap_close_all", "_stop_batch_cycle_thread", "_next_batch_device", "_update_batch_status",
    "_batch_slot_loop", "action_batch_preview_toggle", "_terminal_enabled", "_term_reader", "_term_close_session",
    "_cleanup_subprocesses", "_warn_if_other_instance_running",
]

# Tk UI methods whose job the Qt panel does with its own code (Tk name -> where it went).
REWRITTEN = {
    "__init__": "__init__", "_apply_styles": "QSS", "_build_ui": "_build_ui", "_build_status": "_build_strip",
    "_build_controls": "_build_strip", "_build_log": "_build_docks", "_toggle_log_visible": "the log dock's close/toggle",
    "_sync_actions_canvas_size": "QScrollArea (not needed)", "_update_actions_scroll": "QScrollArea (not needed)",
    "_clear_actions": "_begin_page", "_card": "_card / Card", "_caption": "Caption", "_info_button": "info_button",
    "_info_right": "Card(help=...)", "_collapsible": "Collapsible", "_toggle_row": "_toggle_row / ToggleRow",
    "_mode_pill": "ModePill", "_field_label": "field_label", "_target_row": "_target_row / TargetRow",
    "_mark_tested_right": "_mark_tested_button", "_testing_banner": "_testing_banner / TestingBanner",
    "_back_to_testing": "_back_to_testing", "show_menu_connect": "show_menu_connect",
    "show_menu_volume": "show_menu_volume", "show_menu_power": "show_menu_power",
    "show_menu_heartbeat": "show_menu_heartbeat", "show_menu_testing": "show_menu_testing",
    "_render_testing_power": "_render_testing_power", "_device_picker": "_device_picker",
    "_clear_log": "_clear_log", "_append_log": "_append_log / _append_log_lines",
    "_poll_log_queue": "_poll_log_queue (QTimer)", "_update_terminal_visibility": "_update_terminal_visibility",
    "_on_close": "closeEvent",
}

# Tk methods with no Qt counterpart (plan section 6.1: the sidebar replaces the main menu).
DROPPED = ["show_main_menu", "_menu_button"]

# Tk methods that arrive in a later phase of the port (name -> phase). Until
# then the Qt panel has placeholder pages (and, for the terminal, stubs).
LATER = {
    "show_menu_sleepwake": 2, "_watchdog_rows": 2, "_interval_setting": 2, "_row_stayawake": 2,
    "_row_keepalive": 2, "_row_headtracking": 2, "_row_popup": 2, "_row_overheat": 2, "_row_blackscreen": 2,
    "show_menu_sync": 2, "show_menu_delete_video": 2, "_build_snapshot_card": 2, "show_menu_debug": 2,
    "_render_testing_sleepwake": 2, "_render_testing_snapshot": 2, "show_menu_screencap": 3,
    "_build_terminal": 2, "_toggle_terminal_visible": 2, "_term_refresh_targets": 2, "_term_open_selected": 2,
    "_term_open": 2, "_term_send": 2, "_term_on_return": 2, "_term_history_step": 2, "_term_on_ctrl_c": 2,
    "_term_on_ctrl_d": 2, "_term_clear": 2, "_term_note": 2, "_term_apply": 2, "_term_on_exit": 2,
    "_term_update_echo_mask": 2, "_term_sync_size": 2, "_render_testing_terminal": 2, "_testing_show_terminal": 2,
}

# Names that must not appear in any copied method once substituted.
TK_ONLY_NAMES = ("tk.", "ttk.", "tkfont", "ToggleButton", "self.root")
