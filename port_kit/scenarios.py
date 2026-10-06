"""Differential scenarios: the same steps run against the Tk and the Qt panel
(record.py), then compare.py diffs what each one did.

A scenario is a dict:
  name      unique id
  steps     list of tuples (vocabulary below)
  config    dict written to config.json before the panel starts (optional)
  sentinels {"show_mode": True} files present before start (optional)
  ps        extra `ps -eo pid,args` lines seen at startup (optional)
  devices   what `adb devices` reports (optional; default two headsets)
  phase     the port phase whose pages it needs (record.py skips later ones)

Steps (every click goes through the real widget, found by its label):
  ("open", page)                    sidebar (Qt) / main menu (Tk); also "testing_power"
  ("click", label[, nth])           a button or checkbox on the current page (first line of its text)
  ("click_in", card, label)         ... inside the card with that title
  ("strip", label)                  Stop all tasks / Interrupt script / Kill ADB server
  ("row", item, label)              Open / Mark tested on a Testing-hub row
  ("toggle", key)                   a Start/Stop switch (toggle_buttons key)
  ("type", var, text)               type into the field bound to that variable
  ("check", var, bool)              set the checkbox bound to that variable
  ("choose", var, value)            pick an entry in the dropdown bound to that variable
  ("refresh", var)                  the Refresh next to that dropdown
  ("set", var, value)               set a variable directly (only where a page has no field for it yet)
  ("show_mode", bool)               the Show Mode control
  ("answer", *bools)                queue answers for the next confirmations
  ("files", *paths)                 queue answers for the next file pickers
  ("devices", [serials]) / ("devices_error", text)
  ("output", [lines])               stdout of the next process the panel starts
  ("hold",)                         the next one-shot run keeps running until ("release",)
  ("release",)
  ("proc_ends", key)                a background task exits on its own (as its reader thread reports it)
  ("call", method, *args)          logic whose page arrives in a later phase (see record.py)
  ("setattr", name, value)
  ("pump",)
  ("snap", what)                    extra snapshot: "actions", "picker:<var>", "nav", "strip"
"""

TWO = ["172.16.16.28:5555", "172.16.16.31:5555"]
ONE = "172.16.16.28:5555"
GATED = ["power.reboot", "power.poweroff", "sleepwake.overheat_watchdog", "sleepwake.blackscreen_probe",
         "delete_video.delete", "debug.capture_snapshot", "terminal.shell"]
SUMMARY = ["=========================== SUMMARY ===========================",
           "Connected & stable: 7", "Fixed & confirmed this run: 2", "FAILED to confirm: 1",
           "TOTAL stable with fix applied: 9 / 10",
           "==============================================================="]

SCENARIOS = []


def S(name, steps, phase=1, **extra):
    assert not any(s["name"] == name for s in SCENARIOS), name
    SCENARIOS.append(dict(name=name, steps=steps, phase=phase, **extra))


# ------------------------------------------------------------------ startup
S("startup_default", [])
S("startup_visual_check", [], config={"visual_check": True})
S("startup_old_package_setting", [], config={"package": "com.example.OtherApp"})
S("startup_same_package_setting", [], config={"package": "com.CulturalXchange.BibleSchool"})
S("startup_show_mode_file_present", [("snap", "strip")], sentinels={"show_mode": True})
S("startup_other_instance_warning", [],
  ps=["  4242 bash <CFGDIR>/embedded_scripts/stayAwake.sh --parent-pid 1\n",
      "  4243 bash /somewhere/else/stayAwake.sh\n"])
S("startup_settings_restored", [("open", "volume"), ("snap", "actions")],
  config={"visual_check": True, "last_volume_op": "Max (all connected headsets) at 10:11:12",
          "tested_features": ["power.reboot"]})

# ------------------------------------------------------------------ connect
S("connect_page", [("open", "connect"), ("snap", "actions")])
S("connect_normal", [("open", "connect"), ("output", SUMMARY), ("click", "Normal Connect"), ("pump",)])
S("connect_normal_no_summary", [("open", "connect"), ("output", ["nothing useful"]), ("click", "Normal Connect"),
                                ("pump",)])
