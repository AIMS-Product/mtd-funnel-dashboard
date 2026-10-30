"""Retain original pre-V2 public reports as clearly labeled supplemental history."""

import hashlib
import json
import re
from datetime import date, timedelta

from archive_ui import BASE, picker_html, presentation_namespace
from reporting import ARCHIVE_START, ROOT


def historical_navigation(source):
    """Only import already-published pages before V2's first reporting month."""
    months, weeks = [], []
    for path in sorted(source.glob('*.html')):
        match = re.fullmatch(r'(week-)?(\d{4}-\d{2})(-\d{2})?', path.stem)
        if not match:
            continue
        weekly = bool(match[1])
        start = date.fromisoformat(path.stem.removeprefix('week-') + ('' if weekly else '-01'))
        if start >= ARCHIVE_START:
            continue
        end = start + timedelta(days=7) if weekly else (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        row = dict(key=path.stem, kind='week' if weekly else 'month', month=start.strftime('%Y-%m'),
                   start=start.isoformat(), end=(end-timedelta(days=1)).isoformat(),
                   end_exclusive=end.isoformat(), frozen=True, live=False, supplemental=True,
                   label=start.strftime('%B %Y') + ' (Historical)',
                   href=f'{BASE}/archives/supplemental/{path.name}',
                   source=f'archives/{path.name}',
                   source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        (weeks if weekly else months).append(row)
    return dict(months=months, weeks=weeks)


def retain_history(navigation, directory, source=None):
    """Freeze copies once; later refreshes only update their shared navigation."""
    source = source or ROOT.parent / 'archives'
    destination = directory / 'supplemental'
    destination.mkdir(exist_ok=True)
    manifest_path = destination / 'manifest.json'
    history = json.loads(manifest_path.read_text()) if manifest_path.exists() else historical_navigation(source)
    combined = {kind: sorted(history[kind] + navigation[kind], key=lambda row: row['key'])
                for kind in ('months', 'weeks')}
    ui = presentation_namespace()
    for row in history['months'] + history['weeks']:
        output = destination / f"{row['key']}.html"
        if output.exists():
            continue
        original = (source / f"{row['key']}.html").read_bytes()
        if hashlib.sha256(original).hexdigest() != row['source_sha256']:
            raise ValueError(f"Historical source changed before snapshot restoration: {row['source']}")
        html = original.decode().replace('/mtd-funnel-dashboard/', BASE + '/')
        monthly, weekly = picker_html(dict(view=row, period=row['start']), combined, ui)
        has_week_picker = '<div class="week-picker">' in html
        html = re.sub(r'<div class="month-picker">.*?</select></div>',
                      lambda _: monthly if has_week_picker else monthly + weekly, html, count=1, flags=re.S)
        if has_week_picker:
            html = re.sub(r'<div class="week-picker">.*?</select></div>',
                          lambda _: weekly[weekly.index('<div class="week-picker">'):], html, count=1, flags=re.S)
        html = re.sub(r'(<span class="archive-badge">).*?(</span>)',
                      r'\1Historical · Original MTD rules\2', html, count=1)
        if f'{BASE}/archives/picker.js' not in html:
            html = html.replace('<script>', f'<script src="{BASE}/archives/picker.js"></script>\n<script>', 1)
        output.write_text(html)
    manifest_path.write_text(json.dumps(history, indent=2) + '\n')
    return combined
