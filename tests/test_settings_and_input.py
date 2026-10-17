import ctypes
import json
import os
import tempfile
import unittest

from fkeyautomator import keyboard_input as ki
from fkeyautomator import settings as cfg


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "sub", "settings.json")

    def test_defaults_when_missing(self):
        s = cfg.load(self.path)
        self.assertEqual(len(s.keys), 10)
        self.assertFalse(any(k.enabled for k in s.keys))
        self.assertEqual(s.keys[0].delay_ms, 1000)

    def test_roundtrip(self):
        s = cfg.Settings()
        s.theme = "light"
        s.keys[0].enabled, s.keys[0].delay_ms = True, 250
        s.keys[9].enabled, s.keys[9].delay_ms = True, 12345
        s.start_delay_s, s.hold_ms = 7, 90
        s.window_x, s.window_y = -20, 300
        self.assertTrue(cfg.save(s, self.path))
        r = cfg.load(self.path)
        self.assertEqual((r.keys[0].enabled, r.keys[0].delay_ms), (True, 250))
        self.assertEqual((r.keys[9].enabled, r.keys[9].delay_ms), (True, 12345))
        self.assertEqual((r.start_delay_s, r.hold_ms), (7, 90))
        self.assertEqual((r.window_x, r.window_y), (-20, 300))
        self.assertEqual(r.theme, "light")
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_legacy_settings_default_to_dark_and_invalid_theme_is_sanitised(self):
        self.assertEqual(cfg.Settings.from_dict({"hold_ms": 70}).theme, "dark")
        self.assertEqual(cfg.Settings.from_dict({"theme": {"bad": True}}).theme, "dark")

    def test_corrupt_file_falls_back_and_is_kept(self):
        os.makedirs(os.path.dirname(self.path))
        with open(self.path, "w") as fh:
            fh.write("{ not json")
        s = cfg.load(self.path)
        self.assertEqual(s.hold_ms, cfg.HOLD_DEFAULT)
        self.assertTrue(os.path.exists(self.path + ".bad"))

    def test_garbage_values_are_sanitised(self):
        os.makedirs(os.path.dirname(self.path))
        bad = {
            "keys": [{"enabled": "yes", "delay_ms": -5}, {"enabled": True, "delay_ms": 10**12},
                     {"enabled": True, "delay_ms": "abc"}, 5, None],
            "start_delay_s": 9999, "hold_ms": 0, "window": {"x": "a", "y": 1},
        }
        with open(self.path, "w") as fh:
            json.dump(bad, fh)
        s = cfg.load(self.path)
        self.assertFalse(s.keys[0].enabled)                      # "yes" is not a bool
        self.assertEqual(s.keys[0].delay_ms, cfg.DELAY_MIN)
        self.assertEqual(s.keys[1].delay_ms, cfg.DELAY_MAX)
        self.assertEqual(s.keys[2].delay_ms, cfg.DELAY_DEFAULT)
        self.assertEqual(len(s.keys), 10)
        self.assertEqual(s.start_delay_s, cfg.START_MAX)
        self.assertEqual(s.hold_ms, cfg.HOLD_MIN)
        self.assertIsNone(s.window_x)

    def test_clamp_int_edge_cases(self):
        self.assertEqual(cfg.clamp_int(float("inf"), 0, 10, 4), 4)
        self.assertEqual(cfg.clamp_int(True, 0, 10, 4), 4)
        self.assertEqual(cfg.clamp_int("7", 0, 10, 4), 7)


class SendInputLayoutTests(unittest.TestCase):
    """Verifies the ctypes structures match the Win32 ABI (can run on any OS)."""

    def test_input_struct_size_matches_windows(self):
        # Windows requires cbSize == sizeof(INPUT): 40 on x64, 28 on x86.
        self.assertEqual(ctypes.sizeof(ki.INPUT), ki.expected_input_size())

    def test_field_offsets_x64(self):
        if ctypes.sizeof(ctypes.c_size_t) != 8:
            self.skipTest("x64 layout only")
        self.assertEqual(ki.INPUT.type.offset, 0)
        self.assertEqual(ki.INPUT.ki.offset, 8)
        self.assertEqual(ki.KEYBDINPUT.wVk.offset, 0)
        self.assertEqual(ki.KEYBDINPUT.wScan.offset, 2)
        self.assertEqual(ki.KEYBDINPUT.dwFlags.offset, 4)
        self.assertEqual(ki.KEYBDINPUT.time.offset, 8)
        self.assertEqual(ki.KEYBDINPUT.dwExtraInfo.offset, 16)

    def test_scan_codes_f1_to_f10(self):
        self.assertEqual(ki.SCAN_CODES, (0x3B, 0x3C, 0x3D, 0x3E, 0x3F, 0x40, 0x41, 0x42, 0x43, 0x44))
        self.assertEqual(ki.F_KEY_NAMES[0], "F1")
        self.assertEqual(ki.F_KEY_NAMES[9], "F10")

    def test_key_down_and_up_events(self):
        for i, scan in enumerate(ki.SCAN_CODES):
            down = ki.build_key_event(i, key_up=False)
            up = ki.build_key_event(i, key_up=True)
            self.assertEqual(down.type, ki.INPUT_KEYBOARD)
            self.assertEqual(down.ki.wScan, scan)
            self.assertEqual(down.ki.wVk, 0)
            self.assertEqual(down.ki.dwFlags, ki.KEYEVENTF_SCANCODE)
            self.assertEqual(up.ki.dwFlags, ki.KEYEVENTF_SCANCODE | ki.KEYEVENTF_KEYUP)

    def test_rejects_bad_index(self):
        for bad in (-1, 10):
            with self.assertRaises(ValueError):
                ki.build_key_event(bad, False)

    def test_windows_backend_refuses_other_platforms(self):
        if ki.IS_WINDOWS:
            self.skipTest("running on Windows")
        with self.assertRaises(OSError):
            ki.WindowsKeyboard()


if __name__ == "__main__":
    unittest.main()
