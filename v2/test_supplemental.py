"""Original history stays immutable, visibly attributed, and separate from V2."""

import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

from archive_ui import BASE, PICKER_SCRIPT, write_navigation
from reporting import ROOT
from supplemental import retain_history


def v2_navigation():
    month = json.loads((ROOT/'archives/data-2026-10.json').read_text())['view']
    week = json.loads((ROOT/'archives/data-week-2026-09-28.json').read_text())['view']
    return dict(months=[dict(month, live=True)], weeks=[week])


class SupplementalTests(unittest.TestCase):
    def test_original_figures_and_ui_are_preserved_and_snapshots_stay_frozen(self):
        source = ROOT.parent/'archives'
        with tempfile.TemporaryDirectory() as directory:
            archives = Path(directory)
            navigation = retain_history(v2_navigation(), archives)
            history = json.loads((archives/'supplemental/manifest.json').read_text())
            self.assertEqual([row['key'] for row in history['months']],
                             [f'2026-{month:02}' for month in range(1, 10)])
            self.assertTrue(history['weeks'])
            for row in history['months'] + history['weeks']:
                original = (source/f"{row['key']}.html").read_text()
                copied = (archives/f"supplemental/{row['key']}.html").read_text()
                self.assertEqual(row['source_sha256'], hashlib.sha256(original.encode()).hexdigest())
                self.assertEqual(original.split('<style>')[1].split('</style>')[0],
                                 copied.split('<style>')[1].split('</style>')[0])
                # All six KPI tiles, every table row and CSV calculation remain byte-identical.
                self.assertEqual(original.split('<!-- KPI Cards -->')[1].split('<script')[0],
                                 copied.split('<!-- KPI Cards -->')[1].split('<script')[0])
                self.assertEqual(re.findall(r'<script>(.*?)</script>', original, re.S),
                                 re.findall(r'<script>(.*?)</script>', copied, re.S))
                self.assertIn(f'src="{PICKER_SCRIPT}"', copied)
                self.assertIn('Historical · Original MTD rules', copied)
                self.assertNotIn('v2/v2/', copied)
                for href in re.findall(r'(?:href|value)="(/[^"]+)"', copied):
                    self.assertTrue(href.startswith(BASE+'/'), href)
            frozen = (archives/'supplemental/2026-09.html').read_bytes()
            # Refresh never needs to read or recalculate the original source again.
            retain_history(v2_navigation(), archives, source=archives/'missing-source')
            self.assertEqual((archives/'supplemental/2026-09.html').read_bytes(), frozen)
            self.assertEqual(len(navigation['months']), 10)

    def test_week_across_september_and_october_has_separate_routes_and_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            archives = Path(directory)
            navigation = retain_history(v2_navigation(), archives)
            write_navigation(navigation, archives)
            nav = json.loads((archives/'picker-nav.json').read_text())
            september = next(row for row in nav['weeks']['2026-09'] if row['key'] == 'week-2026-09-28')
            october = next(row for row in nav['weeks']['2026-10'] if row['key'] == 'week-2026-09-28')
            self.assertEqual(september['href'], BASE+'/archives/supplemental/week-2026-09-28.html')
            self.assertEqual(october['href'], BASE+'/archives/week-2026-09-28.html')
            self.assertEqual(nav['week_months']['week-2026-09-28'], '2026-10')
            self.assertTrue(all(row['supplemental'] for row in nav['months'] if row['key'] < '2026-10'))
            script = (archives/'picker.js').read_text()
            self.assertIn('(?:supplemental\\/)?', script)
            self.assertIn("if (!path.includes('/supplemental/'))", script)


if __name__ == '__main__':
    unittest.main()
