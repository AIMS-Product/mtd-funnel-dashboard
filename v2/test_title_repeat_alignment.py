import unittest
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import build


class TitleRepeatAlignmentTests(unittest.TestCase):
    def test_approved_titles_keep_their_setter_and_allow_attendee_suffixes(self):
        titles = {
            'Adam Linn': 'Vendingpreneurs Apex - Next Steps',
            'Esther Cohen': 'Vendingpreneurs Breakthrough - Next Steps',
            'Claude Shany Toussaint': 'Vendingpreneurs Beacon - Next Steps',
            'Helena Seitz': 'Vendingpreneurs Pathfinder - Next Steps',
            'Andrea Harris': 'Vendingpreneurs Nexus - Next Steps',
            'Angel Rojo': 'Vendingpreneurs Atlas - Next Steps',
            'Ariadna Rufrancos': 'Vendingpreneurs Frontier - Next Steps',
            'Reginald Barnwell': 'Vendingpreneurs Trailblazer - Next Steps',
        }
        for setter, title in titles.items():
            for suffix in ('', ' with Test Prospect and Test Closer'):
                with self.subTest(setter=setter, suffix=suffix):
                    self.assertEqual(build.title_bucket({'title': title + suffix}, {})[:2], ('Lane 2', setter))
        self.assertEqual(build.title_bucket({'title': 'Vendingpreneurs Atlas -   Next Steps with Test Prospect'}, {})[:2], ('Lane 2', 'Angel Rojo'))
        self.assertEqual(build.title_bucket({'title': 'Vendingpreneurs Unknown - Next Steps'}, {})[0], '')

    def rows(self, setter='Naria Torres', created='2026-11-02T15:00:00Z'):
        rule = next(rule for rule in build.RULES['title_rules'] if rule['setter_name'] == setter and not rule.get('retired_at_exclusive'))
        first = dict(id='first', lead_id='lead', date_created=created,
                     starts_at='2026-11-03T15:00:00Z', status='completed')
        later = dict(first, id='later', date_created='2026-11-04T15:00:00Z', starts_at='2026-11-05T15:00:00Z')
        candidates = [dict(meeting_id=meeting['id'], lead_id='lead', bucket='Lane 2',
                           setter=setter, rule=rule['key']) for meeting in (first, later)]
        return candidates, [first, later]

    def test_only_naria_gains_temporal_repeat_credit(self):
        candidates, meetings = self.rows()
        self.assertEqual(len(build.choose_bucket_credits(candidates, meetings, {})[0]), 2)
        for setter in ('Vince Bartolini', 'Adam Linn'):
            candidates, meetings = self.rows(setter)
            self.assertEqual(len(build.choose_bucket_credits(candidates, meetings, {})[0]), 1)

    def test_display_name_alone_cannot_grant_exception(self):
        candidates, meetings = self.rows('Vince Bartolini')
        for candidate in candidates:
            candidate['setter'] = 'Naria Torres'
        self.assertEqual(len(build.choose_bucket_credits(candidates, meetings, {})[0]), 1)

    def test_same_calendar_event_reschedules_still_count_once(self):
        for identity in ({'calendar_event_uids': ['same-event']},
                         {'provider_calendar_event_id': 'same-event', 'provider_calendar_type': 'google'}):
            candidates, meetings = self.rows()
            for meeting in meetings:
                meeting.update(identity)
            self.assertEqual(len(build.choose_bucket_credits(candidates, meetings, {})[0]), 1)

    def test_explicit_followup_does_not_gain_exception_credit(self):
        for suffix in ('Follow up', 'F/U', 'Rescheduled'):
            candidates, meetings = self.rows()
            meetings[1]['title'] = 'Vendingpreneurs Pathway - Next Steps ' + suffix
            self.assertEqual(len(build.choose_bucket_credits(candidates, meetings, {})[0]), 1)

    def test_canceled_original_does_not_block_its_replacement(self):
        candidates, meetings = self.rows()
        for meeting in meetings:
            meeting['calendar_event_uids'] = ['same-event']
        meetings[0]['status'] = 'declined-by-org'
        self.assertEqual([row['meeting_id'] for row in build.choose_bucket_credits(candidates[1:], meetings, {})[0]], ['later'])

    def test_exception_does_not_rewrite_october_or_move_shared_clock(self):
        candidates, meetings = self.rows()
        for meeting in meetings:
            meeting['date_created'] = '2026-10-20T15:00:00Z'
        original = deepcopy(meetings)
        self.assertEqual(len(build.choose_bucket_credits(candidates, meetings, {})[0]), 1)
        self.assertEqual(meetings, original)
        candidates, meetings = self.rows('Vince Bartolini')
        anchor = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)
        for delta, count in ((timedelta(hours=720), 1), (timedelta(hours=720, microseconds=1), 2)):
            meetings[1]['starts_at'] = (anchor + delta).isoformat()
            self.assertEqual(len(build.choose_bucket_credits(candidates, meetings, {})[0]), count)

    def test_malformed_calendar_identity_fails_closed(self):
        candidates, meetings = self.rows()
        meetings[1]['calendar_event_uids'] = 'not-a-list'
        with self.assertRaisesRegex(ValueError, 'calendar identities'):
            build.choose_bucket_credits(candidates, meetings, {})

    def test_title_and_cancellation_checks_remain_required(self):
        self.assertEqual(build.title_bucket({'title': 'Follow up with Test Prospect'}, {})[0], '')
        self.assertTrue(build.cancellation({'status': 'declined-by-lead'}, ''))
        self.assertTrue(build.cancellation({'status': 'completed'}, 'Cancelled'))


if __name__ == '__main__':
    unittest.main()
