import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import build
from aggregates import CLOSERS, OTHER_OWNER, build_breakdowns
from publish_shadow import public_data, render_report
from reporting import PACIFIC, presentation
from reports import funnel_rows, pipeline_snapshot, team_rows, write_comparison
from test_reporting import private_snapshot


def accepted_records():
    booking = dict(lead_id="PRIVATE_LEAD", channel="YouTube", bucket="Lane 2",
                   setter="Charlie Ingram", owner="user_test", showed=True,
                   qualified=True, utm_campaign="Campaign A", utm_content="Content A")
    bookings = [booking, {**booking, "showed": False},
                {**booking, "lead_id": "PRIVATE_OTHER", "bucket": "Marketing", "owner": None, "setter": "Marketing"}]
    won = [dict(lead_id="PRIVATE_LEAD", channel="YouTube", revenue=5997,
                utm_campaign="Campaign A", utm_content="Content A",
                package="Bronze · Basic", setter="Charlie Ingram", owner="user_test"),
           dict(lead_id="PRIVATE_NO_BOOKING", channel="YouTube", revenue=2999,
                utm_campaign="Won-only campaign", utm_content="Won content",
                package="VendHub Pro", setter="Marketing", owner="user_unknown")]
    return bookings, won, {"user_test": CLOSERS[0]}


def public_fixture():
    booked, won, users = accepted_records()
    raw = private_snapshot(None, datetime(2026, 10, 30, 8, tzinfo=PACIFIC), datetime(2026, 10, 1).date())
    totals = dict(leads_created=10, bookings=3, lane2=2, marketing=1, social_dms=0,
                  showed=2, qualified=2, closed_won=2, revenue=8996)
    raw['totals'] = totals
    raw['counted_meetings'] = 3
    raw['channels'] = [{"channel": "YouTube", **totals, "unrecoverable_booked_leads": 0}]
    raw['breakdowns'] = build_breakdowns(booked, won, users)
    return raw


class FeatureParityTests(unittest.TestCase):
    def test_accepted_credit_rollups_preserve_distinct_qualification_and_independent_wins(self):
        booked, won, users = accepted_records()
        result = build_breakdowns(booked, won, users)
        rows = {row['value']: row for row in result['channels']['YouTube']['drilldowns']}
        self.assertEqual(rows['Campaign A']['bookings'], 3)
        self.assertEqual(rows['Campaign A']['qualified'], 2)
        self.assertEqual(rows['Campaign A']['showed'], 2)
        self.assertEqual(rows['Won-only campaign']['bookings'], 0)
        self.assertEqual(rows['Won-only campaign']['revenue'], 2999)
        self.assertEqual(sum(row['revenue'] for row in result['channels']['YouTube']['packages']), 8996)
        team = {row['value']: row for row in result['team']}
        self.assertEqual(team[CLOSERS[0]]['bookings'], 2)
        self.assertEqual(team[CLOSERS[0]]['qualified'], 1)
        self.assertEqual(team[OTHER_OWNER]['revenue'], 2999)
        self.assertNotIn('user_unknown', json.dumps(result))

    def test_whitelist_full_drilldowns_and_csv_totals(self):
        raw = public_fixture()
        raw['breakdowns']['channels']['YouTube']['drilldowns'][0]['lead_id'] = 'PRIVATE_LEAD'
        raw['breakdowns']['channels']['YouTube']['drilldowns'][0]['value'] = '</script><script>unsafe</script>'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'private.json'
            source.write_text(json.dumps(raw))
            data = public_data(source)
            out = Path(directory) / 'index.html'
            render_report(data, out)
            html = out.read_text()
        self.assertNotIn('PRIVATE_LEAD', html)
        self.assertNotIn('</script><script>unsafe', html)
        self.assertEqual(data['channels'][0]['drilldowns'][0]['qualified'], 2)
        self.assertEqual(funnel_rows(data)[-1][0], 'TOTAL')
        self.assertEqual(funnel_rows(data)[-1][2], 3)
        reconciliation = team_rows(data)
        self.assertEqual(len([row for row in reconciliation if row and row[-1] == 'YES']), 5)
        data['team'][0]['bookings'] += 1
        with self.assertRaisesRegex(ValueError, 'reconciliation'):
            team_rows(data)

    def test_rounding_matches_legacy_python_half_even(self):
        raw = public_fixture()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'private.json'; source.write_text(json.dumps(raw))
            data = public_data(source)
        data['progress'].update(day=2, days=3)
        data['channels'][0]['bookings'] = 3
        presentation(data)
        self.assertEqual(data['channels'][0]['display']['projected'], 4)
        data['channels'][0]['bookings'] = 1
        data['totals']['bookings'] = 1
        data['goals']['channels']['YouTube'] = 200
        data['goals']['bookings'] = 200
        presentation(data)
        self.assertEqual(data['channels'][0]['display']['goal_pct'], 0)
        self.assertEqual(data['goal_percentages']['bookings'], 0)

    def test_v2_repeat_boundary_and_cancellation_policy_unchanged(self):
        start = datetime(2026, 10, 1, 9, tzinfo=PACIFIC)
        first = dict(id='first', lead_id='same', starts_at=start.isoformat(), date_created=start.isoformat())
        exact = {**first, 'id':'exact', 'starts_at':(start+timedelta(hours=720)).isoformat()}
        candidates = [dict(meeting_id=meeting['id'], lead_id='same', bucket='Lane 2') for meeting in [first,exact]]
        selected, _ = build.choose_bucket_credits(candidates, [first,exact], {})
        self.assertEqual([row['meeting_id'] for row in selected], ['first'])
        after = {**exact, 'starts_at':(start+timedelta(hours=720,seconds=1)).isoformat()}
        selected, _ = build.choose_bucket_credits(candidates, [first,after], {})
        self.assertEqual(len(selected), 2)
        self.assertTrue(build.cancellation({'status':'declined-by-lead'}, ''))
        self.assertEqual(build.title_bucket({'title':'Vendingpreneurs - Next Steps Call','date_created':start.isoformat()}, {})[0], 'Lane 2')
        self.assertEqual(build.title_bucket({'title':'Vending Strategy Call','date_created':start.isoformat(),'user_id':build.RULES['excluded_callers'][0]}, {})[0], '')

    def test_only_pipeline_helper_uses_legacy_module(self):
        getter = lambda *args: {'data':[]}
        legacy = SimpleNamespace(CLOSERS=list(CLOSERS), close_get='original')
        def capture(now):
            self.assertEqual(legacy.close_get, getter)
            return {name: 0 for name in CLOSERS}, {}
        legacy.fetch_open_qualified_by_closer = capture
        with patch('reports.importlib.import_module', return_value=legacy):
            snapshot = pipeline_snapshot(SimpleNamespace(get=getter), datetime(2026,10,30,tzinfo=PACIFIC))
        self.assertEqual(sum(snapshot['counts'].values()), 0)
        self.assertEqual(legacy.close_get, 'original')

    def test_comparison_only_uses_v2_month_snapshots(self):
        raw = public_fixture()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)/'private.json'; source.write_text(json.dumps(raw))
            data = public_data(source)
            data['view'] = dict(kind='month', key='2026-10', label='October 2026', frozen=False)
            out = Path(directory)/'mom.html'
            write_comparison([data], out)
            html = out.read_text()
            self.assertIn('October 2026', html)
            self.assertIn('V2 booking and attribution rules', html)
            self.assertNotIn('PRIVATE_LEAD', html)


if __name__ == '__main__':
    unittest.main()
