#!/usr/bin/env python3
"""The established team CSV, backed by the approved dashboard outcome rules."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import tempfile
from datetime import date, datetime, time, timedelta
from pathlib import Path

from aggregates import BOOKING_SCOPE, VP_BOOKING_CLOSERS
from reporting import ARCHIVE_START, PACIFIC, ROOT
from reports import money, pipeline_snapshot, rate

ACTIVE_CLOSERS = tuple(VP_BOOKING_CLOSERS)
FIELDS = ('occurred_calls', 'showed', 'qualified', 'closed_won', 'revenue')
# Preserve the established team report's goal policy, with Booked now occurring calls.
REVENUE_GOAL_AVG_DEAL = 7_000
GOAL_PIPELINE = 840_000
GOAL_SHOW_RATE = .65
GOAL_CLOSE_RATE_NET = .13
GOAL_CLOSE_RATE_QUAL = .20
PIPELINE_WEIGHT = .20
PIPELINE_PER_LEAD = REVENUE_GOAL_AVG_DEAL * PIPELINE_WEIGHT


def validate_source(data, start, end):
    if data.get('booking_scope') != BOOKING_SCOPE:
        raise ValueError('Team report requires the approved VP booking scope')
    if data.get('rules_version') != json.loads((ROOT / 'rules.json').read_text())['version']:
        raise ValueError('Source booking rules do not match the approved V2 implementation')
    cutoff = datetime.fromisoformat(data['source_cutoff'])
    if cutoff.tzinfo is None:
        raise ValueError('Source cutoff requires a timezone')
    cutoff = cutoff.astimezone(PACIFIC)
    lower = datetime.combine(start, time.min, PACIFIC)
    upper = datetime.combine(end + timedelta(days=1), time.min, PACIFIC)
    if not lower < cutoff <= upper or data['period'].split(' through ')[0] != start.isoformat():
        raise ValueError('Source snapshot dates do not match the requested window')
    if (cutoff - timedelta(microseconds=1)).date() != end:
        raise ValueError('Source snapshot does not cover the requested end date')
    totals = data['totals']
    if any(key not in totals for key in FIELDS) or data.get('team') is None:
        raise ValueError('Source lacks outcome-based team detail')
    if not set(ACTIVE_CLOSERS) <= data.get('pipeline', {}).get('counts', {}).keys():
        raise ValueError('Source lacks the separately captured pipeline snapshot')
    for key in FIELDS:
        if abs(sum(row.get(key, 0) for row in data['team']) - totals[key]) > .01:
            raise ValueError('Source team reconciliation differs: ' + key)
    if 'no_shows' in totals and totals['occurred_calls'] != totals['showed'] + totals['no_shows']:
        raise ValueError('Occurred calls must equal shows plus no-shows')


def saved_source(start, end, archives):
    candidates = []
    for path in archives.glob('data-*.json'):
        data = json.loads(path.read_text())
        view = data.get('view', {})
        if view.get('start') != start.isoformat() or view.get('end') != end.isoformat():
            continue
        if 'occurred_calls' not in data.get('totals', {}):
            continue  # Frozen older definitions are never silently relabeled.
        validate_source(data, start, end)
        candidates.append((data['generated_at'], path, data))
    if not candidates:
        return None
    _, path, data = max(candidates, key=lambda item: item[0])
    return data, path


def build_source(start, end, now):
    """Exact V2 extraction for custom windows without a saved matching snapshot."""
    from build import CloseReader, build_dataset, load_api_key
    from outcome_core import ReportingReader, scheduled_dataset, occurred_dataset
    from outcome_public import apply_occurred_mtd
    from publish_shadow import public_data
    cutoff = min(now, datetime.combine(end + timedelta(days=1), time.min, PACIFIC))
    reader = ReportingReader(CloseReader(load_api_key()).get, start, cutoff)
    raw = build_dataset(reader, cutoff, start)
    raw['generated_at'] = now.isoformat()
    scheduled = scheduled_dataset(reader)
    occurred = occurred_dataset(scheduled)
    with tempfile.TemporaryDirectory(prefix='team-report-private-') as directory:
        source = Path(directory) / 'input.json'
        source.write_text(json.dumps(raw))
        result = apply_occurred_mtd(public_data(source), occurred, scheduled)
    result['pipeline'] = pipeline_snapshot(reader, now)
    validate_source(result, start, end)
    return result


def report_rows(data, start, end, *, source_label, source_hash, generated_at):
    validate_source(data, start, end)
    source_reps = {row['value']: row for row in data['team']}
    empty = dict.fromkeys(FIELDS, 0)
    reps = {name: {field: source_reps.get(name, empty).get(field, 0) for field in FIELDS}
            for name in ACTIVE_CLOSERS}
    other = {field: sum(row.get(field, 0) for row in data['team'] if row['value'] not in ACTIVE_CLOSERS)
             for field in FIELDS}
    team = {field: sum(row[field] for row in reps.values()) for field in FIELDS}
    for field in ('occurred_calls', 'showed', 'qualified'):
        if team[field] != data['totals'][field] or other[field]:
            raise ValueError('Approved closer call counts do not match V2: ' + field)
    pipeline = data['pipeline']
    for name, row in reps.items():
        row['qual_open'] = pipeline['counts'].get(name, 0)
    team['qual_open'] = sum(row['qual_open'] for row in reps.values())
    booked = team['occurred_calls']
    goal = booked * GOAL_CLOSE_RATE_NET * REVENUE_GOAL_AVG_DEAL
    rows = [['## REPORT METADATA'], ['Report', 'Team Performance — Closers'],
            ['Start Date', start.isoformat()], ['End Date', end.isoformat()],
            ['Generated At', generated_at.isoformat()], ['Source Snapshot', source_label],
            ['Source SHA-256', source_hash], ['Source Generated At', data['generated_at']],
            ['Source Cutoff (exclusive)', data['source_cutoff']], ['Timezone', 'America/Los_Angeles'],
            ['Booking Rules', data['rules_version']], ['Closers', '; '.join(ACTIVE_CLOSERS)],
            ['Booked Basis', 'Calls Occurred: qualifying scheduled calls with native Completed or No Show outcome'],
            ['Shown Basis', 'Native Completed meeting outcome; not First Call Show Up'],
            ['Qualified Basis', 'Distinct currently qualified leads in occurred-call cohort per owner'],
            ['Won / Revenue Basis', 'Included V2 opportunities by date_won and opportunity owner; independent of meeting dates'],
            ['Win Units', 'Opportunities; Rep/Manager may count distinct owner/lead wins instead'],
            ['MTD V2 Booked Difference', 'MTD V2 Total Booked is creation-date credits; compare this Booked to MTD V2 Calls Occurred'],
            ['Pipeline Snapshot', pipeline.get('generated_at', '')], ['Pipeline Basis', pipeline.get('basis', '')],
            ['Revenue Goal Basis', 'Booked (occurred calls) × 13% × $7,000'], []]

    def percent_goal(actual, target):
        return f'{100 * actual / target:.0f}%' if target else '—'

    def tile(label, actual, target, numerator, denominator, definition):
        return [label, actual, target, '', '', numerator, denominator, definition]
    rows += [['## TEAM KPI TILES'], ['Tile', 'Actual', 'Goal', '% of Goal', 'Status', 'Numerator', 'Denominator', 'Definition'],
             tile('Team Revenue Closed', money(team['revenue']), money(goal), team['closed_won'], booked, 'Date-won revenue; goal = occurred calls × 13% × $7,000'),
             tile('Team Pipeline', money(team['qual_open'] * PIPELINE_PER_LEAD), money(GOAL_PIPELINE), team['qual_open'], '', 'Saved trailing-30-day qualified-owner snapshot × $7,000 × 20%'),
             tile('Team Show Rate', rate(team['showed'], booked), f'{100 * GOAL_SHOW_RATE:.1f}%', team['showed'], booked, 'Native Completed ÷ Calls Occurred'),
             tile('Team Close Rate (Booked → Closed, Net)', rate(team['closed_won'], booked), f'{100 * GOAL_CLOSE_RATE_NET:.1f}%', team['closed_won'], booked, 'Date-won opportunities ÷ Calls Occurred'),
             tile('Team Close Rate (Qualified → Closed)', rate(team['closed_won'], team['qualified']), f'{100 * GOAL_CLOSE_RATE_QUAL:.1f}%', team['closed_won'], team['qualified'], 'Secondary ratio: date-won opportunities ÷ qualified leads'), []]
    targets = [(team['revenue'], goal), (team['qual_open'] * PIPELINE_PER_LEAD, GOAL_PIPELINE),
               (team['showed'] / booked if booked else None, GOAL_SHOW_RATE),
               (team['closed_won'] / booked if booked else None, GOAL_CLOSE_RATE_NET),
               (team['closed_won'] / team['qualified'] if team['qualified'] else None, GOAL_CLOSE_RATE_QUAL)]
    for row, (actual, target) in zip(rows[-6:-1], targets):
        row[3] = percent_goal(actual, target) if actual is not None else '—'
        row[4] = ('On / Above Goal' if actual >= target else 'Below Goal') if actual is not None and target else '—'
    rows += [['## TEAM COUNTS'], ['Metric', 'Value'], ['Booked', booked], ['Showed', team['showed']],
             ['Qualified', team['qualified']], ['Qual Rate (Qualified ÷ Booked)', rate(team['qualified'], booked)],
             ['Open Qualified Opps (Closers)', team['qual_open']], ['Pipeline (Gross, before 20%)', money(team['qual_open'] * REVENUE_GOAL_AVG_DEAL)],
             ['Revenue Goal (Deals Needed)', f'{booked * GOAL_CLOSE_RATE_NET:.1f}'], ['Closed Won', team['closed_won']],
             ['Avg Deal', money(team['revenue'] / team['closed_won']) if team['closed_won'] else '—'], [],
             ['## REP BREAKDOWN'], ['Rep', 'Revenue', 'Revenue Goal', '% of Rev Goal', 'Closed Won', 'Avg Deal',
             'Pipeline', 'Open Qualified Opps', 'Booked', 'Showed', 'Show %', 'Qualified', 'Qual %',
             'Close % (Booked → Closed, Net)', 'Close % (Qualified → Closed)']]

    def rep_line(name, row, excluded=False):
        calls, revenue, closed = row['occurred_calls'], row['revenue'], row['closed_won']
        revenue_goal = calls * GOAL_CLOSE_RATE_NET * REVENUE_GOAL_AVG_DEAL
        return [name, money(revenue), money(revenue_goal), percent_goal(revenue, revenue_goal), closed,
                money(revenue / closed) if closed else '—', '' if excluded else money(row['qual_open'] * PIPELINE_PER_LEAD),
                '' if excluded else row['qual_open'], calls, row['showed'], rate(row['showed'], calls),
                row['qualified'], rate(row['qualified'], calls), rate(closed, calls), rate(closed, row['qualified'])]
    rows += [rep_line(name, row) for name, row in sorted(reps.items(), key=lambda item: (-item[1]['revenue'], -item[1]['occurred_calls'], item[0]))]
    rows += [rep_line('EXCLUDED — Other / Non-Closer', other, True), rep_line('TOTAL', team), [],
             ['## RECONCILIATION'], ['Metric', 'This Report — Closers', 'MTD V2 Same Snapshot — All Owners', 'Other / Non-Closer', 'Match Including Other']]
    for label, key in [('Booked / Calls Occurred', 'occurred_calls'), ('Showed', 'showed'), ('Qualified', 'qualified'), ('Closed Won', 'closed_won'), ('Revenue', 'revenue')]:
        if abs(team[key] + other[key] - data['totals'][key]) > .01:
            raise ValueError('Team report does not reconcile: ' + key)
        rows.append([label, team[key], data['totals'][key], other[key], 'YES'])
    rows += [[], ['## DATA NOTES'], ['Source selection', 'Same saved V2 snapshot where available; no independent lead-field booking/show calculation'],
             ['Reporting windows', 'Compare identical start/end dates and Source Cutoff; a weekly report is not the current full MTD'],
             ['Excluded roster', 'Only the nine approved VP closers appear; other owners are audit-only'],
             ['Native definition differences', 'Win opportunity/lead units, owner scope and trailing-30-day pipeline remain explicitly separate'], [], ['## WARNINGS'], ['None']]
    return rows


def generate(start, end, *, source=None, archives=None, output=None, now=None):
    now = now or datetime.now(PACIFIC)
    if start < ARCHIVE_START or end < start or end > now.date():
        raise ValueError('Use an October 2026-or-later window ending no later than today')
    if source:
        path = Path(source)
        data = json.loads(path.read_text())
        validate_source(data, start, end)
    else:
        saved = saved_source(start, end, Path(archives or ROOT / 'archives'))
        if saved:
            data, path = saved
        else:
            data, path = build_source(start, end, now), None
    if path:
        source_label = str(path.relative_to(ROOT.parent)) if path.is_relative_to(ROOT.parent) else str(path)
        source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        source_label = 'Fresh exact V2 read-only custom-window capture'
        source_hash = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
    rows = report_rows(data, start, end, source_label=source_label, source_hash=source_hash, generated_at=now)
    output = Path(output or ROOT.parent / 'reports')
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f'team_report_{start}_{end}.csv'
    temporary = destination.with_suffix('.csv.tmp')
    with temporary.open('w', newline='') as stream:
        csv.writer(stream).writerows(rows)
    temporary.replace(destination)
    print('Written aligned team report:', destination)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', required=True, type=date.fromisoformat)
    parser.add_argument('--end', required=True, type=date.fromisoformat)
    parser.add_argument('--source', type=Path, help='Use an explicit matching saved V2 aggregate snapshot')
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    try:
        generate(args.start, args.end, source=args.source, output=args.output_dir)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
