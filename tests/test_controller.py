import os
import tempfile
import time
import unittest

from fkeyautomator import settings as cfg
from fkeyautomator.controller import Controller
from fkeyautomator.macro_runtime import MacroPlayer
from fkeyautomator.macros import MacroEvent
from tests.mock_backend import MockBackend


def wait_until(predicate, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(0.005)
    return False


class FakeHotkey:
    def __init__(self, on_pressed, on_status):
        self.on_pressed, self.on_status = on_pressed, on_status
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


class FakeMacroHotkey(FakeHotkey):
    def __init__(self, on_pressed, on_status, hotkey, hotkey_id):
        super().__init__(on_pressed, on_status)
        self.hotkey, self.hotkey_id = hotkey, hotkey_id

    def set_hotkey(self, hotkey):
        self.hotkey = hotkey


class FakeRecorder:
    def __init__(self):
        self.recording = False
        self.events = []

    def start(self):
        self.recording = True

    def stop(self):
        self.recording = False
        return list(self.events)


class FakeMacroIO:
    def __init__(self):
        self.down = set()

    def send(self, event):
        if event.action == "down":
            self.down.add(event.identity)
        else:
            self.down.discard(event.identity)

    def foreground_state(self):
        return "ok"

    def begin_timer(self):
        pass

    def end_timer(self):
        pass


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "settings.json")
        self.backend = MockBackend()
        self.c = self.make()

    def make(self, **kw):
        return Controller(self.backend, config_path=self.path, hotkey_factory=FakeHotkey, **kw)

    def tearDown(self):
        self.c.runner.stop()

    def pump(self, until, timeout=3.0):
        return wait_until(lambda: (self.c.tick(), until())[1], timeout)

    def test_start_without_keys_shows_message(self):
        self.assertFalse(self.c.start())
        self.assertEqual(self.c.state.message_key, "no_keys")
        self.assertFalse(self.c.state.running)

    def test_full_run_executes_only_checked_keys_with_own_delays(self):
        self.c.set_start_delay(0)
        self.c.set_hold(10)
        self.c.set_enabled(1, True);  self.c.set_delay(1, 30)
        self.c.set_enabled(4, True);  self.c.set_delay(4, 60)
        self.c.set_enabled(7, False)
        self.assertTrue(self.c.start())
        self.assertTrue(self.c.state.running)
        self.assertTrue(self.pump(lambda: self.c.state.cycles >= 2))
        self.c.stop()
        self.assertTrue(self.pump(lambda: not self.c.state.running))
        self.assertEqual(self.c.state.phase, "stopped")
        self.assertEqual(set(self.backend.down_indexes()), {1, 4})
        self.assertEqual(self.backend.down_indexes()[:4], [1, 4, 1, 4])
        self.assertEqual(self.backend.down_now, set())
        self.assertGreaterEqual(self.c.state.presses, 4)

    def test_key_flash_state_appears_then_clears(self):
        self.c.set_start_delay(0); self.c.set_hold(10)
        self.c.set_enabled(2, True); self.c.set_delay(2, 600)
        self.c.start()
        self.assertTrue(self.pump(lambda: self.c.state.active_key == 2))
        self.assertTrue(self.pump(lambda: self.c.state.active_key is None, 1.5))
        self.c.stop()

    def test_start_runs_immediately_without_countdown(self):
        self.c.set_start_delay(2); self.c.set_enabled(0, True)
        self.c.start()
        self.assertEqual(self.c.state.phase, "running")
        self.assertEqual(self.c.state.countdown, 0)
        time.sleep(0.02)
        self.assertNotIn("countdown", [event[0] for event in list(self.c.events.queue)])
        self.c.stop()

    def test_own_window_focus_message_then_clears(self):
        self.backend.foreground = "self"
        self.c.set_start_delay(0); self.c.set_hold(10); self.c.set_enabled(0, True)
        self.c.start()
        self.assertTrue(self.pump(lambda: self.c.state.phase == "waiting"))
        self.assertEqual(self.c.state.message_key, "self_focus")
        self.backend.foreground = "ok"
        self.assertTrue(self.pump(lambda: self.c.state.phase == "running"))
        self.assertEqual(self.c.state.message_key, "")
        self.c.stop()

    def test_blocked_target_message(self):
        self.backend.foreground = "blocked"
        self.c.set_start_delay(0); self.c.set_enabled(0, True)
        self.c.start()
        self.assertTrue(self.pump(lambda: self.c.state.message_key == "blocked"))
        self.c.stop()

    def test_unchecking_last_key_while_running_stops_with_message(self):
        self.c.set_start_delay(0); self.c.set_hold(10)
        self.c.set_enabled(0, True); self.c.set_delay(0, 20)
        self.c.start()
        self.assertTrue(self.pump(lambda: self.c.state.presses >= 1))
        self.c.set_enabled(0, False)
        self.assertTrue(self.pump(lambda: not self.c.state.running))
        self.assertEqual(self.c.state.message_key, "all_disabled")

    def test_hotkey_toggles_start_and_stop(self):
        self.c.set_start_delay(0); self.c.set_hold(10); self.c.set_enabled(3, True); self.c.set_delay(3, 20)
        self.c.hotkey.on_pressed()                         # as if Ctrl+Alt+S was pressed (other thread)
        self.assertTrue(self.pump(lambda: self.c.state.running and self.c.state.presses >= 1))
        self.c.hotkey.on_pressed()                         # second press stops immediately
        self.assertFalse(self.c.runner._thread.is_alive() and not self.c.runner._stop.is_set())
        self.assertTrue(self.pump(lambda: not self.c.state.running))
        self.assertEqual(self.backend.down_now, set())

    def test_hotkey_registration_failure_is_reported(self):
        self.c.hotkey.on_status(False)
        self.c.tick()
        self.assertIs(self.c.state.hotkey_ok, False)
        self.assertEqual(self.c.state.message_key, "hotkey_fail")

    def test_settings_saved_debounced_and_restored(self):
        t = [100.0]
        c = Controller(self.backend, config_path=self.path, clock=lambda: t[0])
        c.set_enabled(5, True); c.set_delay(5, 777); c.set_hold(55); c.set_start_delay(4)
        c.tick()
        self.assertFalse(os.path.exists(self.path))        # not yet: debounce
        t[0] += 1.0
        c.tick()
        self.assertTrue(os.path.exists(self.path))
        again = Controller(self.backend, config_path=self.path)
        self.assertEqual(again.settings.keys[5].delay_ms, 777)
        self.assertTrue(again.settings.keys[5].enabled)
        self.assertEqual((again.settings.hold_ms, again.settings.start_delay_s), (55, 4))
        self.assertEqual([s.index for s in again.get_steps()], [5])

    def test_close_saves_and_stops_everything(self):
        self.c.set_start_delay(0); self.c.set_enabled(0, True); self.c.set_delay(0, 30)
        self.c.start()
        self.assertTrue(self.pump(lambda: self.c.state.presses >= 1))
        self.c.close()
        self.assertTrue(os.path.exists(self.path))
        self.assertTrue(self.c.hotkey.stopped)
        self.assertTrue(wait_until(lambda: not self.c.runner.is_running(), 1.0))
        self.assertEqual(self.backend.down_now, set())

    def test_values_are_clamped(self):
        self.c.set_delay(0, 10**12); self.c.set_hold(0); self.c.set_start_delay(-3)
        self.assertEqual(self.c.settings.keys[0].delay_ms, cfg.DELAY_MAX)
        self.assertEqual(self.c.settings.hold_ms, cfg.HOLD_MIN)
        self.assertEqual(self.c.settings.start_delay_s, cfg.START_MIN)

    def test_relaunch_as_admin_paths(self):
        calls = []
        ok = self.make(relaunch=lambda: calls.append(1) or True)
        self.assertTrue(ok.relaunch_as_admin())
        no = self.make(relaunch=lambda: False)
        self.assertFalse(no.relaunch_as_admin())
        self.assertEqual(no.state.message_key, "relaunch_fail")
        self.assertEqual(calls, [1])

    def test_engine_error_surfaces_in_state(self):
        from fkeyautomator.engine import KeyboardInputError
        self.backend.fail_on_down = KeyboardInputError("SendInput failed (error 5)")
        self.c.set_start_delay(0); self.c.set_enabled(0, True)
        self.c.start()
        self.assertTrue(self.pump(lambda: self.c.state.phase == "error"))
        self.assertEqual(self.c.state.message_key, "error")
        self.assertIn("error 5", self.c.state.message_detail)

    def test_macro_record_save_restore_and_mutual_exclusion(self):
        recorder = FakeRecorder()
        c = Controller(self.backend, config_path=self.path, macro_recorder=recorder)
        try:
            macro = c.create_macro("combo")
            self.assertTrue(c.start_recording(macro.id))
            self.assertFalse(c.start())
            recorder.events = [MacroEvent("key", "key", "down", 0, 0x1E, 0x41)]
            self.assertTrue(c.stop_recording())
            self.assertEqual(c.get_macro(macro.id).events[0].virtual_key, 0x41)
            restored = Controller(self.backend, config_path=self.path)
            self.assertEqual(restored.macro_store.macros[0].name, "combo")
            self.assertEqual(restored.macro_store.macros[0].events[0].action, "down")
            c.update_macro(macro.id, repeat_count=12, repeat_forever=True)
            restored = Controller(self.backend, config_path=self.path)
            self.assertEqual((restored.macro_store.macros[0].repeat_count,
                              restored.macro_store.macros[0].repeat_forever), (12, True))
            self.assertEqual(c.state.message_key, "automation_busy")
        finally:
            c.close()

    def test_macro_playback_blocks_existing_runner_and_stops_safely(self):
        io = FakeMacroIO()
        c = Controller(self.backend, config_path=self.path, macro_backend=io)
        try:
            macro = c.create_macro("long")
            c.update_macro(macro.id, events=[
                MacroEvent("key", "key", "down", 0, 0x1E, 0x41),
                MacroEvent("key", "key", "up", 60_000, 0x1E, 0x41),
            ])
            self.assertTrue(c.play_macro(macro.id, loop=True))
            self.assertFalse(c.start())
            self.assertTrue(wait_until(lambda: bool(io.down)))
            c.stop_macro()
            self.assertTrue(wait_until(lambda: not c.macro_player.running))
            self.assertEqual(io.down, set())
            self.assertTrue(wait_until(lambda: (c.tick(), not c.state.macro_playing)[1]))
        finally:
            c.close()

    def test_macro_hotkey_is_independent_and_user_changeable(self):
        c = Controller(
            self.backend, config_path=self.path,
            macro_hotkey_factory=FakeMacroHotkey,
        )
        try:
            self.assertEqual(c.macro_hotkey.hotkey, "Ctrl+Shift+F12")
            self.assertEqual(c.macro_hotkey.hotkey_id, 0x4B42)
            self.assertEqual(c.set_macro_hotkey("ctrl+alt+m"), "Ctrl+Alt+M")
            self.assertEqual(c.macro_hotkey.hotkey, "Ctrl+Alt+M")
            c.macro_hotkey.on_status(False)
            c.tick()
            self.assertFalse(c.state.macro_hotkey_ok)
        finally:
            c.close()


if __name__ == "__main__":
    unittest.main()
