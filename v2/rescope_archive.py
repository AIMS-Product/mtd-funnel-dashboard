"""Scope a frozen archive using booking evidence reconciled to its saved state.

The input rows and user directory are private audit artifacts. Only aggregate
output is written. This never replaces a historical snapshot with current CRM
ownership: every saved booking rollup must match before a subset is applied.
"""

import argparse
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path

from aggregates import BOOKING_SCOPE, build_breakdowns, vp_closer_bookings
from reporting import PACIFIC, presentation

BOOKING_FIELDS = ('bookings', 'marketing', 'lane2', 'social_dms', 'showed', 'qualified')


def check_groups(saved, reconstructed, context):
    old = {row['value']: row for row in saved}
    new = {row['value']: row for row in reconstructed}
    for name in old.keys() | new.keys():
        for field in BOOKING_FIELDS:
            if old.get(name, {}).get(field, 0) != new.get(name, {}).get(field, 0):
                raise ValueError(f'Historical evidence differs from saved {context}: {name} / {field}')


def replace_groups(saved, reconstructed):
    new = {row['value']: row for row in reconstructed}
    for row in saved:
        for field in BOOKING_FIELDS:
            row[field] = new.get(row['value'], {}).get(field, 0)


def rescope_saved_report(saved, bookings, users):
    if not saved['view']['frozen']:
        raise ValueError('This migration requires a frozen snapshot')
    if len({row['meeting_id'] for row in bookings}) != len(bookings):
        raise ValueError('Historical meeting evidence contains duplicate IDs')
    all_owners = build_breakdowns(bookings, [], users)
    check_groups(saved['team'], all_owners['team'], 'team')
    check_groups(saved['setters'], all_owners['setters'], 'setters')
    for channel in saved['channels']:
        related = [row for row in bookings if row['channel'] == channel['channel']]
        summary = summarize(related)
        for field in BOOKING_FIELDS:
            if channel[field] != summary[field]:
                raise ValueError(f'Historical evidence differs from saved source: {channel["channel"]} / {field}')
        detail = all_owners['channels'].get(channel['channel'], {})
        check_groups(channel['drilldowns'], detail.get('drilldowns', []), channel['channel'] + ' drilldowns')
        check_groups(channel.get('setters', []), detail.get('setters', []), channel['channel'] + ' setters')
    if saved['totals']['bookings'] != len(bookings):
        raise ValueError('Historical evidence does not reproduce the saved total')

    selected = vp_closer_bookings(bookings, users)
    scoped = build_breakdowns(selected, [], users)
    result = deepcopy(saved)
    replace_groups(result['team'], scoped['team'])
    replace_groups(result['setters'], scoped['setters'])
    for channel in result['channels']:
        related = [row for row in selected if row['channel'] == channel['channel']]
        channel.update(summarize(related))
        channel['unrecoverable_booked_leads'] = len({row['lead_id'] for row in related if row['channel'] == 'Unknown (Needs Review)'})
        detail = scoped['channels'].get(channel['channel'], {})
        replace_groups(channel['drilldowns'], detail.get('drilldowns', []))
        replace_groups(channel.get('setters', []), detail.get('setters', []))
    for field in BOOKING_FIELDS:
        result['totals'][field] = sum(row[field] for row in result['channels'])
        if sum(row[field] for row in result['team']) != result['totals'][field]:
            raise ValueError('Scoped source and owner totals do not reconcile: ' + field)
    result['counted_meetings'] = len(selected)
    result['booking_scope'] = BOOKING_SCOPE
    result['booking_scope_changed_at'] = datetime.now(PACIFIC).isoformat()
    result['booking_snapshot_basis'] = 'Historical booking detail reconciled to every saved owner, source, campaign/content and setter rollup before applying the nine VP closer roster.'
    return presentation(result)


def summarize(rows):
    return dict(bookings=len(rows), marketing=sum(row['bucket'] == 'Marketing' for row in rows),
                lane2=sum(row['bucket'] == 'Lane 2' for row in rows),
                social_dms=sum(row['bucket'] == 'Social DMs' for row in rows),
                showed=sum(bool(row['showed']) for row in rows),
                qualified=len({row['lead_id'] for row in rows if row['qualified']}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--bookings', type=Path, required=True)
    parser.add_argument('--users', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    saved = json.loads(args.archive.read_text())
    result = rescope_saved_report(saved, json.loads(args.bookings.read_text()), json.loads(args.users.read_text()))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result['totals'], indent=2))


if __name__ == '__main__':
    main()
