"""Close event evidence used by independent VP appointment booking reports."""

from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import re

from aggregates import vp_business_line

CREDIT_BUCKETS = {'Lane 2', 'Social DMs'}
REASSIGNMENT_START = '2026-10-01'
TRANSFER_WINDOW = timedelta(seconds=60)
RESCHEDULE_STATUS = re.compile(r'(reschedule requested|call rescheduled)$', re.I)
FOLLOWUP_TITLE = re.compile(r'follow[-\s]?up|fallow\s+up|\bf/u\b|reschedul', re.I)


@dataclass(frozen=True)
class Change:
    at: datetime
    before: str | None
    after: str | None
    first_assignment: bool
    event_id: str


def close_events(reader, lead_id, object_type, *, action=None):
    filters = {'lead_id': lead_id, 'object_type': object_type, '_limit': 50}
    if action:
        filters['action'] = action
    cursors = set()
    records = {}
    while True:
        page = reader.get('event/', filters)
        for event in page['data']:
            if event.get('lead_id') != lead_id or event.get('object_type') != object_type:
                raise ValueError('Close returned an event outside the requested lead or activity type')
            event_id = event['id']
            if event_id in records and records[event_id] != event:
                raise ValueError('Close returned conflicting versions of the same event')
            records[event_id] = event
        next_cursor = page.get('cursor_next')
        if not next_cursor:
            return list(records.values())
        if next_cursor in cursors:
            raise ValueError('Close event pagination returned a repeated cursor')
        cursors.add(next_cursor)
        filters['_cursor'] = next_cursor


def field(image, name):
    if name in image:
        return image[name]
    if name.startswith('custom.'):
        return (image.get('custom') or {}).get(name.removeprefix('custom.'))
    return None


def event_time(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).astimezone(timezone.utc)


def revisions(events, name, *, before=None):
    for event in events:
        created = event_time(event.get('date_created'))
        updated = event_time(event.get('date_updated'))
        if not created or not updated or (before is not None and updated >= before):
            continue
        if name not in (event.get('changed_fields') or ()):
            continue
        previous, after = event.get('previous_data'), event.get('data')
        if not isinstance(previous, dict) or not isinstance(after, dict):
            continue
        old, new = field(previous, name), field(after, name)
        if old != new:
            yield created, updated, old, new, event['id'], previous, after


def user_identity(value):
    if isinstance(value, list):
        if len(value) != 1:
            return None
        value = value[0]
    if isinstance(value, dict):
        value = value.get('id')
    return value if isinstance(value, str) and value.startswith('user_') else None


def owner_changes(events, owner_field, cutoff):
    changes = {}
    for created, updated, old, new, event_id, _, _ in revisions(events, owner_field, before=cutoff):
        before, after = user_identity(old), user_identity(new)
        if before == after:
            continue
        # A consolidated event identifies the interval, but cannot date an
        # ownership change within it unless the booking is outside that interval.
        at = updated
        if at in changes and changes[at][:2] != (before, after):
            return ()
        changes[at] = before, after, event_id
    result = []
    prior = None
    saw_previous = False
    for at, (before, after, event_id) in sorted(changes.items()):
        if result and before != prior:
            return ()
        first = before is None and not saw_previous
        result.append(Change(at, before, after, first, event_id))
        prior = after
        saw_previous = saw_previous or before is not None or after is not None
    return tuple(result)


def booking_offer(events, offer_field, current, booked):
    """Recover the funnel at booking time from linked Close field revisions."""
    result = current
    for created, updated, old, new, _, _, _ in sorted(
            revisions(events, offer_field), key=lambda item: item[1], reverse=True):
        if result != new:
            continue
        if created <= booked <= updated:
            return current
        if booked < created:
            result = old
    return result


def match_close_transition(meetings, at, parse_time):
    matches = []
    for row in meetings:
        created = parse_time(row.get('date_created'))
        if created and timedelta(0) < created - at <= TRANSFER_WINDOW:
            matches.append(row['id'])
    return matches[0] if len(matches) == 1 else None


