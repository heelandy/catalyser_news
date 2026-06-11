import csv
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import macro_pipeline_runner as runner


def write_releases(path: Path, release_times: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["release_time", "title"])
        writer.writeheader()
        for value in release_times:
            writer.writerow({"release_time": value, "title": "Test Event"})


class ReleaseWindowTests(unittest.TestCase):
    """release_time values are UTC timestamps without a timezone suffix.

    The fast news window must compare them against UTC now, not local time.
    A bug here would make the fast refresh fire 4-5 hours off for ET users.
    """

    def utc_naive(self, delta_minutes: float) -> str:
        moment = datetime.now(timezone.utc) + timedelta(minutes=delta_minutes)
        return moment.replace(tzinfo=None).isoformat(timespec="seconds")

    def check(self, release_times: list[str], window: float) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "releases.csv"
            write_releases(path, release_times)
            return runner.release_within_minutes(str(path), window)

    def test_release_five_minutes_ahead_is_inside_window(self):
        self.assertTrue(self.check([self.utc_naive(5)], 15))

    def test_release_five_minutes_ago_is_inside_window(self):
        self.assertTrue(self.check([self.utc_naive(-5)], 15))

    def test_release_two_hours_away_is_outside_window(self):
        # 120 minutes is also smaller than the ET/UTC offset (240/300 min),
        # so this fails if naive UTC values were compared against local time.
        self.assertFalse(self.check([self.utc_naive(120)], 15))

    def test_release_four_hours_away_is_outside_window(self):
        # Exactly the EDT offset: a local-time comparison bug would wrongly
        # report this as "now".
        self.assertFalse(self.check([self.utc_naive(240)], 15))

    def test_timezone_suffixed_values_are_normalized(self):
        suffixed = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(timespec="seconds")
        self.assertTrue(self.check([suffixed.replace("+00:00", "Z")], 15))

    def test_missing_file_and_bad_rows_are_safe(self):
        self.assertFalse(runner.release_within_minutes("does_not_exist.csv", 15))
        self.assertFalse(self.check(["not-a-date", ""], 15))


class RunnerLockTests(unittest.TestCase):
    def test_lock_blocks_second_runner_and_clears_stale(self):
        import os

        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "runner.lock"

            self.assertTrue(runner.acquire_runner_lock(lock, None))
            self.assertEqual(lock.read_text(encoding="utf-8").strip(), str(os.getpid()))

            # same PID re-acquires (not a duplicate runner)
            self.assertTrue(runner.acquire_runner_lock(lock, None))

            # a stale lock from a dead PID is replaced
            lock.write_text("999999999\n", encoding="utf-8")
            self.assertTrue(runner.acquire_runner_lock(lock, None))

            runner.release_runner_lock(lock)
            self.assertFalse(lock.exists())


class LogRotationTests(unittest.TestCase):
    def test_log_rotates_past_limit_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "runner.log"
            log.write_text("x" * 2048, encoding="utf-8")

            runner.rotate_log_if_needed(log, 0.001)  # ~1 KB limit
            backup = Path(tmp) / "runner.log.1"
            self.assertTrue(backup.exists())
            self.assertFalse(log.exists())

            # under the limit nothing happens
            log.write_text("small", encoding="utf-8")
            runner.rotate_log_if_needed(log, 10)
            self.assertTrue(log.exists())


if __name__ == "__main__":
    unittest.main()
