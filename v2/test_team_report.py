"""Regression contracts for the GitHub report's real entry point and CSV units."""
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from aggregates import BOOKING_SCOPE, APPOINTMENT_BOOKING_SCOPE, METRICS
from reporting import PACIFIC, ROOT
from team_report import ACTIVE_CLOSERS, FIELDS, generate, report_rows, saved_source, validate_source

START, END = date(2026, 11, 2), date(2026, 11, 8)


def fixture():
    first = dict.fromkeys((*METRICS, 'occurred_calls'), 0)
    first.update(value=ACTIVE_CLOSERS[0], bookings=9, occurred_calls=2, showed=1, qualified=1,
                 closed_won=1, revenue=100)
    inactive = dict.fromkeys((*METRICS, 'occurred_calls'), 0)
    inactive.update(value='Oscar Pugh', closed_won=1, revenue=50)
    totals = {field: first.get(field, 0) + inactive.get(field, 0) for field in (*METRICS, 'occurred_calls')}
    totals['no_shows'] = 1
    pipeline = {name: 0 for name in ACTIVE_CLOSERS}
    pipeline.update({ACTIVE_CLOSERS[0]: 3, 'Oscar Pugh': 4})
    return {'booking_scope': BOOKING_SCOPE, 'rules_version': json.loads((ROOT/'rules.json').read_text())['version'],
            'source_cutoff': '2026-11-09T00:00:00-08:00', 'generated_at': '2026-11-09T00:00:25-08:00',
            'period': '2026-11-02 through 2026-11-08 PT', 'totals': totals, 'team': [first, inactive],
            'pipeline': {'counts': pipeline, 'generated_at': '2026-11-09T00:00:25-08:00', 'basis': 'Saved trailing-30-day owner snapshot'},
            'view': {'start': START.isoformat(), 'end': END.isoformat()}}


class TeamReportTests(unittest.TestCase):
    def test_current_appointment_scope_and_saved_owner_scope_keep_their_definitions(self):
        for scope in (BOOKING_SCOPE, APPOINTMENT_BOOKING_SCOPE):
            data = fixture()
            data['booking_scope'] = scope
            validate_source(data, START, END)
        data['booking_scope'] = 'unrecognized-scope'
        with self.assertRaisesRegex(ValueError, 'VP booking scope'):
            validate_source(data, START, END)

    def rows(self, data=None):
        return report_rows(data or fixture(), START, END, source_label='saved-v2', source_hash='source-hash',
                           generated_at=datetime(2026, 11, 10, tzinfo=PACIFIC))

    def test_booked_and_all_primary_rates_use_occurred_not_creation_or_show_fields(self):
        rows = self.rows()
        self.assertIn(['Booked', 2], rows)
        self.assertIn(['Qual Rate (Qualified ÷ Booked)', '50.0%'], rows)
        tiles = {row[0]: row for row in rows if row and row[0].startswith('Team ')}
        self.assertEqual(tiles['Team Show Rate'][1], '50.0%')
        self.assertEqual(tiles['Team Show Rate'][5:7], [1, 2])
        self.assertEqual(tiles['Team Close Rate (Booked → Closed, Net)'][1], '50.0%')
        self.assertEqual(tiles['Team Revenue Closed'][2], '$1,820')

    def test_inactive_owner_is_audit_only_and_date_won_totals_are_not_forced(self):
        rows = self.rows()
        self.assertNotIn('Oscar Pugh', json.dumps(rows))
        total = next(row for row in rows if row and row[0] == 'TOTAL')
        self.assertEqual(total[1], '$100')
        self.assertEqual(total[4], 1)
        self.assertIn(['Closed Won', 1, 2, 1, 'YES'], rows)
        self.assertIn(['Revenue', 100, 150, 50, 'YES'], rows)
        self.assertIn(['Open Qualified Opps (Closers)', 3], rows)

    def test_zero_calls_keep_independent_wins_with_undefined_rates(self):
        data = fixture()
        for row in data['team']:
            row.update(occurred_calls=0, showed=0, qualified=0)
        data['totals'].update(occurred_calls=0, showed=0, qualified=0, no_shows=0)
        rows = self.rows(data)
        self.assertIn(['Closed Won', 1], rows)
        show = next(row for row in rows if row and row[0] == 'Team Show Rate')
        self.assertEqual(show[1], '—')

    def test_matching_snapshot_is_reused_without_source_reads_or_archive_mutation(self):
        data = fixture()
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            source = folder/'data-week-2026-11-02.json'; source.write_text(json.dumps(data))
            before = source.read_bytes()
            with patch('team_report.build_source', side_effect=AssertionError('Unexpected CRM fetch')):
                output = generate(START, END, archives=folder, output=folder/'out')
            rows = list(csv.reader(output.open()))
            self.assertIn(['Booked', '2'], rows)
            self.assertIn(['Source SHA-256', hashlib.sha256(before).hexdigest()], rows)
            self.assertEqual(source.read_bytes(), before)

    def test_missing_outcomes_incorrect_windows_or_pipeline_cannot_be_relabeled(self):
        for mutation in [lambda d: d['totals'].pop('occurred_calls'),
                         lambda d: d.update(source_cutoff='2026-11-10T00:00:00-08:00'),
                         lambda d: d.update(rules_version='older-rules'),
                         lambda d: d['pipeline']['counts'].pop(ACTIVE_CLOSERS[0])]:
            data = fixture(); mutation(data)
            with self.assertRaises(ValueError): validate_source(data, START, END)

    def test_old_frozen_snapshot_is_not_overwritten_or_silently_upgraded(self):
        data = fixture(); data['totals'].pop('occurred_calls')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'data-week-old.json'; path.write_text(json.dumps(data))
            original = path.read_bytes()
            self.assertIsNone(saved_source(START, END, Path(directory)))
            self.assertEqual(path.read_bytes(), original)

    def test_real_established_cli_routes_to_v2_without_crm_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory); source = folder/'source.json'; source.write_text(json.dumps(fixture()))
            import os
            environment = {key: value for key, value in os.environ.items() if key != 'CLOSE_API_KEY'}
            result = subprocess.run([sys.executable, str(ROOT.parent/'generate_team_report.py'),
                                     '--start', START.isoformat(), '--end', END.isoformat(),
                                     '--source', str(source), '--output-dir', str(folder/'out')],
                                    env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = list(csv.reader((folder/'out/team_report_2026-11-02_2026-11-08.csv').open()))
            self.assertIn(['Booked', '2'], rows)
            self.assertNotIn('Oscar Pugh', json.dumps(rows))


if __name__ == '__main__': unittest.main()
