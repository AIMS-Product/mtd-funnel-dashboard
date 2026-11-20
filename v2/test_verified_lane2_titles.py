import unittest
import re
import build

TITLES = [('Anastasiya Peralaika', 'Vendingpreneurs', 'Meridian'), ('Kylee Koerner', 'Vendingpreneurs', 'Vista'), ('Spencer Clark', 'Acquisition Ace', 'Forge'), ('Colin McDowell', 'Acquisition Ace', 'Vanguard'), ('Madalina Mastacaneanu', 'Vendingpreneurs', 'Crest')]

class VerifiedLane2TitleTests(unittest.TestCase):
    def test_verified_titles_resolve_once_with_dash_and_attendee_variants(self):
        for name, program, label in TITLES:
            for dash in ('-', '–', '—'):
                for suffix in ('', ' with Test Prospect and Test Closer'):
                    title = f'{program} {label} {dash} Next Steps{suffix}'
                    with self.subTest(title=title):
                        self.assertEqual(build.preliminary_bucket({'title': title}), 'Lane 2')
                        self.assertEqual(build.title_bucket({'title': title}, {})[:2], ('Lane 2', name))
                        matches = [r for r in build.RULES['title_rules'] if re.search(r['pattern'], title, re.I)]
                        self.assertEqual([r['setter_name'] for r in matches], [name])

    def test_unapproved_cross_program_titles_are_not_credited(self):
        for title in ('Vendingpreneurs Forge – Next Steps', 'Acquisition Ace Vista – Next Steps', 'Vendingpreneurs Crestline – Next Steps'):
            self.assertEqual(build.title_bucket({'title': title}, {})[0], '')
