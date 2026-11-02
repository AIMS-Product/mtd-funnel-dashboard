"""VP booking scope is separate from credit selection and independent wins."""

import unittest
import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import build
from aggregates import BOOKING_SCOPE, VP_BOOKING_CLOSERS, vp_closer_bookings
from reporting import PACIFIC
from publish_shadow import public_data
from rescope_archive import rescope_saved_report
from test_parity import accepted_records, public_fixture


class BookingScopeTests(unittest.TestCase):
    def frozen_fixture(self):
        raw = public_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'raw.json'
            path.write_text(json.dumps(raw))
            saved = public_data(path)
        saved['view'] = {'frozen': True}
        rows, _, users = accepted_records()
        rows = [{**row, 'meeting_id': str(i)} for i, row in enumerate(rows)]
        return saved, rows, users

    def test_frozen_scope_preserves_snapshot_and_independent_wins(self):
        saved, rows, users = self.frozen_fixture()
        original = json.dumps(saved, sort_keys=True)
        result = rescope_saved_report(saved, rows, users)
        self.assertEqual((result['totals']['bookings'], result['totals']['showed'], result['totals']['qualified']), (2, 1, 1))
        self.assertEqual((result['totals']['closed_won'], result['totals']['revenue']), (2, 8996))
        self.assertEqual(result['source_cutoff'], saved['source_cutoff'])
        self.assertEqual(result['generated_at'], saved['generated_at'])
        self.assertEqual(result['totals']['leads_created'], saved['totals']['leads_created'])
        self.assertEqual(result['channels'][0]['packages'], saved['channels'][0]['packages'])
        self.assertEqual(json.dumps(saved, sort_keys=True), original)

    def test_frozen_scope_rejects_missing_or_mismatched_historical_detail(self):
        saved, rows, users = self.frozen_fixture()
        with self.assertRaisesRegex(ValueError, 'Historical evidence'):
            rescope_saved_report(saved, rows[:-1], users)
        rows[0]['utm_campaign'] = 'Changed after the archive'
        with self.assertRaisesRegex(ValueError, 'Historical evidence'):
            rescope_saved_report(saved, rows, users)

    def test_exact_nine_person_roster_and_missing_or_external_owners(self):
        users = {f'user_{i}': name for i, name in enumerate(VP_BOOKING_CLOSERS)}
        users['user_oscar'] = 'Oscar Pugh'
        rows = [{'owner': key} for key in users] + [{'owner': None}, {'owner': 'user_missing'}, {'owner': 'Rob Maxfield'}]
        selected = vp_closer_bookings(rows, users)
        self.assertEqual(len(selected), 9)
        self.assertNotIn('Oscar Pugh', VP_BOOKING_CLOSERS)
        self.assertIn('Joe Dysert', VP_BOOKING_CLOSERS)
        self.assertEqual(vp_closer_bookings([{'owner': {'id': 'user_0'}}], users), [{'owner': {'id': 'user_0'}}])
        self.assertEqual(len(rows), 13)

    def test_builder_scopes_every_booking_rollup_and_preserves_independent_populations(self):
        leads = {
            key: {'id': key, 'display_name': key,
                  f'custom.{build.LEAD_OWNER_FIELD}': owner,
                  f'custom.{build.RULES["lead_fields"]["funnel"]}': 'YouTube',
                  f'custom.{build.QUALIFIED_FIELD}': 'Yes'}
            for key, owner in [('vp', 'user_vp'), ('oscar', 'user_oscar'), ('other', None)]
        }
        meetings = [dict(id=key, lead_id=key, user_id='creator', title='Vending Strategy Call',
                         date_created='2026-10-10T15:00:00Z', starts_at='2026-10-11T15:00:00Z',
                         status='completed', outcome_id='completed') for key in leads]

        class Reader:
            def meetings_created_in_window(self, *args):
                return meetings

            def meeting_history_for_leads(self, ids):
                return meetings

            def pages(self, endpoint, params=None):
                if endpoint == 'outcome/':
                    return [{'id': 'completed', 'label': 'Completed'}]
                if endpoint == 'user/':
                    return [{'id': 'user_vp', 'first_name': 'Luke', 'last_name': 'Herman'},
                            {'id': 'user_oscar', 'first_name': 'Oscar', 'last_name': 'Pugh'}]
                return []

            def get(self, endpoint, params=None):
                return leads[endpoint.split('/')[1]]

        won = [{'lead_id': 'oscar', 'user_id': 'user_oscar', 'value': 10000, 'currency': 'USD'}]
        with patch.object(build, 'fetch_created_leads', return_value=[]), patch.object(build, 'fetch_won_opportunities', return_value=won):
            result = build.build_dataset(Reader(), datetime(2026, 11, 1, tzinfo=PACIFIC), date(2026, 10, 1))
        self.assertEqual(result['booking_scope'], BOOKING_SCOPE)
        self.assertEqual(result['excluded_owner_bookings'], 2)
        self.assertEqual([row['lead_id'] for row in result['rows']], ['vp'])
        self.assertEqual((result['totals']['bookings'], result['totals']['showed'], result['totals']['qualified']), (1, 1, 1))
        self.assertEqual((result['totals']['closed_won'], result['totals']['revenue']), (1, 100))
        self.assertEqual(sum(row['bookings'] for row in result['breakdowns']['team']), 1)
        self.assertEqual(sum(row['bookings'] for row in result['breakdowns']['channels']['YouTube']['drilldowns']), 1)


if __name__ == '__main__':
    unittest.main()
