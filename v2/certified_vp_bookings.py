"""Apply the certified Lane 2 and Social DM meeting selection before MTD rollups."""
from datetime import date, datetime
from typing import Iterable, Mapping
from zoneinfo import ZoneInfo


BUCKETS = {'Lane 2', 'Social DMs'}
PACIFIC = ZoneInfo('America/Los_Angeles')


def align_bookings(
    legacy: Iterable[dict], candidates: Iterable[dict], membership: Iterable[Mapping], *,
    start: date, period_cutoff: datetime, reviewed_origins: Mapping[str, Mapping] | None = None,
) -> list[dict]:
    by_id = {}
    for row in candidates:
        activity = row['meeting_id']
        if activity in by_id:
            raise ValueError('MTDv2 returned duplicate candidate meetings')
        by_id[activity] = row
    resolved = {}
    for item in membership:
        activity = item['activity_id']
        if not activity or activity in resolved or item['bucket'] not in BUCKETS:
            raise ValueError('Certified VP membership contains an invalid or duplicate meeting')
        candidate = by_id.get(activity)
        if candidate is None:
            raise ValueError('A certified meeting is missing from the MTDv2 source candidates')
        canonical_day = date.fromisoformat(str(item['booked_day']))
        if canonical_day.isoformat() != candidate['booked_date_pt']:
            candidate = _apply_reviewed_origin(candidate, canonical_day, (reviewed_origins or {}).get(activity))
        if (canonical_day < start
                or not datetime.fromisoformat(candidate['booked_at']) < period_cutoff
                or not item['appointment_closer'] or item['appointment_closer'] != candidate['appointment_closer']):
            raise ValueError('A certified meeting differs from its independent MTDv2 source identity')
        resolved[activity] = {**candidate, 'bucket': item['bucket'], 'owner': item['appointment_closer']}
    if not resolved:
        raise ValueError('VP refresh requires a nonempty certified membership')
    return [row for row in legacy if row['bucket'] not in BUCKETS and row['meeting_id'] not in resolved
            ] + list(resolved.values())


def _apply_reviewed_origin(candidate: dict, day: date, proof: Mapping | None) -> dict:
    if not proof or proof['close_activity_id'] != candidate['meeting_id'] or not proof['review_sha256']:
        raise ValueError('A changed booking date requires reviewed origin evidence for the meeting')
    original = datetime.fromisoformat(proof['original_booked_at'])
    observed = datetime.fromisoformat(candidate['booked_at'])
    if (observed != datetime.fromisoformat(proof['update_date_created']) or original >= observed
            or original.astimezone(PACIFIC).date() != day):
        raise ValueError('Reviewed origin differs from either the original booking or the observed Close sync time')
    return {**candidate, 'booked_at': original.isoformat(), 'booked_date_pt': day.isoformat()}