S("connect_visual_check_on", [("open", "connect"), ("check", "visual_check_var", True),
                              ("click", "Normal Connect"), ("pump",)])
S("connect_visual_check_off_again", [("open", "connect"), ("check", "visual_check_var", False),
                                     ("click", "Full Scan"), ("pump",)], config={"visual_check": True})
S("connect_full_scan", [("open", "connect"), ("output", SUMMARY), ("click", "Full Scan"), ("pump",)])
S("connect_purge_yes", [("open", "connect"), ("answer", True), ("click", "Purge & Reconnect All"), ("pump",)])
S("connect_purge_no", [("open", "connect"), ("answer", False), ("click", "Purge & Reconnect All"), ("pump",)])
S("connect_purge_visual_check", [("open", "connect"), ("answer", True), ("click", "Purge & Reconnect All"),
                                 ("pump",)], config={"visual_check": True})
S("connect_buttons_disabled_while_running",
  [("open", "connect"), ("hold",), ("click", "Normal Connect"), ("snap", "actions"), ("snap", "strip"),
   ("release",), ("snap", "actions")])
S("connect_page_opened_mid_run",
  [("open", "connect"), ("hold",), ("click", "Full Scan"), ("open", "volume"), ("snap", "actions"),
   ("release",), ("snap", "actions")])

# ------------------------------------------------------------------ strip
S("interrupt_nothing_running", [("strip", "Interrupt script")])
S("interrupt_escalates", [("open", "connect"), ("hold",), ("click", "Normal Connect"),
                          ("strip", "Interrupt script"), ("strip", "Interrupt script"), ("release",)])
S("interrupt_counter_resets_after_run", [("open", "connect"), ("hold",), ("click", "Normal Connect"),
                                         ("strip", "Interrupt script"), ("release",),
                                         ("hold",), ("click", "Full Scan"), ("strip", "Interrupt script"),
                                         ("release",)])
S("stop_all_with_watchdog_and_heartbeat", [("open", "heartbeat"), ("toggle", "heartbeat"),
                                           ("strip", "Stop all tasks"), ("snap", "actions")])
S("stop_all_when_nothing_running", [("strip", "Stop all tasks"), ("strip", "Stop all tasks")])
S("kill_adb_yes", [("answer", True), ("strip", "Kill ADB server")])
S("kill_adb_no", [("answer", False), ("strip", "Kill ADB server")])
S("kill_adb_names_active_tasks", [("open", "heartbeat"), ("toggle", "heartbeat"), ("answer", False),
                                  ("strip", "Kill ADB server")])
S("show_mode_on", [("show_mode", True), ("snap", "strip")])
S("show_mode_on_then_off", [("show_mode", True), ("show_mode", False), ("snap", "strip")])
S("show_mode_off_from_saved_on", [("show_mode", False)], sentinels={"show_mode": True})

# ------------------------------------------------------------------ heartbeat
S("heartbeat_page", [("open", "heartbeat"), ("snap", "actions")])
S("heartbeat_start", [("open", "heartbeat"), ("toggle", "heartbeat"), ("snap", "actions")])
S("heartbeat_start_stop", [("open", "heartbeat"), ("toggle", "heartbeat"), ("toggle", "heartbeat"),
                           ("snap", "actions")])
S("heartbeat_ends_on_its_own", [("open", "heartbeat"), ("toggle", "heartbeat"), ("proc_ends", "heartbeat"),
                                ("pump",), ("snap", "actions")])
S("heartbeat_state_kept_across_pages", [("open", "heartbeat"), ("toggle", "heartbeat"), ("open", "connect"),
                                        ("open", "heartbeat"), ("snap", "actions")])