def booking_transitions(events, history, owner_field, statuses, parse_time, cutoff, *, periods=()):
    handoffs = {}
    rescheduled = set()
    conflicts = set()
    for created, updated, before, after, event_id, previous, current in revisions(
            events, 'status_id', before=cutoff):
        label = current.get('status_label') or statuses.get(after, '')
        if not label.endswith('Call Booked'):
            continue
        meeting = match_close_transition(history, updated, parse_time)
        if not meeting:
            continue
        if meeting in handoffs:
            conflicts.add(meeting)
        handoffs[meeting] = user_identity(field(previous, owner_field)), user_identity(field(current, owner_field)), event_id
        if RESCHEDULE_STATUS.search(previous.get('status_label') or statuses.get(before, '')):
            rescheduled.add(meeting)
    for meeting in conflicts:
        handoffs.pop(meeting, None)
        rescheduled.discard(meeting)
    # A setter can route a lead that is already in Call Booked. Use the
    # owner revision only when it ends a verified reassignment period.
    reassignments = {current.event_id: previous for previous, current in zip(periods, periods[1:])
                     if previous.after and not previous.first_assignment}
    owner_handoffs = {}
    for created, updated, old, new, event_id, previous, current in revisions(events, owner_field, before=cutoff):
        period = reassignments.get(event_id)
        if period is None or not period.at < created <= updated:
            continue
        before, after = user_identity(old), user_identity(new)
        status = current.get('status_label') or statuses.get(current.get('status_id'), '')
        if before != period.after or not after or before == after or not status.endswith('Call Booked'):
            continue
        if field(previous, 'status_id') not in (None, field(current, 'status_id')):
            continue
        old_status = previous.get('status_label')
        if old_status and old_status != status:
            continue
        meeting = match_close_transition(history, updated, parse_time)
        if meeting is None or meeting in handoffs or meeting in conflicts:
            continue
        if meeting in owner_handoffs:
            conflicts.add(meeting)
        owner_handoffs[meeting] = before, after, event_id
    handoffs.update((meeting, proof) for meeting, proof in owner_handoffs.items() if meeting not in conflicts)
    return handoffs, rescheduled


def booked_period(events, booked, meeting_id, handoffs, setter, closer):
    index = bisect_left([event.at for event in events], booked)
    if not index or (index < len(events) and events[index].at == booked):
        return None
    before, after, proof = handoffs.get(meeting_id, (None, None, None))
    if (setter and closer and before == setter and after == closer
            and events[index - 1].event_id == proof):
        index -= 1
    return events[index - 1] if index else None


