"""A fake keyboard that records what the engine does (with timestamps)."""
import threading
import time

from fkeyautomator.engine import InputBackend


class MockBackend(InputBackend):
    def __init__(self):
        self.log = []                 # (monotonic_time, "down"|"up", index)
        self.down_now = set()
        self.lock = threading.Lock()
        self.foreground = "ok"
        self.modifiers = False
        self.fail_on_down = None      # exception instance to raise on next key_down
        self.timer_calls = []

    def key_down(self, index):
        if self.fail_on_down:
            exc, self.fail_on_down = self.fail_on_down, None
            raise exc
        with self.lock:
            self.log.append((time.monotonic(), "down", index))
            self.down_now.add(index)

    def key_up(self, index):
        with self.lock:
            self.log.append((time.monotonic(), "up", index))
            self.down_now.discard(index)

    def foreground_state(self):
        return self.foreground

    def modifiers_down(self):
        return self.modifiers

    def begin_timer(self):
        self.timer_calls.append("begin")

    def end_timer(self):
        self.timer_calls.append("end")

    # helpers
    def downs(self):
        with self.lock:
            return [(t, i) for t, kind, i in self.log if kind == "down"]

    def down_indexes(self):
        return [i for _, i in self.downs()]
