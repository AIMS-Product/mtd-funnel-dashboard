from datetime import datetime, timedelta, timezone
import unittest

from vp_booking_history import BookingHistory, booked_period, booking_offer, event_time, owner_changes


class VPBookingHistoryTest(unittest.TestCase):
    owner = 'custom.owner'
    offer = 'custom.offer'
    cutoff = datetime(2026, 11, 21, tzinfo=timezone.utc)

    def revision(self, event_id, day, previous, current, changed):
        return dict(id=event_id, date_created=day, date_updated=day,
                    changed_fields=[changed], previous_data={changed: previous}, data={changed: current})

    def test_booking_time_routing_preserves_the_setter_period(self):
        assigned = self.revision('assign', '2026-11-02T08:00:00.000000', 'user_prior', 'user_setter', self.owner)
        close = self.revision('route', '2026-11-03T08:01:00.000000', 'user_setter', 'user_closer', self.owner)
        periods = owner_changes([close, assigned], self.owner, self.cutoff)
        booked = event_time('2026-11-03T08:01:01.000000')
        self.assertEqual(booked_period(periods, booked, 'meeting',
                                      {'meeting': ('user_setter', 'user_closer', 'route')},
                                      'user_setter', 'user_closer').after, 'user_setter')
        self.assertEqual(booked_period(periods, booked, 'meeting', {}, 'user_setter', 'user_closer').after,
                         'user_closer')

    def test_existing_call_booked_status_allows_verified_reassignment_only(self):
        booked = '2026-11-17T23:03:44.551000Z'
        field = self.owner
        assign = self.revision('assign', '2026-11-17T22:54:45Z', 'user_prior', 'user_setter', field)
        route = self.revision('route', '2026-11-17T23:03:37.851000Z', 'user_setter', 'user_closer', field)
        route['date_created'] = '2026-11-17T23:03:37.044000Z'
        route['data']['status_id'] = 'booked'
        prior = {'id': 'prior', 'lead_id': 'lead', 'user_id': 'user_old_closer',
                 'date_created': '2026-10-29T20:19:29Z', 'starts_at': '2026-10-30T19:00:00Z'}
        current = {'id': 'current', 'lead_id': 'lead', 'user_id': 'user_closer',
                   'date_created': booked, 'starts_at': '2026-11-24T20:00:00Z'}
        candidate = {'meeting_id': 'current', 'lead_id': 'lead', 'bucket': 'Lane 2',
                     'business_line': 'Vendingpreneurs (VP)', 'booked_date_pt': '2026-11-17',
                     'setter': 'Setter', 'appointment_closer': 'user_closer', 'title': 'Consultation'}

        def evaluate(*, assignment=assign, handoff=route, earlier=prior, extra=(), **changes):
            policy = BookingHistory({'lead': [handoff, assignment]}, field, self.offer,
                                    {'booked': 'Call Booked'}, {'user_setter': 'Setter'},
                                    self.cutoff, event_time)
            return policy.apply_reassignments([{**candidate, **changes}], [earlier, current, *extra],
                                              [], self.cutoff + timedelta(days=1), reader=None,
                                              rules={}, calendar_keys=lambda meeting: {meeting['id']})

        self.assertEqual(evaluate(), [candidate])
        self.assertEqual(evaluate(earlier={**prior, 'date_created': '2026-11-17T22:59:00Z'}), [])
        self.assertEqual(evaluate(appointment_closer='user_other'), [])
        self.assertEqual(evaluate(title='Consultation Follow-up'), [])
        self.assertEqual(evaluate(outcome='Rescheduled'), [])
        self.assertEqual(evaluate(extra=[{**current, 'id': 'other'}]), [])
        self.assertEqual(evaluate(handoff={**route, 'data': {field: 'user_closer', 'status_id': 'other'}}), [])
        self.assertEqual(evaluate(handoff={**route, 'date_created': '2026-11-17T23:02:00Z',
                                          'date_updated': '2026-11-17T23:02:00Z'}), [])
        self.assertEqual(evaluate(assignment={**assign, 'previous_data': {field: None}}), [])
        self.assertEqual(evaluate(assignment={**assign, 'data': {field: 'user_other'}}), [])

    def test_archived_offer_keeps_sourced_booking_time_scope(self):
        event = self.revision('offer', '2026-11-11T08:00:00.000000', 'Vendingpreneurs (VP)',
                              'The Land Geek (TLG)', self.offer)
        self.assertEqual(booking_offer([event], self.offer, 'The Land Geek (TLG)',
                                       event_time('2026-10-07T08:00:00.000000')), 'Vendingpreneurs (VP)')
        self.assertEqual(booking_offer([event], self.offer, 'The Land Geek (TLG)',
                                       event_time('2026-11-12T08:00:00.000000')), 'The Land Geek (TLG)')

    def test_missing_owner_history_does_not_invent_a_transfer(self):
        first = self.revision('first', '2026-11-02T08:00:00.000000', 'user_prior', 'user_setter', self.owner)
        second = self.revision('second', '2026-11-03T08:01:00.000000', 'user_other', 'user_closer', self.owner)
        self.assertEqual(owner_changes([first, second], self.owner, self.cutoff), ())