S("headtracking_ends_on_its_own", [("proc_ends", "htWatchdog"), ("pump",)])
# KNOWN BUG in the shared logic (Tk and Qt alike, reported 27 Sep 2026): a task that exits within one
# pump tick of starting stays "Running" -- _refresh_toggle_state compares against a snapshot that
# _start_toggle never updates. Both panels must behave the same until a mirrored fix is approved.
S("heartbeat_dies_within_one_tick", [("open", "heartbeat"), ("start_and_end_in_one_tick", "heartbeat"),
                                     ("snap", "actions")])

# ------------------------------------------------------------------ volume
S("volume_page", [("open", "volume"), ("snap", "actions"), ("snap", "picker:volume_target_var")])
S("volume_check_all", [("open", "volume"), ("click", "Check current volume"), ("pump",)])
S("volume_refresh", [("open", "volume"), ("refresh", "volume_target_var"), ("snap", "picker:volume_target_var")])
S("volume_refresh_none_connected", [("devices", []), ("open", "volume"), ("refresh", "volume_target_var"),
                                    ("snap", "picker:volume_target_var")])
S("volume_refresh_error", [("devices_error", "adb: not found"), ("open", "volume"),
                           ("refresh", "volume_target_var")])
S("volume_check_one", [("open", "volume"), ("refresh", "volume_target_var"), ("choose", "volume_target_var", ONE),
                       ("click", "Check current volume"), ("pump",)])
S("volume_target_gone_after_refresh", [("open", "volume"), ("refresh", "volume_target_var"),
                                       ("choose", "volume_target_var", "172.16.16.31:5555"),
                                       ("devices", [ONE]), ("refresh", "volume_target_var"),
                                       ("click", "Check current volume"), ("pump",)])
S("volume_target_kept_across_pages", [("open", "volume"), ("refresh", "volume_target_var"),
                                      ("choose", "volume_target_var", ONE), ("open", "connect"), ("open", "volume"),
                                      ("click", "Check current volume"), ("pump",)])
for label, _level in (("Max", "max"), ("-2", 13), ("-3", 12), ("-4", 11)):
    S(f"volume_preset_{label}_all", [("open", "volume"), ("click", label), ("pump",)])
S("volume_preset_-3_one", [("open", "volume"), ("refresh", "volume_target_var"),
                           ("choose", "volume_target_var", ONE), ("click", "-3"), ("pump",)])
S("volume_mute_yes_all", [("open", "volume"), ("answer", True), ("click", "Mute"), ("pump",)])
S("volume_mute_no", [("open", "volume"), ("answer", False), ("click", "Mute"), ("pump",)])
S("volume_mute_yes_one", [("open", "volume"), ("refresh", "volume_target_var"),
                          ("choose", "volume_target_var", ONE), ("answer", True), ("click", "Mute"), ("pump",)])
S("volume_set_typed", [("open", "volume"), ("type", "volume_level_var", "5"), ("click", "Set Volume"), ("pump",)])
S("volume_set_default", [("open", "volume"), ("click", "Set Volume"), ("pump",)])
S("volume_set_spaces", [("open", "volume"), ("type", "volume_level_var", " 7 "), ("click", "Set Volume"),
                        ("pump",)])
for bad in ("abc", "16", "", "-1", "3.5"):
    S(f"volume_set_invalid_{bad or 'empty'}", [("open", "volume"), ("type", "volume_level_var", bad),
                                                ("click", "Set Volume"), ("pump",)])
S("volume_set_zero_yes", [("open", "volume"), ("type", "volume_level_var", "0"), ("answer", True),
                          ("click", "Set Volume"), ("pump",)])
S("volume_set_zero_no", [("open", "volume"), ("type", "volume_level_var", "0"), ("answer", False),
                         ("click", "Set Volume"), ("pump",)])
S("volume_set_one_headset", [("open", "volume"), ("refresh", "volume_target_var"),
                             ("choose", "volume_target_var", "172.16.16.31:5555"), ("type", "volume_level_var", "9"),
                             ("click", "Set Volume"), ("pump",)])
S("volume_last_operation_shown", [("open", "volume"), ("click", "-2"), ("pump",), ("open", "connect"),
                                  ("open", "volume"), ("snap", "actions")])
