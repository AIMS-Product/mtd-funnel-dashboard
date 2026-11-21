from datetime import date, datetime
import unittest

from certified_vp_bookings import align_bookings


class TestCertifiedVPBookings(unittest.TestCase):
    start = date(2026, 11, 1)
    cutoff = datetime.fromisoformat('2026-11-20T13:00:00-08:00')
    candidate = {'meeting_id': 'booking', 'booked_at': '2026-11-17T18:28:27.490000+00:00',
                 'booked_date_pt': '2026-11-17', 'appointment_closer': 'closer', 'bucket': 'Social DMs'}
    corrected = {'activity_id': 'booking', 'booked_day': '2026-11-16', 'appointment_closer': 'closer', 'bucket': 'Lane 2'}

    def test_reviewed_original_booking_can_precede_close_sync_date(self):
        origin = {'close_activity_id': 'booking', 'review_sha256': 'verified',
                  'update_date_created': self.candidate['booked_at'],
                  'original_booked_at': '2026-11-16T21:00:07.956897Z'}
        marketing = {'meeting_id': 'marketing', 'bucket': 'Marketing'}
        result = align_bookings([self.candidate, marketing], [self.candidate], [self.corrected],
                                start=self.start, period_cutoff=self.cutoff, reviewed_origins={'booking': origin})
        self.assertEqual(result[0], marketing)
        self.assertEqual(result[1]['bucket'], 'Lane 2')
        self.assertEqual(result[1]['owner'], 'closer')
        self.assertEqual(result[1]['booked_date_pt'], '2026-11-16')

    def test_rejects_changed_booking_date_without_verified_origin(self):
        with self.assertRaisesRegex(ValueError, 'requires reviewed origin'):
            align_bookings([], [self.candidate], [self.corrected], start=self.start, period_cutoff=self.cutoff)
