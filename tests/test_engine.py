import queue
import threading
import time
import unittest

from fkeyautomator.engine import KeyboardInputError, Runner, Step
from tests.mock_backend import MockBackend


def wait_until(predicate, timeout=3.0, interval=0.005):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(interval)
    return False


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.backend = MockBackend()
        self.events = queue.Queue()
        self.runner = Runner(self.backend, self.events.put)

    def tearDown(self):
        self.runner.stop()
        if self.runner._thread:
            self.runner._thread.join(2)

    def start(self, steps, hold=10, start_delay=0):
        holder = {"steps": tuple(steps)}
        self.holder = holder
        ok = self.runner.start(lambda: holder["steps"], lambda: hold, start_delay)
        self.assertTrue(ok)

    def drain(self):
        out = []
        while True:
            try:
                out.append(self.events.get_nowait())
            except queue.Empty:
                return out

    # ------------------------------------------------------------ behaviour
    def test_only_selected_keys_in_order_and_repeat(self):
        self.start([Step(0, 30), Step(2, 30), Step(9, 30)])
        self.assertTrue(wait_until(lambda: len(self.backend.downs()) >= 7))
        self.runner.stop()
        seq = self.backend.down_indexes()
        expected = [0, 2, 9] * 3
        self.assertEqual(seq[:len(expected)][:7], expected[:7])
        self.assertTrue(set(seq) <= {0, 2, 9}, "an unselected key was pressed")

    def test_each_key_uses_its_own_delay(self):
        self.start([Step(0, 120), Step(1, 40), Step(2, 200)], hold=10)
        self.assertTrue(wait_until(lambda: len(self.backend.downs()) >= 4))
        self.runner.stop()
        d = self.backend.downs()
        gap01 = d[1][0] - d[0][0]   # delay of F1 (+hold)
        gap12 = d[2][0] - d[1][0]   # delay of F2
        gap23 = d[3][0] - d[2][0]   # delay of F3
        self.assertAlmostEqual(gap01, 0.120, delta=0.045)
        self.assertAlmostEqual(gap12, 0.040, delta=0.045)
        self.assertAlmostEqual(gap23, 0.200, delta=0.045)
        self.assertGreater(gap01, gap12)
        self.assertGreater(gap23, gap01)

    def test_key_is_held_for_hold_time(self):
        self.start([Step(3, 100)], hold=80)
        self.assertTrue(wait_until(lambda: any(k == "up" for _, k, _ in self.backend.log)))
        self.runner.stop()
        down = next(t for t, k, i in self.backend.log if k == "down")
        up = next(t for t, k, i in self.backend.log if k == "up")
        self.assertAlmostEqual(up - down, 0.080, delta=0.03)

    def test_repeats_until_stopped(self):
        self.start([Step(0, 5), Step(1, 5)], hold=5)
        time.sleep(0.6)
        self.assertTrue(self.runner.is_running())
        self.assertGreater(len(self.backend.downs()), 20)
        self.runner.stop()
        self.assertTrue(wait_until(lambda: not self.runner.is_running()))

    def test_stop_during_hold_releases_immediately(self):
        self.start([Step(4, 100)], hold=5000)          # would hold for 5 s
        self.assertTrue(wait_until(lambda: 4 in self.backend.down_now))
        t0 = time.monotonic()
        self.runner.stop()
        self.assertEqual(self.backend.down_now, set(), "key left pressed after stop()")
        self.assertLess(time.monotonic() - t0, 0.05)
        self.assertTrue(wait_until(lambda: not self.runner.is_running(), 1.0))
        ups = [i for _, k, i in self.backend.log if k == "up"]
        self.assertEqual(ups.count(4), 1, "key must be released exactly once")

    def test_stop_during_long_delay_is_immediate(self):
        self.start([Step(0, 60_000)], hold=10)
        self.assertTrue(wait_until(lambda: len(self.backend.downs()) == 1))
        t0 = time.monotonic()
        self.runner.stop()
        self.assertTrue(wait_until(lambda: not self.runner.is_running(), 1.0))
        self.assertLess(time.monotonic() - t0, 0.25)

    def test_stop_during_countdown_presses_nothing(self):
        self.start([Step(0, 10)], start_delay=5)
        self.assertTrue(wait_until(lambda: any(e[0] == "countdown" for e in list(self.events.queue))))
        self.runner.stop()
        self.assertTrue(wait_until(lambda: not self.runner.is_running(), 1.0))
        self.assertEqual(self.backend.downs(), [])

    def test_countdown_events_then_running(self):
        self.start([Step(0, 10)], start_delay=2)
        self.assertTrue(wait_until(lambda: len(self.backend.downs()) >= 1, 4.0))
        self.runner.stop()
        kinds = [e[0] for e in self.drain()]
        self.assertEqual(kinds[:3], ["countdown", "countdown", "running"])

    def test_no_keys_stops_with_reason(self):
        self.start([])
        self.assertTrue(wait_until(lambda: not self.runner.is_running(), 1.0))
        stopped = [e for e in self.drain() if e[0] == "stopped"][0]
        self.assertEqual(stopped[1], "no_keys")

    def test_live_edit_is_picked_up_next_cycle(self):
        self.start([Step(0, 20)])
        self.assertTrue(wait_until(lambda: len(self.backend.downs()) >= 2))
        self.holder["steps"] = (Step(5, 20),)
        self.assertTrue(wait_until(lambda: 5 in self.backend.down_indexes()))

    def test_unchecking_everything_while_running_stops(self):
        self.start([Step(0, 20)])
        self.assertTrue(wait_until(lambda: len(self.backend.downs()) >= 1))
        self.holder["steps"] = ()
        self.assertTrue(wait_until(lambda: not self.runner.is_running(), 1.0))

    def test_waits_while_own_window_is_active(self):
        self.backend.foreground = "self"
        self.start([Step(0, 10)])
        time.sleep(0.4)
        self.assertEqual(self.backend.downs(), [], "typed into our own window")
        self.backend.foreground = "ok"
        self.assertTrue(wait_until(lambda: len(self.backend.downs()) >= 1, 1.0))
        targets = [e[1] for e in self.drain() if e[0] == "target"]
        self.assertEqual(targets, ["self", "ok"])

    def test_blocked_target_warns_but_still_sends(self):
        self.backend.foreground = "blocked"
        self.start([Step(0, 10)])
        self.assertTrue(wait_until(lambda: len(self.backend.downs()) >= 1, 1.0))
        self.assertIn(("target", "blocked"), self.drain())

    def test_waits_for_modifier_keys_to_be_released(self):
        self.backend.modifiers = True            # user still holds Ctrl+Alt
        self.start([Step(0, 10)])
        time.sleep(0.3)
        self.assertEqual(self.backend.downs(), [])
        self.backend.modifiers = False
        self.assertTrue(wait_until(lambda: len(self.backend.downs()) >= 1, 1.0))

    def test_backend_error_is_reported_and_everything_released(self):
        self.backend.fail_on_down = KeyboardInputError("boom")
        self.start([Step(0, 10)])
        self.assertTrue(wait_until(lambda: not self.runner.is_running(), 1.0))
        events = self.drain()
        self.assertIn(("error", "boom"), events)
        self.assertEqual([e for e in events if e[0] == "stopped"][0][1], "error")
        self.assertEqual(self.backend.down_now, set())

    def test_cannot_start_twice_but_can_restart_after_stop(self):
        self.start([Step(0, 50)])
        self.assertFalse(self.runner.start(lambda: (Step(0, 1),), lambda: 5, 0))
        self.runner.stop()
        self.assertTrue(self.runner.start(lambda: (Step(1, 20),), lambda: 5, 0))
        self.assertTrue(wait_until(lambda: 1 in self.backend.down_indexes(), 1.0))

    def test_stop_from_other_thread_while_hammering(self):
        """Stress: many start/stop cycles never leave a key stuck down."""
        for _ in range(25):
            self.assertTrue(self.runner.start(lambda: (Step(0, 0), Step(1, 0)), lambda: 30, 0))
            time.sleep(0.01)
            t = threading.Thread(target=self.runner.stop)
            t.start()
            t.join()
            self.assertTrue(wait_until(lambda: not self.runner.is_running(), 1.0))
            self.assertEqual(self.backend.down_now, set())

    def test_high_resolution_timer_is_bracketed(self):
        self.start([Step(0, 10)])
        self.assertTrue(wait_until(lambda: len(self.backend.downs()) >= 1))
        self.runner.stop()
        self.assertTrue(wait_until(lambda: self.backend.timer_calls == ["begin", "end"], 1.0))


if __name__ == "__main__":
    unittest.main()