S("volume_level_kept_across_pages", [("open", "volume"), ("type", "volume_level_var", "12"), ("open", "power"),
                                     ("open", "volume"), ("click", "Set Volume"), ("pump",)])

# ------------------------------------------------------------------ power
S("power_page_none_tested", [("open", "power"), ("snap", "actions")])
S("power_page_reboot_tested", [("open", "power"), ("snap", "actions")], config={"tested_features": ["power.reboot"]})
S("power_page_poweroff_tested", [("open", "power"), ("snap", "actions")],
  config={"tested_features": ["power.poweroff"]})
S("power_page_both_tested", [("open", "power"), ("snap", "actions")],
  config={"tested_features": ["power.reboot", "power.poweroff"]})
BOTH = {"tested_features": ["power.reboot", "power.poweroff"]}
S("power_reboot_all_yes", [("open", "power"), ("answer", True), ("click", "Reboot"), ("pump",)], config=BOTH)
S("power_reboot_all_no", [("open", "power"), ("answer", False), ("click", "Reboot"), ("pump",)], config=BOTH)
S("power_reboot_one_yes", [("open", "power"), ("refresh", "power_target_var"), ("choose", "power_target_var", ONE),
                           ("answer", True), ("click", "Reboot"), ("pump",)], config=BOTH)
S("power_poweroff_all_yes", [("open", "power"), ("answer", True), ("click", "Power Off"), ("pump",)], config=BOTH)
S("power_poweroff_all_no", [("open", "power"), ("answer", False), ("click", "Power Off"), ("pump",)], config=BOTH)
S("power_poweroff_one_yes", [("open", "power"), ("refresh", "power_target_var"),
                             ("choose", "power_target_var", "172.16.16.31:5555"), ("answer", True),
                             ("click", "Power Off"), ("pump",)], config=BOTH)
S("power_poweroff_one_no", [("open", "power"), ("refresh", "power_target_var"),
                            ("choose", "power_target_var", ONE), ("answer", False), ("click", "Power Off"),
                            ("pump",)], config=BOTH)
S("power_target_refresh_error", [("devices_error", "timed out"), ("open", "power"),
                                 ("refresh", "power_target_var")], config=BOTH)
S("power_buttons_disabled_while_running", [("open", "power"), ("hold",), ("answer", True), ("click", "Reboot"),
                                           ("snap", "actions"), ("release",), ("snap", "actions")], config=BOTH)

# ------------------------------------------------------------------ testing
for label, tested in (("none", []), ("all", GATED)):
    S(f"testing_hub_{label}_tested", [("open", "testing"), ("snap", "actions"), ("snap", "nav")],
      config={"tested_features": tested})
for key in GATED:
    S(f"testing_hub_only_{key}", [("open", "testing"), ("snap", "actions"), ("snap", "nav")],
      config={"tested_features": [key]})
    S(f"power_page_only_{key}", [("open", "power"), ("snap", "actions")], config={"tested_features": [key]})
S("testing_mark_reboot_from_hub", [("open", "testing"), ("row", "Reboot", "Mark tested"), ("snap", "actions"),
                                   ("open", "power"), ("snap", "actions")])
S("testing_mark_delete_video_from_hub", [("open", "testing"), ("row", "Delete Video", "Mark tested"),
                                         ("snap", "actions"), ("snap", "nav")])
S("testing_mark_last_one", [("open", "testing"), ("row", "Terminal", "Mark tested"), ("snap", "actions")],
  config={"tested_features": GATED[:-1]})
S("testing_power_page_none", [("open", "testing_power"), ("snap", "actions")])
S("testing_power_page_reboot_tested", [("open", "testing_power"), ("snap", "actions")],
  config={"tested_features": ["power.reboot"]})
S("testing_power_page_both_tested", [("open", "testing"), ("snap", "actions")], config=BOTH)
S("testing_power_reboot_yes", [("open", "testing_power"), ("answer", True), ("click", "Reboot"), ("pump",)])
S("testing_power_poweroff_one_yes", [("open", "testing_power"), ("refresh", "power_target_var"),
                                     ("choose", "power_target_var", ONE), ("answer", True),
                                     ("click", "Power Off"), ("pump",)])
