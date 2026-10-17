import importlib
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

from tests import stub_tk
from tests.mock_backend import MockBackend


class UiSmokeTests(unittest.TestCase):
    """Runs the real ui.py against a fake Tk (logic only, not appearance)."""

    def setUp(self):
        self.patch = mock.patch.dict(sys.modules, {"tkinter": stub_tk.make_module()})
        self.patch.start()
        sys.modules.pop("fkeyautomator.ui", None)
        self.ui = importlib.import_module("fkeyautomator.ui")
        from fkeyautomator.controller import Controller
        self.path = os.path.join(tempfile.mkdtemp(), "settings.json")
        self.backend = MockBackend()
        self.ctl = Controller(self.backend, config_path=self.path, admin=False,
                              relaunch=lambda: True)
        self.win = self.ui.MainWindow(self.ctl)

    def tearDown(self):
        self.ctl.runner.stop()
        self.patch.stop()
        sys.modules.pop("fkeyautomator.ui", None)

    def click(self, widget):
        widget.bindings["<Button-1>"](stub_tk.Event())

    def pump(self, until, timeout=3.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.win._poll()
            if until():
                return True
            time.sleep(0.005)
        return False

    def test_builds_ten_rows_with_f_labels_and_dpi_scaling(self):
        self.assertEqual(len(self.win.rows), 10)
        self.assertEqual([r.keycap.label for r in self.win.rows], ["F%d" % n for n in range(1, 11)])
        self.assertEqual(self.ui.px(10), 15)                       # 144 dpi -> 1.5x
        self.assertEqual(self.win.root.geometry_value, "+730+126")  # centred, upper third

    def test_key_list_has_vertical_scrollbar_and_mousewheel_support(self):
        self.assertIsNotNone(self.win.key_scrollbar)
        result = self.win._on_scroll_wheel(stub_tk.Event(delta=-120))
        self.assertEqual(result, "break")
        self.assertEqual(self.win.key_canvas.last_scroll, (1, "units"))

    def test_macro_library_and_recorder_are_separate_and_share_macros(self):
        from fkeyautomator.macros import MacroEvent
        self.win._on_macros()
        self.win._new_macro()
        macro = self.ctl.get_macro()
        self.assertEqual(macro.name, "ماكرو 1")
        self.ctl.update_macro(macro.id, events=[
            MacroEvent("key", "key", "down", 0, 0x1E, 0x41),
            MacroEvent("mouse", "left", "up", 24),
            MacroEvent("mouse", "move", "move", 8, x=320, y=240),
        ])
        self.win._refresh_macro_list(macro.id)
        self.assertEqual(self.win.macro_tree.get_children(), ("0", "1", "2"))
        self.assertEqual(self.win.macro_tree.rows["0"][2], "A")
        self.assertEqual(self.win.macro_tree.rows["1"][2], "زر أيسر")
        self.assertEqual(self.win.macro_tree.rows["2"][1], "حركة")
        self.assertEqual(self.win.macro_tree.rows["2"][2], "(320، 240)")
        self.win._on_recorder()
        self.assertIsNot(self.win.recorder_window, self.win.macro_window)
        self.assertIsNot(self.win.recorder_window, self.win.root)
        self.assertEqual(self.win.recorder_tree.get_children(), ("0", "1", "2"))
        self.win.recorder_repeat_var.set("25")
        self.win.recorder_repeat_forever_var.set(True)
        self.win._save_recorder_repeat()
        self.assertEqual((macro.repeat_count, macro.repeat_forever), (25, True))

        # Closing the recorder must leave the independently managed library open.
        self.win._close_recorder_window()
        self.assertIsNotNone(self.win.macro_window)
        self.assertTrue(self.win.macro_window.winfo_exists())
        self.assertEqual(self.ctl.get_macro().id, macro.id)

    def test_recorder_opens_directly_from_main_window(self):
        self.win._on_recorder()
        self.assertIsNotNone(self.win.recorder_window)
        self.assertIsNone(self.win.macro_window)
        self.win._on_macros()
        self.assertIsNot(self.win.recorder_window, self.win.macro_window)

    def test_theme_toggle_persists_and_applies_to_secondary_windows(self):
        self.win._on_recorder()
        self.win._on_macros()
        self.assertEqual(self.ctl.settings.theme, "dark")
        self.win._toggle_theme()
        self.assertEqual(self.ctl.settings.theme, "light")
        saved = self.ctl._config_path
        from fkeyautomator import settings as cfg
        self.assertEqual(cfg.load(saved).theme, "light")

    def test_initial_state_buttons_and_status(self):
        self.assertTrue(self.win.start_btn.enabled)
        self.assertFalse(self.win.stop_btn.enabled)
        self.assertEqual(self.win.pill.opts["text"], "جاهز")

    def test_toggle_click_updates_controller_and_keycap(self):
        row = self.win.rows[2]
        self.assertTrue(row.keycap.dim)
        self.click(row.toggle)
        self.assertTrue(self.ctl.settings.keys[2].enabled)
        self.assertFalse(row.keycap.dim)
        self.click(row.toggle)
        self.assertFalse(self.ctl.settings.keys[2].enabled)

    def test_keycap_click_toggles_enable_state(self):
        row = self.win.rows[0]
        row.keycap.bindings["<ButtonRelease-1>"](stub_tk.Event())
        self.assertTrue(self.ctl.settings.keys[0].enabled)
        row.keycap.bindings["<ButtonRelease-1>"](stub_tk.Event())
        self.assertFalse(self.ctl.settings.keys[0].enabled)

    def test_range_and_fixed_delay_modes_keep_existing_settings(self):
        row = self.win.rows[0]
        row.min_stepper.var.set("1250")
        self.assertEqual(self.ctl.settings.keys[0].delay_min_ms, 1250)
        self.assertEqual(self.ctl.settings.keys[0].delay_max_ms, 1250)
        row.max_stepper.var.set("1500")
        self.assertEqual(self.ctl.settings.keys[0].delay_max_ms, 1500)

        self.click(row.fixed_toggle)
        self.assertTrue(self.ctl.settings.keys[0].fixed_delay)
        self.assertEqual(row.max_stepper.entry.opts["state"], "disabled")
        row.min_stepper.var.set("750")
        self.assertEqual(self.ctl.settings.keys[0].fixed_delay_ms, 750)

        self.click(row.fixed_toggle)
        self.assertFalse(self.ctl.settings.keys[0].fixed_delay)
        self.assertEqual(row.min_stepper.value, 1250)
        self.assertEqual(row.max_stepper.entry.opts["state"], "normal")

    def test_stepper_typing_buttons_and_validation(self):
        st = self.win.rows[0].stepper
        self.assertTrue(st._validate(""))
        self.assertTrue(st._validate("1500"))
        self.assertFalse(st._validate("12a"))
        self.assertFalse(st._validate("-5"))
        self.assertFalse(st._validate("12345678"))                 # longer than the max has digits
        st.var.set("250")
        self.assertEqual(self.ctl.settings.keys[0].delay_ms, 250)
        self.click(st.plus)
        self.assertEqual(self.ctl.settings.keys[0].delay_ms, 350)
        self.assertEqual(st.var.get(), "350")
        for _ in range(10):
            self.click(st.minus)
        self.assertEqual(self.ctl.settings.keys[0].delay_ms, 0)    # clamped at 0
        st.var.set("")                                             # emptied while typing
        self.assertEqual(self.ctl.settings.keys[0].delay_ms, 0)    # keeps last valid value
        st._commit()
        self.assertEqual(st.var.get(), "0")
        st.var.set("99999999")                                     # above the maximum
        self.assertEqual(self.ctl.settings.keys[0].delay_ms, 3_600_000)

    def test_start_without_selection_shows_arabic_hint(self):
        self.win.start_btn.bindings["<ButtonRelease-1>"](stub_tk.Event())
        self.assertIn("فعّل مفتاحًا", self.win.message.opts["text"])
        self.assertFalse(self.ctl.state.running)

    def test_full_flow_start_light_up_stop_close(self):
        self.ctl.set_start_delay(0); self.ctl.set_hold(10)
        for i, ms in ((0, 400), (3, 400)):
            self.click(self.win.rows[i].toggle)
            self.win.rows[i].stepper.var.set(str(ms))
        self.win.start_btn.bindings["<ButtonRelease-1>"](stub_tk.Event())
        self.assertFalse(self.win.start_btn.enabled)
        self.assertTrue(self.win.stop_btn.enabled)

        self.assertTrue(self.pump(lambda: self.win.rows[0].keycap.pressed))   # F1 cap lit
        self.assertEqual(self.win.pill.opts["text"], "يعمل")
        self.assertTrue(self.pump(lambda: self.win.rows[3].keycap.pressed))   # then F4
        self.assertFalse(self.win.rows[0].keycap.pressed)
        self.assertTrue(self.pump(lambda: not any(r.keycap.pressed for r in self.win.rows), 1.0))

        self.win.stop_btn.bindings["<ButtonRelease-1>"](stub_tk.Event())
        self.assertTrue(self.pump(lambda: not self.ctl.state.running))
        self.assertEqual(self.win.pill.opts["text"], "متوقف")
        self.assertTrue(self.win.start_btn.enabled)
        self.assertFalse(self.win.stop_btn.enabled)
        self.assertEqual(self.backend.down_now, set())
        self.assertIn("الضغطات", self.win.stats.opts["text"])

        self.win._on_close()
        self.assertTrue(self.win.root.destroyed)
        self.assertEqual((self.ctl.settings.window_x, self.ctl.settings.window_y), (321, 123))
        from fkeyautomator import settings as cfg
        saved = cfg.load(self.path)
        self.assertEqual([k.enabled for k in saved.keys].count(True), 2)
        self.assertEqual(saved.keys[0].delay_ms, 400)

    def test_start_button_enters_running_state_without_countdown(self):
        self.ctl.set_start_delay(3)
        self.click(self.win.rows[0].toggle)
        self.win.start_btn.bindings["<ButtonRelease-1>"](stub_tk.Event())
        self.assertEqual(self.win.pill.opts["text"], "يعمل")
        self.ctl.stop()

    def test_release_outside_button_does_not_fire(self):
        self.click(self.win.rows[0].toggle)
        self.win.start_btn.bindings["<ButtonRelease-1>"](stub_tk.Event(x=500, y=5))
        self.assertFalse(self.ctl.state.running)

    def test_every_message_formats_and_renders(self):
        from fkeyautomator import strings as T
        for key, text in T.MESSAGES.items():
            self.assertTrue(text.format(detail="x"))
            self.ctl.state.message_kind, self.ctl.state.message_key = "warn", key
            self.win.render()
            self.assertTrue(self.win.message.opts["text"])

    def test_admin_footer_and_relaunch(self):
        self.assertTrue(self.win._on_admin() is None)              # relaunch ok -> window closes
        self.assertTrue(self.win.root.destroyed)

    def test_shade_helper(self):
        self.assertEqual(self.ui.shade("#808080", 1.0), "#808080")
        self.assertEqual(self.ui.shade("#FFFFFF", 1.5), "#FFFFFF")
        self.assertEqual(self.ui.shade("#101010", 0.0), "#000000")


if __name__ == "__main__":
    unittest.main()