@dataclass
class BookingHistory:
    events: dict
    owner_field: str
    offer_field: str
    statuses: dict
    users: dict
    as_of: datetime
    parse_time: object

    def offer_at_booking(self, candidate):
        if candidate['booked_date_pt'] < REASSIGNMENT_START:
            return candidate['business_line']
        records = self.events.get(candidate['lead_id'], ())
        return booking_offer(records, self.offer_field, candidate['business_line'],
                             self.parse_time(candidate['booked_at']))

    def _setter_id(self, label):
        matches = [user for user, name in self.users.items() if name == label]
        return matches[0] if len(matches) == 1 else None

    def apply_reassignments(self, rows, history, counted, cutoff, *, reader, rules, calendar_keys):
        """Repeat suppression resets only on a proven change to the booking setter."""
        selected = {row['meeting_id']: row for row in counted}
        raw_by_lead = defaultdict(list)
        for meeting in history:
            created = self.parse_time(meeting.get('date_created'))
            if created and created < cutoff and self.parse_time(meeting.get('starts_at')):
                raw_by_lead[meeting['lead_id']].append(meeting)
        for row in rows:
            meeting_id = row['meeting_id']
            if (meeting_id in selected or row['bucket'] not in CREDIT_BUCKETS
                    or row['booked_date_pt'] < REASSIGNMENT_START
                    or not vp_business_line(row['business_line'])):
                continue
            records = self.events.get(row['lead_id'], ())
            periods = owner_changes(records, self.owner_field, self.as_of)
            if not periods:
                continue
            history_rows = raw_by_lead[row['lead_id']]
            handoffs, rescheduled = booking_transitions(
                records, history_rows, self.owner_field, self.statuses, self.parse_time, self.as_of, periods=periods)
            if meeting_id in rescheduled:
                if self.verified_replacement(reader, rules, row, history_rows, selected):
                    selected[meeting_id] = row
                continue
            if FOLLOWUP_TITLE.search(row.get('title') or '') or str(row.get('outcome') or '').casefold() == 'rescheduled':
                continue
            by_id = {m['id']: m for m in history_rows}
            current = by_id.get(meeting_id)
            if not current:
                continue
            def key(meeting):
                return self.parse_time(meeting['starts_at']), self.parse_time(meeting['date_created']), meeting['id']
            comparison = key(current)
            prior = [m for m in history_rows if key(m) < comparison
                     and comparison[0] - key(m)[0] <= timedelta(hours=720)]
            if not prior:
                continue
            current_calendar = calendar_keys(current)
            if any(current_calendar & calendar_keys(m) and key(m)[1] < comparison[1] for m in history_rows):
                continue
            setter = self._setter_id(row['setter'])
            period = booked_period(periods, comparison[1], meeting_id, handoffs, setter, row['appointment_closer'])
            if not period or not setter or period.after != setter:
                continue
            predecessor = max(prior, key=key)
            if period.first_assignment:
                before, after, _ = handoffs.get(meeting_id, (None, None, None))
                if (before != setter or after != row['appointment_closer']
                        or predecessor.get('user_id') in (None, setter) or key(predecessor)[1] >= period.at):
                    continue
            if any(booked_period(periods, key(m)[1], m['id'], handoffs, None, None) == period for m in prior):
                continue
            selected[meeting_id] = row
        return list(selected.values())

    def verified_replacement(self, reader, rules, candidate, history, selected):
        key = activity_digest(candidate['meeting_id'])
        review = next((row for row in rules.get('reviewed_vp_replacements', ())
                       if row['activity_id_sha256'] == key), None)
        if review is None:
            return False
        predecessor = next((row for row in history
                            if activity_digest(row['id']) == review['previous_activity_id_sha256']), None)
        if not predecessor:
            return False
        original = self.parse_time(predecessor['date_created'])
        booked = self.parse_time(candidate['booked_at'])
        scheduled = self.parse_time(candidate['starts_at'])
        if not original < booked or not predecessor.get('user_id'):
            return False
        # Preserve a prior credit in the same 720-hour scheduled episode.
        for row in selected.values():
            if (row['lead_id'] == candidate['lead_id'] and row['bucket'] in CREDIT_BUCKETS
                    and abs(self.parse_time(row['starts_at']) - scheduled) <= timedelta(hours=720)):
                return False
        setter = self._setter_id(candidate['setter'])
        if setter is None:
            return False
        lead_id = candidate['lead_id']
        sms = close_events(reader, lead_id, 'activity.sms', action='sent')
        calls = close_events(reader, lead_id, 'activity.call', action='completed')
        expected = [(sms, 'handoff_sms_sha256', predecessor['user_id'], 'sent'),
                    (calls, 'booking_call_sha256', setter, 'completed'),
                    (sms, 'confirmation_sms_sha256', setter, 'sent')]
        matched = []
        for events, field_key, who, status in expected:
            proof = next((event for event in events
                          if activity_digest(event['object_id']) == review[field_key]), None)
            if not proof:
                return False
            detail = proof.get('data') or {}
            when = event_time(proof['date_created'])
            if (not when or when >= self.as_of or not detail.get('contact_id') or
                    detail.get('user_id') != who or detail.get('direction') != 'outbound'
                    or detail.get('status') != status):
                return False
            matched.append((when, detail['contact_id']))
        (handoff_at, _), (call_at, _), (confirmation_at, _) = matched
        return (len({contact for _, contact in matched}) == 1
                and handoff_at < booked < confirmation_at
                and handoff_at < call_at < confirmation_at)


def activity_digest(activity_id):
    return sha256(activity_id.encode()).hexdigest()


def reviewed_booking_date(rules, activity_id, close_booked_at, parse_time):
    proof = rules.get('reviewed_vp_booking_dates', {}).get(activity_digest(activity_id))
    if proof is None:
        return close_booked_at
    observed = parse_time(proof['update_date_created'])
    original = parse_time(proof['original_booked_at'])
    if observed != close_booked_at or not original or original >= observed or not proof.get('review_sha256'):
        return close_booked_at
    return original


def active_history(reader, candidate_rows, initially_counted, users, rules, owner_field, cutoff, parse_time):
    owner_field = 'custom.' + owner_field
    present = {row['meeting_id'] for row in initially_counted}
    leads = {row['lead_id'] for row in candidate_rows if row['bucket'] in CREDIT_BUCKETS
             and row['booked_date_pt'] >= REASSIGNMENT_START and
             (row['meeting_id'] not in present or not vp_business_line(row['business_line']))}
    requires_events = getattr(reader, 'lead_booking_events', None)
    if not leads or requires_events is None:
        return BookingHistory({}, owner_field, 'custom.' + rules['lead_fields']['offer'], {}, users, cutoff, parse_time)
    with ThreadPoolExecutor(max_workers=3) as pool:
        events = dict(zip(sorted(leads), pool.map(requires_events, sorted(leads))))
    statuses = {row['id']: row.get('label', '') for row in reader.pages('status/lead/')}
    return BookingHistory(events, owner_field, 'custom.' + rules['lead_fields']['offer'],
                          statuses, users, cutoff, parse_time)