S("testing_power_poweroff_no", [("open", "testing_power"), ("answer", False), ("click", "Power Off"), ("pump",)])
S("testing_power_mark_reboot", [("open", "testing_power"), ("click_in", "Reboot", "Mark tested"),
                                ("snap", "actions"), ("open", "power"), ("snap", "actions")])
S("testing_power_mark_poweroff", [("open", "testing_power"), ("click_in", "Power Off", "Mark tested"),
                                  ("snap", "actions")], config={"tested_features": ["power.reboot"]})
S("power_target_shared_with_testing_page", [("open", "power"), ("refresh", "power_target_var"),
                                            ("choose", "power_target_var", ONE), ("open", "testing_power"),
                                            ("answer", True), ("click", "Power Off"), ("pump",)],
  config={"tested_features": ["power.reboot"]})
S("testing_open_rows", [("open", "testing"), ("row", "Power Off", "Open"), ("snap", "actions")])


# ------------------------------------------------------------------ logic whose pages come in phase 2
# Called directly on both panels (their pages aren't ported yet); proves the copied logic behaves the
# same through the Qt compatibility layer: variables, dialogs, spawning, the sync brake.
PKG = "com.CulturalXchange.BibleSchool"
C = ("set", "content_dir_var", "/data/content")
S("logic_sync_dryrun_defaults", [C, ("call", "action_sync_dryrun"), ("pump",)])
S("logic_sync_missing_content_folder", [("call", "action_sync"), ("pump",)])
S("logic_sync_remote_target_other_app", [C, ("set", "remote_target_var", "/sdcard/Android/data/com.other/files"),
                                         ("call", "action_sync_dryrun")])
S("logic_sync_app_root_with_video_target", [C, ("set", "content_is_app_root_var", True),
                                            ("set", "remote_target_var", f"/sdcard/Android/data/{PKG}/files/Video"),
                                            ("call", "action_sync_dryrun")])
S("logic_sync_prune_no", [C, ("set", "sync_prune_var", True), ("answer", False), ("call", "action_sync"), ("pump",)])
S("logic_sync_prune_yes", [C, ("set", "sync_prune_var", True), ("answer", True), ("call", "action_sync"), ("pump",)])
S("logic_sync_verify_every_option", [
    C, ("set", "remote_target_var", f"/sdcard/Android/data/{PKG}"), ("set", "content_is_app_root_var", True),
    ("set", "sync_verify_hash_var", True), ("set", "sync_keep_screen_on_var", True),
    ("set", "sync_skip_power_config_var", True), ("set", "sync_skip_install_registration_var", True),
    ("set", "sync_workers_var", "4"), ("set", "sync_min_free_mb_var", "500"),
    ("set", "sync_devices_var", "172.16.16.28:5555,172.16.16.31:5555"),
    ("set", "sync_connect_file_var", "/data/hosts.txt"), ("set", "sync_state_dir_var", "/data/state"),
    ("set", "sync_clean_stale_var", True), ("set", "sync_check_catalog_var", True),
    ("call", "action_sync_verify"), ("pump",)])
S("logic_sync_catalog_needs_package", [C, ("set", "remote_target_var", "/sdcard/somewhere"),
                                       ("set", "sync_check_catalog_var", True), ("call", "action_sync_dryrun"),
                                       ("pump",)])
S("logic_sync_bad_workers", [C, ("set", "sync_workers_var", "0"), ("call", "action_sync_dryrun")])
S("logic_sync_bad_min_free", [C, ("set", "sync_min_free_mb_var", "lots"), ("call", "action_sync_dryrun")])
S("logic_diagnose_ok", [("set", "diagnose_workers_var", "3"), ("set", "diagnose_filesize_var", "50"),
                        ("call", "action_diagnose_bandwidth"), ("pump",)])
