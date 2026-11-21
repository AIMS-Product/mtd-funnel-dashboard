from datetime import datetime, timezone
import unittest

from vp_booking_history import booked_period, booking_offer, event_time, owner_changes


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
