import os
import tempfile
import threading
import time
import unittest

from fkeyautomator.hotkey import parse_hotkey
from fkeyautomator.macro_runtime import GlobalRecorder, MacroPlayer
from fkeyautomator.macros import Macro, MacroEvent, MacroStore


def wait_until(predicate, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.002)
    return False


class FakeMacroIO:
    def __init__(self):
        self.log = []
        self.down = set()
        self.lock = threading.Lock()
        self.timer = []

    def send(self, event):
        with self.lock:
            self.log.append((event.device, event.code, event.action))
            if event.action == "down":
                self.down.add(event.identity)
            else:
                self.down.discard(event.identity)

    def foreground_state(self):
        return "ok"

    def begin_timer(self):
        self.timer.append("begin")

    def end_timer(self):
        self.timer.append("end")


class MacroTests(unittest.TestCase):
    def test_roundtrip_and_import_export(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "macros.json")
            macro = Macro("first", "Build", [
                MacroEvent("key", "key", "down", 0, 0x1E, 0x41),
                MacroEvent("key", "key", "up", 54, 0x1E, 0x41),
                MacroEvent("mouse", "left", "down", 12),
                MacroEvent("mouse", "left", "up", 30),
            ], "fixed", 75)
            store = MacroStore(path)
            store.macros = [macro]
            store.hotkey = "Ctrl+Shift+F12"
            self.assertTrue(store.save())
            loaded = MacroStore(path)
            self.assertEqual(loaded.hotkey, "Ctrl+Shift+F12")
            self.assertEqual(loaded.macros[0].to_dict(), macro.to_dict())
            exported = os.path.join(folder, "build.json")
            loaded.export_macro(loaded.macros[0], exported)
            imported = loaded.import_macro(exported)
            self.assertEqual(imported.events[1].delay_ms, 54)
            self.assertNotEqual(imported.id, loaded.macros[0].id)

    def test_pointer_event_and_repeat_settings_roundtrip_and_legacy_defaults(self):
        macro = Macro(
            "pointer", "Pointer", [MacroEvent("mouse", "move", "move", 12, x=-120, y=48)],
            repeat_count=7, repeat_forever=True,
        )
        restored = Macro.from_dict(macro.to_dict())
        self.assertEqual((restored.events[0].x, restored.events[0].y), (-120, 48))
        self.assertEqual((restored.repeat_count, restored.repeat_forever), (7, True))
        legacy = Macro.from_dict({"id": "old", "name": "Old", "events": []})
        self.assertEqual((legacy.repeat_count, legacy.repeat_forever), (1, False))
        with self.assertRaises(ValueError):
            MacroEvent("mouse", "move", "move", x="bad", y=2)

    def test_rejects_invalid_macro_event_and_hotkey(self):
        with self.assertRaises(ValueError):
            MacroEvent("mouse", "wheel", "down")
        with self.assertRaises(ValueError):
            Macro.from_dict({"id": "bad", "events": [{"device": "bad"}]})
        with self.assertRaises(ValueError):
            parse_hotkey("F12")
        flags, vk, label = parse_hotkey("ctrl+shift+f11")
        self.assertEqual((flags, vk, label), (0x0006, 0x7A, "Ctrl + Shift + F11"))

    def test_record_events_coalesces_key_repeat_and_synthesizes_release(self):
        recorder = GlobalRecorder(own_pid=1)
        recorder._record(MacroEvent("key", "key", "down", scan_code=0x1E, virtual_key=0x41))
        recorder._record(MacroEvent("key", "key", "down", scan_code=0x1E, virtual_key=0x41))
        recorder._record_pointer(40, 50)
        recorder._record(MacroEvent("mouse", "left", "down"))
        events = recorder.stop()
        self.assertEqual([(e.device, e.code, e.action) for e in events], [
            ("key", "key", "down"), ("mouse", "move", "move"),
            ("mouse", "left", "down"), ("key", "key", "up"),
            ("mouse", "left", "up"),
        ])

    def test_pointer_sampling_keeps_interval_points_and_final_position(self):
        recorder = GlobalRecorder(own_pid=1)
        recorder._record_pointer(10, 20, now=1.0)
        recorder._record_pointer(11, 21, now=1.004)  # pending within sample interval
        recorder._record_pointer(12, 22, now=1.012)  # next sample keeps latest point
        recorder._record_pointer(13, 23, now=1.015)  # final pending point
        events = recorder.stop()
        self.assertEqual([(e.x, e.y) for e in events], [(10, 20), (12, 22), (13, 23)])
        self.assertEqual([e.delay_ms for e in events], [0, 12, 3])

    def test_playback_order_once_and_releases_held_inputs(self):
        io = FakeMacroIO()
        player = MacroPlayer(io)
        macro = Macro("once", "once", [
            MacroEvent("key", "key", "down", 5000, 0x1E, 0x41),
            MacroEvent("key", "key", "up", 0, 0x1E, 0x41),
            MacroEvent("mouse", "right", "down", 0),
        ])
        self.assertTrue(player.start(macro))
        self.assertTrue(wait_until(lambda: not player.running))
        self.assertEqual(io.log, [
            ("key", "key", "down"), ("key", "key", "up"),
            ("mouse", "right", "down"), ("mouse", "right", "up"),
        ])
        self.assertEqual(io.down, set())
        self.assertEqual(io.timer, ["begin", "end"])

    def test_stop_during_delay_is_immediate_and_loop_repeats(self):
        io = FakeMacroIO()
        player = MacroPlayer(io)
        macro = Macro("loop", "loop", [
            MacroEvent("key", "key", "down", 0, 0x1E, 0x41),
            MacroEvent("key", "key", "up", 60_000, 0x1E, 0x41),
        ])
        self.assertTrue(player.start(macro, loop=True))
        self.assertTrue(wait_until(lambda: len(io.log) == 1))
        t0 = time.monotonic()
        player.stop()
        self.assertEqual(io.down, set())
        self.assertLess(time.monotonic() - t0, 0.05)
        self.assertTrue(wait_until(lambda: not player.running))
        self.assertEqual(io.log[-1], ("key", "key", "up"))

    def test_fixed_timing_replaces_gaps_and_repeat_runs(self):
        io = FakeMacroIO()
        player = MacroPlayer(io)
        macro = Macro("repeat", "repeat", [
            MacroEvent("key", "key", "down", 0, 0x1E, 0x41),
            MacroEvent("key", "key", "up", 100_000, 0x1E, 0x41),
        ], "fixed", 4)
        self.assertTrue(player.start(macro, loop=True))
        self.assertTrue(wait_until(lambda: len(io.log) >= 8))
        player.stop()
        self.assertTrue(wait_until(lambda: not player.running))
        self.assertGreaterEqual(len(io.log), 8)
        self.assertEqual(io.down, set())

    def test_finite_repeat_count_runs_exactly_the_configured_number(self):
        io = FakeMacroIO()
        player = MacroPlayer(io)
        macro = Macro("finite", "finite", [
            MacroEvent("key", "key", "down", 0, 0x1E, 0x41),
            MacroEvent("key", "key", "up", 0, 0x1E, 0x41),
        ], repeat_count=4)
        self.assertTrue(player.start(macro))
        self.assertTrue(wait_until(lambda: not player.running))
        self.assertEqual(io.log, [("key", "key", action) for _ in range(4) for action in ("down", "up")])
        self.assertEqual(io.down, set())

    def test_repeat_forever_from_macro_settings_stops_and_releases(self):
        io = FakeMacroIO()
        player = MacroPlayer(io)
        macro = Macro("forever", "forever", [
            MacroEvent("key", "key", "down", 0, 0x1E, 0x41),
            MacroEvent("key", "key", "up", 2, 0x1E, 0x41),
        ], repeat_forever=True)
        self.assertTrue(player.start(macro))
        self.assertTrue(wait_until(lambda: len(io.log) >= 8))
        player.stop()
        self.assertTrue(wait_until(lambda: not player.running))
        self.assertEqual(io.down, set())


if __name__ == "__main__":
    unittest.main()