S("logic_diagnose_bad", [("set", "diagnose_workers_var", "x"), ("call", "action_diagnose_bandwidth")])
S("logic_popup_watchdog_bad_interval", [("set", "popup_watchdog_interval_var", "abc"),
                                        ("call", "action_toggle_popup_watchdog", None)])
S("logic_popup_watchdog_start_stop", [("set", "popup_watchdog_interval_var", "25"),
                                      ("call", "action_toggle_popup_watchdog", None),
                                      ("call", "action_toggle_popup_watchdog", None)])
S("logic_overheat_observe", [("set", "overheat_pattern_var", "  "), ("set", "overheat_interval_var", "0"),
                             ("call", "action_toggle_overheat_watchdog", None)])
S("logic_overheat_arm_no", [("set", "overheat_arm_var", True), ("set", "overheat_pattern_var", "Too hot"),
                            ("answer", False), ("call", "action_toggle_overheat_watchdog", None)])
S("logic_overheat_arm_yes", [("set", "overheat_arm_var", True), ("set", "overheat_pattern_var", "Too hot"),
                             ("answer", True), ("call", "action_toggle_overheat_watchdog", None)])
S("logic_blackscreen_arm_yes_cycle", [("set", "blackscreen_arm_var", True), ("set", "blackscreen_recovery_var", "cycle"),
                                      ("set", "blackscreen_consecutive_var", "5"), ("answer", True),
                                      ("call", "action_toggle_blackscreen_probe", None)])
S("logic_blackscreen_arm_no", [("set", "blackscreen_arm_var", True), ("answer", False),
                               ("call", "action_toggle_blackscreen_probe", None)])
S("logic_blackscreen_observe_bad_values", [("set", "blackscreen_interval_var", "-3"),
                                           ("set", "blackscreen_consecutive_var", ""),
                                           ("call", "action_toggle_blackscreen_probe", None)])
S("logic_sleep_wake_refresh_all", [("answer", True), ("call", "action_sleep_all"), ("pump",),
                                   ("call", "action_wake_all"), ("pump",), ("answer", False),
                                   ("call", "action_screen_refresh"), ("pump",)])
S("logic_sleep_one", [("set", "sleepwake_target_var", ONE), ("answer", True), ("call", "action_sleep_all"),
                      ("pump",)])
S("logic_stayawake_keepalive", [("call", "action_toggle_stayawake", None), ("call", "action_toggle_keepalive", None),
                                ("strip", "Stop all tasks")])
S("logic_capture_diagnostics_bad", [("set", "capture_repeat_var", "0"), ("call", "action_capture_diagnostics")])
S("logic_capture_diagnostics_one", [("set", "capture_device_var", ONE), ("set", "capture_repeat_var", "3"),
                                    ("set", "capture_interval_var", "7"), ("set", "capture_screencap_var", False),
                                    ("call", "action_capture_diagnostics"), ("pump",)])
S("logic_delete_video_yes", [("setattr", "_delete_video_catalog", {"@The Capitol (871t867)": "871t867"}),
                             ("set", "delete_video_selection_var", "@The Capitol (871t867)"),
                             ("set", "delete_video_device_var", ONE), ("set", "delete_video_dry_run_var", False),
                             ("answer", True), ("call", "action_delete_video"), ("pump",)])
S("logic_delete_video_dry_run_all", [("setattr", "_delete_video_catalog", {"Vid": "abc"}),
                                     ("set", "delete_video_selection_var", "Vid"),
                                     ("set", "delete_video_device_var", "ALL CONNECTED HEADSETS"),
                                     ("set", "delete_video_skip_v3local_var", True),
                                     ("set", "sync_state_dir_var", "/data/state"),
                                     ("call", "action_delete_video"), ("pump",)])
S("logic_delete_video_nothing_chosen", [("call", "action_delete_video")])
S("logic_batch_preview_bad_interval", [("set", "batch_interval_var", "0"), ("call", "action_batch_preview_toggle")])
S("logic_browse_content_folder", [("files", "/media/usb/content"), ("call", "_browse_content_dir"),
                                  ("files", ""), ("call", "_browse_state_dir")])
