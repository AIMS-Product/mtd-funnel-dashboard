"""Regression coverage for V2 periods, public output, and archive rollover."""

import json
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import build
import refresh
from reporting import PACIFIC, display_metadata, report_periods


def private_snapshot(reader, cutoff, start):
    totals = dict(leads_created=10, bookings=4, marketing=2, lane2=1, social_dms=1,
                  showed=3, qualified=2, closed_won=1, revenue=5997)
    return {
        "generated_at": cutoff.isoformat(), "source_cutoff": cutoff.isoformat(),
        "period": f"{start} through {(cutoff - timedelta(microseconds=1)).date()} PT",
        "rules_version": "test-rules", "counted_meetings": 4,
        "excluded_repeat_candidates": 1, "vendhub_arr": 1200,
        "totals": totals,
        "channels": [{"channel": "YouTube", **totals, "unrecoverable_booked_leads": 0,
                      "drilldowns": [{"campaign": "</script><script>unsafe</script>",
                                      "content": [{"name": "Example", "bookings": 4,
                                                   "rows": [{"lead_name": "PRIVATE_CUSTOMER"}]}]}]}],
        "rows": [{"lead_name": "PRIVATE_CUSTOMER", "lead_id": "PRIVATE_LEAD"}],
    }


class ReportingTests(unittest.TestCase):
    def test_october_progress_matches_current_mtd(self):
        progress = display_metadata(date(2026, 10, 1), datetime(2026, 10, 30, 8, tzinfo=PACIFIC))
        self.assertEqual(progress, dict(day=30, days=31, working_days=22,
                                        working_elapsed=22, elapsed_pct=100.0))
        closed = display_metadata(date(2026, 10, 1), datetime(2026, 11, 1, tzinfo=PACIFIC))
        self.assertEqual(closed["day"], 31)

    def test_october_includes_opening_partial_week_and_current_week(self):
        now = datetime(2026, 10, 30, 8, tzinfo=PACIFIC)
        periods = report_periods(now)
        weeks = [p for p in periods if p.kind == "week"]
        self.assertEqual(len(weeks), 5)
        self.assertEqual(weeks[0].start, date(2026, 10, 1))
        self.assertEqual(weeks[0].end, date(2026, 10, 5))
        self.assertEqual(weeks[-1].key, "week-2026-10-26")
        self.assertFalse(weeks[-1].view(now)["frozen"])
        self.assertTrue(all(p.start >= date(2026, 10, 1) for p in periods))

    def test_week_cutoffs_follow_pacific_dst(self):
        period = report_periods(datetime(2026, 11, 2, 8, tzinfo=PACIFIC))[-2]
        self.assertEqual(period.key, "week-2026-10-26")
        self.assertEqual(period.cutoff(datetime(2026, 11, 2, 8, tzinfo=PACIFIC)).isoformat(),
                         "2026-11-02T00:00:00-08:00")

    def test_public_archives_freeze_and_finalize_at_rollover(self):
        now = datetime(2026, 10, 30, 8, tzinfo=PACIFIC)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archives = root / "archives"
            with patch.object(refresh, "ROOT", root), patch.object(refresh, "ARCHIVES", archives), \
                 patch.object(refresh, "load_api_key", return_value="test"), \
                 patch.object(refresh, "build_dataset", side_effect=private_snapshot) as builder:
                refresh.refresh(now)
                self.assertEqual(builder.call_count, 6)
                old_week = archives / "data-week-2026-10-05.json"
                frozen_bytes = old_week.read_bytes()
                builder.reset_mock()
                refresh.refresh(now + timedelta(minutes=15))
                self.assertEqual(builder.call_count, 2)
                self.assertEqual(old_week.read_bytes(), frozen_bytes)
                builder.reset_mock()
                rollover = datetime(2026, 11, 2, 8, tzinfo=PACIFIC)
                refresh.refresh(rollover)
                self.assertEqual(builder.call_count, 4)
                october = json.loads((archives / "data-2026-10.json").read_text())
                self.assertTrue(october["view"]["frozen"])
                self.assertEqual(october["source_cutoff"], "2026-11-01T00:00:00-07:00")
                self.assertEqual(october["goals"]["bookings"], 1241)
                last_week = json.loads((archives / "data-week-2026-10-26.json").read_text())
                self.assertEqual(last_week["source_cutoff"], "2026-11-02T00:00:00-08:00")
                for path in root.rglob('*'):
                    if not path.is_file():
                        continue
                    text = path.read_text()
                    self.assertNotIn("PRIVATE_CUSTOMER", text)
                    self.assertNotIn("PRIVATE_LEAD", text)
                    if path.suffix == '.html':
                        self.assertNotIn("</script><script>unsafe", text)
                builder.reset_mock()
                refresh.refresh(rollover, render_only=True)
                builder.assert_not_called()


class SourceWindowTests(unittest.TestCase):
    def test_historical_window_excludes_next_day_and_accumulates_arr(self):
        lead = {
            "id": "sample", "date_created": "2026-10-05T12:00:00Z",
            f"custom.{build.RULES['lead_fields']['funnel']}": "YouTube",
            f"custom.{build.PROGRAM_TIER_FIELD}": "Bronze - $5,997",
        }

        class Reader:
            def __init__(self):
                self.won_params = None

            def pages(self, endpoint, params=None):
                if endpoint == 'lead/':
                    return [lead, {**lead, "id": "boundary", "date_created": "2026-10-12T07:00:00Z"}]
                if endpoint == 'opportunity/':
                    self.won_params = params
                    return [{"lead_id": "sample", "value": 599700, "currency": "USD"},
                            {"lead_id": "sample", "value": 599700, "currency": "EUR"}]
                return []

            def meetings_created_in_window(self, start, end):
                return []

            def meeting_history_for_leads(self, ids):
                return []

        reader = Reader()
        result = build.build_dataset(reader, datetime(2026, 10, 12, tzinfo=PACIFIC), date(2026, 10, 5))
        self.assertEqual(result['totals']['leads_created'], 1)
        self.assertEqual(result['totals']['revenue'], 5997)
        self.assertEqual(result['vendhub_arr'], 1200)
        self.assertEqual(reader.won_params['date_won__lte'], '2026-10-11')
        self.assertEqual(result['period'], '2026-10-05 through 2026-10-11 PT')

    def test_naive_cutoff_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'timezone'):
            build.build_dataset(None, datetime(2026, 10, 30))


if __name__ == '__main__':
    unittest.main()
