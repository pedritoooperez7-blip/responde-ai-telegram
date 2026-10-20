"""Offline tests for the in-process rate limiters (no web framework required)."""
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import limits


class FakeClock:
    def __init__(self, start=1000.0):
        self.value = start

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class SlidingWindowLimiterTests(unittest.TestCase):
    def test_allows_up_to_the_limit_then_reports_retry_after(self):
        clock = FakeClock()
        limiter = limits.SlidingWindowLimiter(3, 60, clock=clock)
        for _ in range(3):
            allowed, retry = limiter.check("u1")
            self.assertTrue(allowed)
            self.assertEqual(retry, 0.0)
        allowed, retry = limiter.check("u1")
        self.assertFalse(allowed)
        self.assertGreater(retry, 0)
        self.assertLessEqual(retry, 60)

    def test_window_expiry_restores_capacity(self):
        clock = FakeClock()
        limiter = limits.SlidingWindowLimiter(2, 10, clock=clock)
        self.assertTrue(limiter.check("u1")[0])
        self.assertTrue(limiter.check("u1")[0])
        self.assertFalse(limiter.check("u1")[0])
        clock.advance(10.1)
        self.assertTrue(limiter.check("u1")[0])

    def test_keys_are_independent_and_reset_clears_one(self):
        clock = FakeClock()
        limiter = limits.SlidingWindowLimiter(1, 60, clock=clock)
        self.assertTrue(limiter.check("a")[0])
        self.assertTrue(limiter.check("b")[0])
        self.assertFalse(limiter.check("a")[0])
        limiter.reset("a")
        self.assertTrue(limiter.check("a")[0])

    def test_concurrent_checks_never_exceed_the_limit(self):
        limiter = limits.SlidingWindowLimiter(5, 60)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: limiter.check("shared")[0], range(40)))
        self.assertEqual(sum(1 for allowed in results if allowed), 5)

    def test_invalid_limits_are_normalised(self):
        limiter = limits.SlidingWindowLimiter(0, 0)
        self.assertEqual(limiter.max_events, 1)
        self.assertGreater(limiter.window_seconds, 0)


class DailyCounterTests(unittest.TestCase):
    def test_take_respects_limit_and_reports_remaining(self):
        counter = limits.DailyCounter(2)
        self.assertEqual(counter.remaining("u"), 2)
        self.assertTrue(counter.take("u"))
        self.assertTrue(counter.take("u"))
        self.assertFalse(counter.take("u"))
        self.assertEqual(counter.remaining("u"), 0)

    def test_counter_resets_on_a_new_utc_day(self):
        clock = FakeClock(start=1600000000.0)  # 2020-09-13T12:26:40Z
        counter = limits.DailyCounter(1, clock=clock)
        self.assertTrue(counter.take("u"))
        self.assertFalse(counter.take("u"))
        clock.advance(86400)
        self.assertTrue(counter.take("u"))

    def test_users_are_independent(self):
        counter = limits.DailyCounter(1)
        self.assertTrue(counter.take("a"))
        self.assertTrue(counter.take("b"))


class ConcurrencyGateTests(unittest.TestCase):
    def test_single_slot_gate_denies_when_busy(self):
        gate = limits.ConcurrencyGate(1)
        self.assertTrue(gate.acquire(timeout=0))
        self.assertFalse(gate.acquire(timeout=0))
        gate.release()
        self.assertTrue(gate.acquire(timeout=0))
        gate.release()

    def test_gate_allows_all_slots(self):
        gate = limits.ConcurrencyGate(2)
        self.assertTrue(gate.acquire(0))
        self.assertTrue(gate.acquire(0))
        self.assertFalse(gate.acquire(0))
        gate.release()
        gate.release()

    def test_gate_is_safe_under_concurrency(self):
        gate = limits.ConcurrencyGate(3)
        active = 0
        peak = 0
        lock = threading.Lock()

        def worker():
            nonlocal active, peak
            if not gate.acquire(0.5):
                return
            try:
                with lock:
                    active += 1
                    peak = max(peak, active)
                threading.Event().wait(0.01)
            finally:
                with lock:
                    active -= 1
                gate.release()

        with ThreadPoolExecutor(max_workers=9) as pool:
            list(pool.map(lambda _: worker(), range(18)))
        self.assertLessEqual(peak, 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
