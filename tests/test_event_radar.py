import sqlite3
import unittest
from datetime import date

import pandas as pd

from event_radar.email_alert import dedupe_alerts_for_email
from event_radar.event_strength import score_news_event_strength
from event_radar.models import (
    ClassifiedEvent,
    NewsEvent,
    RadarAlert,
    ThemeMatch,
)
from event_radar.performance import summarize_alert_performance
from event_radar.repository import EventRepository
from event_radar.service import build_alert_drafts
from event_radar.technical_confirmation import TechnicalThresholds, confirm_alert
from event_radar.theme_mapper import match_themes
from event_radar.trends import TrendThresholds, update_trend_states
from pipeline.db import _create_tables, upsert_prices


def _radar_alert(alert_id, theme, ticker, priority, status):
    return RadarAlert(
        alert_id=alert_id,
        event_id=1,
        alert_date="2026-05-08",
        ticker=ticker,
        theme=theme,
        priority=priority,
        reason="reason",
        technical_status=status,
        close_price=100.0,
        relative_strength=0.05,
        breakout=True,
        volume_ratio=1.5,
        event_title="event",
        event_source="source",
        event_url="",
        event_published_at="2026-05-08",
        event_direction="bullish",
    )


class EventRadarTests(unittest.TestCase):
    def test_keyword_theme_mapping(self):
        theme_map = {
            "themes": {
                "ai_memory": {
                    "label": "AI Memory Demand",
                    "category": "Semiconductor",
                    "direction": "bullish",
                    "tickers": ["MU", "WDC"],
                    "keywords": ["AI server", "HBM", "DRAM"],
                }
            }
        }
        event = NewsEvent(
            title="AI server demand lifts HBM pricing",
            summary="DRAM makers gain pricing power",
        )

        matches = match_themes(event, theme_map, min_score=2)

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].theme, "AI Memory Demand")
        self.assertEqual(matches[0].tickers, ["MU", "WDC"])
        self.assertEqual(matches[0].score, 3)

    def test_alert_drafts_use_match_priority_thresholds(self):
        classified = ClassifiedEvent(
            news=NewsEvent(title="test"),
            matches=[
                ThemeMatch(
                    theme="AI Memory Demand",
                    category="Semiconductor",
                    tickers=["MU", "WDC"],
                    matched_keywords=["HBM", "DRAM", "AI server"],
                    score=3,
                    direction="bullish",
                    confidence=0.95,
                )
            ],
        )

        drafts = build_alert_drafts(
            event_id=10,
            classified=classified,
            high_priority_min_score=3,
            watchlist_min_score=2,
        )

        self.assertEqual(len(drafts), 2)
        self.assertTrue(all(draft.priority == "High Priority" for draft in drafts))
        self.assertEqual({draft.ticker for draft in drafts}, {"MU", "WDC"})

    def test_email_dedupe_prefers_stronger_alert(self):
        alerts = [
            _radar_alert(1, "AI Compute", "NVDA", "Watchlist", "partial"),
            _radar_alert(2, "AI Compute", "NVDA", "High Priority", "confirmed"),
            _radar_alert(3, "AI Compute", "AMD", "Watchlist", "partial"),
        ]

        deduped = dedupe_alerts_for_email(alerts)

        self.assertEqual(len(deduped), 2)
        self.assertEqual(deduped[0].alert_id, 2)
        self.assertEqual({alert.ticker for alert in deduped}, {"NVDA", "AMD"})

    def test_repository_dedupes_events_and_alerts(self):
        conn = sqlite3.connect(":memory:")
        repository = EventRepository(conn)
        classified = ClassifiedEvent(
            news=NewsEvent(title="Event", url="https://example.test/event"),
            matches=[
                ThemeMatch(
                    theme="AI Memory Demand",
                    category="Semiconductor",
                    tickers=["MU"],
                    matched_keywords=["HBM"],
                    score=1,
                )
            ],
        )

        first_event_id = repository.save_event(classified)
        second_event_id = repository.save_event(classified)
        saved_alerts = repository.save_alerts(
            build_alert_drafts(first_event_id, classified)
            + build_alert_drafts(first_event_id, classified)
        )

        self.assertEqual(first_event_id, second_event_id)
        self.assertEqual(saved_alerts, 1)

    def test_trend_alerts_are_loaded_once_per_status(self):
        conn = sqlite3.connect(":memory:")
        repository = EventRepository(conn)
        repository.upsert_trend_state(
            theme="AI Compute",
            ticker="NVDA",
            status="Cooling",
            last_event_date="2026-05-08",
            last_alert_id=1,
            last_close=100.0,
            high_watermark=110.0,
            reason="below MA20",
        )

        alerts = repository.load_unsent_trend_alerts()
        marked = repository.mark_trend_alerts_sent(alerts)
        after_mark = repository.load_unsent_trend_alerts()
        repository.upsert_trend_state(
            theme="AI Compute",
            ticker="NVDA",
            status="Closed",
            last_event_date="2026-05-08",
            last_alert_id=1,
            last_close=90.0,
            high_watermark=110.0,
            reason="drawdown from high -18.18%",
        )
        after_status_change = repository.load_unsent_trend_alerts()

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].status, "Cooling")
        self.assertEqual(marked, 1)
        self.assertEqual(after_mark, [])
        self.assertEqual(len(after_status_change), 1)
        self.assertEqual(after_status_change[0].status, "Closed")

    def test_technical_confirmation_promotes_confirmed_alert(self):
        conn = sqlite3.connect(":memory:")
        _create_tables(conn)
        repository = EventRepository(conn)
        dates = pd.date_range("2026-01-01", periods=61, freq="D")

        def prices(base, last_close, last_volume):
            rows = []
            for idx, _date in enumerate(dates):
                close = base + idx * 0.1
                rows.append(
                    {
                        "open": close,
                        "high": close + 0.5,
                        "low": close - 0.5,
                        "close": close,
                        "volume": 1000,
                    }
                )
            rows[-1]["close"] = last_close
            rows[-1]["high"] = last_close
            rows[-1]["volume"] = last_volume
            return pd.DataFrame(rows, index=dates)

        upsert_prices(conn, prices(100, 120, 3000), "MU")
        upsert_prices(conn, prices(100, 106, 1000), "SPY")
        upsert_prices(conn, prices(100, 105, 1000), "QQQ")

        check = confirm_alert(
            alert=type(
                "Pending",
                (),
                {
                    "alert_id": 1,
                    "ticker": "MU",
                    "theme": "AI Memory Demand",
                    "priority": "Info",
                    "reason": "event reason",
                },
            )(),
            repository=repository,
            thresholds=TechnicalThresholds(high_priority_confirmations=3),
        )

        self.assertEqual(check.priority, "High Priority")
        self.assertEqual(check.technical_status, "confirmed")
        self.assertTrue(check.breakout)
        self.assertGreater(check.volume_ratio, 1.3)

    def test_high_priority_requires_volume_confirmation(self):
        conn = sqlite3.connect(":memory:")
        _create_tables(conn)
        repository = EventRepository(conn)
        dates = pd.date_range("2026-01-01", periods=61, freq="D")

        def prices(base, last_close, last_volume):
            rows = []
            for idx, _date in enumerate(dates):
                close = base + idx * 0.1
                rows.append(
                    {
                        "open": close,
                        "high": close + 0.5,
                        "low": close - 0.5,
                        "close": close,
                        "volume": 1000,
                    }
                )
            rows[-1]["close"] = last_close
            rows[-1]["high"] = last_close
            rows[-1]["volume"] = last_volume
            return pd.DataFrame(rows, index=dates)

        upsert_prices(conn, prices(100, 120, 300), "MU")
        upsert_prices(conn, prices(100, 106, 1000), "SPY")
        upsert_prices(conn, prices(100, 105, 1000), "QQQ")

        check = confirm_alert(
            alert=type(
                "Pending",
                (),
                {
                    "alert_id": 1,
                    "ticker": "MU",
                    "theme": "AI Memory Demand",
                    "priority": "Info",
                    "reason": "event reason",
                },
            )(),
            repository=repository,
            thresholds=TechnicalThresholds(high_priority_confirmations=3),
        )

        self.assertEqual(check.priority, "Watchlist")
        self.assertEqual(check.technical_status, "partial")
        self.assertLess(check.volume_ratio, 1.0)

    def test_opinion_article_has_low_event_strength(self):
        weak = NewsEvent(
            title="Is Nvidia (NVDA) The Best AI Stock Pick of Cathie Wood in 2026?"
        )
        strong = NewsEvent(title="NVDA raises guidance as AI demand accelerates")

        self.assertEqual(score_news_event_strength(weak), 25)
        self.assertGreaterEqual(score_news_event_strength(strong), 85)

    def test_performance_summary_groups_by_theme(self):
        conn = sqlite3.connect(":memory:")
        repository = EventRepository(conn)
        event_id = repository.save_event(
            ClassifiedEvent(
                news=NewsEvent(title="Event", url="https://example.test/perf"),
                matches=[
                    ThemeMatch(
                        theme="AI Compute",
                        category="Semiconductor",
                        tickers=["NVDA"],
                        matched_keywords=["AI"],
                        score=1,
                    )
                ],
            )
        )
        repository.save_alerts(
            build_alert_drafts(
                event_id,
                ClassifiedEvent(
                    news=NewsEvent(title="Event"),
                    matches=[
                        ThemeMatch(
                            theme="AI Compute",
                            category="Semiconductor",
                            tickers=["NVDA"],
                            matched_keywords=["AI"],
                            score=1,
                        )
                    ],
                ),
            )
        )
        alert_id = conn.execute("SELECT alert_id FROM radar_alerts").fetchone()[0]
        repository.upsert_alert_performance(
            alert_id=alert_id,
            horizon_days=5,
            price_date="2026-05-15",
            entry_price=100.0,
            exit_price=110.0,
            return_pct=0.10,
            benchmark_return_pct=0.02,
            relative_return_pct=0.08,
            max_drawdown_pct=-0.03,
        )

        summaries = summarize_alert_performance(
            repository,
            horizon_days=5,
            group_by="theme",
        )

        self.assertEqual(len(summaries), 1)
        self.assertEqual(summaries[0].group, "AI Compute")
        self.assertEqual(summaries[0].sample_count, 1)
        self.assertAlmostEqual(summaries[0].avg_relative_return_pct, 0.08)

    def test_trend_underperformance_alone_stays_active(self):
        conn = sqlite3.connect(":memory:")
        _create_tables(conn)
        repository = EventRepository(conn)
        self._save_trend_candidate(repository, ticker="NVDA")
        dates = pd.date_range("2026-01-01", periods=61, freq="D")
        upsert_prices(conn, self._trend_prices(dates, last_close=116), "NVDA")
        upsert_prices(conn, self._trend_prices(dates, last_close=130), "SPY")
        upsert_prices(conn, self._trend_prices(dates, last_close=128), "QQQ")

        results = update_trend_states(
            repository,
            thresholds=TrendThresholds(cooling_min_signals=2),
            dry_run=True,
        )

        self.assertEqual(results[0].status, "Active")
        self.assertEqual(results[0].reason, "trend remains active")

    def test_trend_requires_multiple_cooling_signals(self):
        conn = sqlite3.connect(":memory:")
        _create_tables(conn)
        repository = EventRepository(conn)
        self._save_trend_candidate(repository, ticker="NVDA")
        dates = pd.date_range("2026-01-01", periods=61, freq="D")
        upsert_prices(conn, self._trend_prices(dates, last_close=90), "NVDA")
        upsert_prices(conn, self._trend_prices(dates, last_close=130), "SPY")
        upsert_prices(conn, self._trend_prices(dates, last_close=128), "QQQ")

        results = update_trend_states(
            repository,
            thresholds=TrendThresholds(cooling_min_signals=2),
            dry_run=True,
        )

        self.assertEqual(results[0].status, "Cooling")
        self.assertIn("below MA20", results[0].reason)
        self.assertIn("underperforming SPY/QQQ over 20d", results[0].reason)

    def _save_trend_candidate(self, repository, ticker):
        event_id = repository.save_event(
            ClassifiedEvent(
                news=NewsEvent(
                    title="AI infrastructure demand",
                    url=f"https://example.test/{ticker}",
                    published_at=date.today().isoformat(),
                ),
                matches=[
                    ThemeMatch(
                        theme="AI Compute",
                        category="Semiconductor",
                        tickers=[ticker],
                        matched_keywords=["AI"],
                        score=1,
                    )
                ],
            )
        )
        repository.save_alerts(
            build_alert_drafts(
                event_id,
                ClassifiedEvent(
                    news=NewsEvent(title="AI infrastructure demand"),
                    matches=[
                        ThemeMatch(
                            theme="AI Compute",
                            category="Semiconductor",
                            tickers=[ticker],
                            matched_keywords=["AI"],
                            score=1,
                        )
                    ],
                ),
            )
        )
        repository.conn.execute(
            "UPDATE radar_alerts SET technical_status='partial' WHERE ticker=?",
            (ticker,),
        )
        repository.conn.commit()

    def _trend_prices(self, dates, last_close):
        rows = []
        for idx, _date in enumerate(dates):
            close = 100 + idx * 0.3
            rows.append(
                {
                    "open": close,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "volume": 1000,
                }
            )
        rows[-1]["close"] = last_close
        rows[-1]["high"] = max(rows[-1]["high"], last_close)
        rows[-1]["low"] = min(rows[-1]["low"], last_close)
        return pd.DataFrame(rows, index=dates)


if __name__ == "__main__":
    unittest.main()
