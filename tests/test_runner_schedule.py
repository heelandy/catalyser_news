import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import macro_pipeline_runner as runner


class StopAtTests(unittest.TestCase):
    def test_parse_stop_at_empty_disables(self):
        self.assertIsNone(runner.parse_stop_at(""))
        self.assertIsNone(runner.parse_stop_at("  "))

    def test_parse_stop_at_valid(self):
        self.assertEqual(runner.parse_stop_at("18:00"), (18, 0))
        self.assertEqual(runner.parse_stop_at("07:30"), (7, 30))

    def test_parse_stop_at_invalid(self):
        for value in ["banana", "25:00", "18:75", "18", "18:00:00"]:
            with self.assertRaises(SystemExit):
                runner.parse_stop_at(value)

    def test_past_stop_time(self):
        self.assertFalse(runner.past_stop_time(None))
        self.assertTrue(runner.past_stop_time((0, 0)))
        self.assertFalse(runner.past_stop_time((23, 59)))


class StageOrderTests(unittest.TestCase):
    def make_args(self):
        argv = sys.argv
        sys.argv = ["macro_pipeline_runner.py"]
        try:
            return runner.normalize_args(runner.parse_args())
        finally:
            sys.argv = argv

    def test_news_feed_runs_first(self):
        args = self.make_args()
        stages = [stage.name for stage in runner.build_stages(args)]
        self.assertIn("news_feed", stages)
        self.assertEqual(stages.index("news_feed"), 0)
        self.assertLess(stages.index("news_feed"), stages.index("live_calendar_fetch"))
        self.assertLess(stages.index("live_calendar_fetch"), stages.index("live_regime_context"))

    def test_news_refresh_defaults(self):
        args = self.make_args()
        self.assertEqual(args.news_feed_cache_minutes, 3)
        self.assertEqual(args.news_feed_refresh_seconds, 180)


if __name__ == "__main__":
    unittest.main()
