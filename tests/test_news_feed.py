import argparse
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

import macro_news_feed as news


class NewsFeedTests(unittest.TestCase):
    def test_tradingview_url_normalizes_future_market(self):
        url = news.normalize_tradingview_url("https://www.tradingview.com/news-flow/?market=stock,etf,future")
        self.assertEqual(url, "https://www.tradingview.com/news-flow/?market=stock,etf,futures")

    def test_hot_jobs_hawkish_fed_and_chip_selloff_is_bearish_for_nq(self):
        row = {
            "provider": "test",
            "source": "CNBC/Yahoo",
            "title": "Nonfarm payrolls jumped way higher than expected as higher inflation fueled Fed rate hike bets",
            "summary": (
                "Chip stocks were hammered, with the semiconductor sector suffering its steepest decline. "
                "The slump erased more than $1 trillion as investors unwind positions tied to the AI boom."
            ),
            "url": "",
            "published_at": datetime(2026, 6, 5, tzinfo=timezone.utc),
        }
        interpreted = news.interpret(row)
        self.assertEqual(interpreted["direction"], "bearish")
        self.assertGreaterEqual(interpreted["confidence"], 0.70)
        self.assertIn("labor", interpreted["themes"])
        self.assertIn("rates", interpreted["themes"])
        self.assertIn("chips_ai", interpreted["themes"])
        self.assertIn("macro_policy_pressure", interpreted["risk_flags"])
        self.assertIn("nq_growth_pressure", interpreted["risk_flags"])

    def test_listicle_content_is_heavily_discounted(self):
        row = {
            "provider": "yahoo",
            "source": "Motley Fool",
            "title": "3 Beaten-Down AI Chip Stocks Worth a Closer Look After the Sell-Off",
            "summary": "Here are three reasons the sell-off could be a buying opportunity.",
            "url": "",
            "published_at": datetime(2026, 6, 11, tzinfo=timezone.utc),
        }
        interpreted = news.interpret(row)
        self.assertIn("low_signal_content", interpreted["risk_flags"])
        self.assertLessEqual(interpreted["confidence"], 0.10)

    def test_strong_source_keeps_more_confidence_than_weak_source(self):
        base = {
            "provider": "yahoo",
            "title": "Chip stocks slump as the semiconductor sell-off deepens",
            "summary": "",
            "url": "",
            "published_at": datetime(2026, 6, 11, tzinfo=timezone.utc),
        }
        strong = news.interpret({**base, "source": "Reuters"})
        weak = news.interpret({**base, "source": "Insider Monkey"})
        self.assertGreater(strong["confidence"], weak["confidence"])

    def test_news_bias_decays_old_headlines(self):
        def row(published, title):
            return news.interpret({
                "provider": "yahoo",
                "source": "Reuters",
                "title": title,
                "summary": "",
                "url": "",
                "published_at": published,
            })

        now = datetime(2026, 6, 11, 12, 0, tzinfo=timezone.utc)
        fresh_bull = row(now, "Stocks rally as futures rise on strong earnings beat")
        stale_bear = row(datetime(2026, 6, 11, 0, 0, tzinfo=timezone.utc), "Market selloff deepens as futures fall and stocks slump")
        fresh_bear = row(now, "Market selloff deepens as futures fall and stocks slump")

        decayed = news.news_bias([fresh_bull, stale_bear], now)
        undecayed = news.news_bias([fresh_bull, fresh_bear], now)

        # the 12-hour-old bearish headline should weigh far less than a fresh one
        self.assertGreater(decayed["score"], undecayed["score"])
        self.assertGreater(decayed["score"], 0)

    def test_same_story_under_two_symbols_dedupes_by_title(self):
        a = {"title": "Dow Jones Futures Fall On Iran News!", "url": "https://a.test/1"}
        b = {"title": "Dow Jones Futures Fall on Iran news", "url": "https://b.test/2"}
        self.assertEqual(news.article_key(a), news.article_key(b))

    def test_auto_provider_falls_back_to_yahoo_rss(self):
        args = argparse.Namespace(
            provider="auto",
            symbols="NQ=F",
            max_per_symbol=2,
            max_items=5,
            timeout=3,
            tradingview_news_url=news.TRADINGVIEW_NEWS_FLOW_URL,
        )
        rss_row = {
            "provider": "yahoo_rss",
            "source": "Yahoo Finance RSS",
            "symbol": "NQ=F",
            "symbols": "NQ",
            "title": "Nasdaq futures fall as yields rise",
            "summary": "",
            "url": "https://example.test/news",
            "published_at": datetime(2026, 6, 10, tzinfo=timezone.utc),
        }
        with patch.object(news, "fetch_yahoo_symbol", return_value=[]), patch.object(news, "fetch_yahoo_rss_symbol", return_value=[rss_row]), patch.object(news, "fetch_tradingview") as tv_fetch:
            rows, errors, attempts, source_used = news.fetch_rows(args)

        self.assertEqual(source_used, "yahoo_rss")
        self.assertEqual(rows, [rss_row])
        self.assertEqual(errors, [])
        self.assertEqual([attempt["provider"] for attempt in attempts], ["yahoo", "yahoo_rss"])
        tv_fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
