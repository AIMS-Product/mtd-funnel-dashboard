"""Feed V2 aggregates to the current MTD's exact, unchanged presentation code."""

from __future__ import annotations

import ast
import calendar
import json
import re
import warnings
from datetime import date, datetime, timedelta
from html import escape
from pathlib import Path

from reporting import PACIFIC, ROOT

BASE = '/mtd-funnel-dashboard/v2'
PICKER_SCRIPT = BASE + '/archives/picker.js?v=supplemental-1'
FUNCTIONS = {
    'pct', 'pct_class', 'fmt_currency', 'rev_per_close', 'funnel_slug',
    'calc_on_pace', 'pace_class', 'pace_label', 'goal_pct_label', 'goal_pct_corner',
    'build_funnel_rows', 'generate_html', 'week_display_label', 'write_picker_js',
}
CONSTANTS = {'FUNNEL_GROUPS', 'EXCLUDED_FROM_TOTALS_FUNNELS', 'MONTHLY_BOOKED_GOAL', 'MONTHLY_REVENUE_GOAL'}


def presentation_namespace():
    """Load only pure UI functions/constants; legacy fetching code is never executed."""
    source = ROOT.parent / 'fetch_and_build.py'
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', category=SyntaxWarning, message='.*invalid escape sequence.*')
        tree = ast.parse(source.read_text())
    namespace = dict(calendar=calendar, re=re, json=json, datetime=datetime,
                     date=date, timedelta=timedelta, Path=Path, PACIFIC=PACIFIC)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in CONSTANTS:
                    namespace[target.id] = ast.literal_eval(node.value)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in FUNCTIONS]
    if {node.name for node in functions} != FUNCTIONS:
        raise ValueError('The current MTD presentation contract changed')
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec'), namespace)
    return namespace


def legacy_metrics(row):
    return {key: row.get(key, 0) for key in ('leads_created', 'showed', 'qualified', 'revenue')} | {
        'booked': row['bookings'], 'closed': row['closed_won'],
    }


def adapter(data, ui):
    view = data.get('view') or dict(kind='month', start=data['period'].split(' through ')[0], frozen=False)
    start = date.fromisoformat(view['start'])
    label = start.strftime('%B %Y')
    if view['kind'] == 'week':
        end = date.fromisoformat(view['end_exclusive']) - timedelta(days=1)
        label += ' · ' + ui['week_display_label'](start, end)
    totals, details, packages = {}, {}, {}
    for channel in data['channels']:
        name = escape(channel['channel'])
        totals[name] = legacy_metrics(channel)
        children = {escape(row['value']): legacy_metrics(row) for row in channel['drilldowns']}
        # Setter rows use the same existing expansion and row styling as campaigns.
        for row in channel.get('setters', []):
            if row['lane2'] or row['social_dms']:
                children[escape('Setter · ' + row['value'])] = legacy_metrics(row)
        details[name] = children
        packages[name] = {escape(row['value']): {'count': row['closed_won'], 'revenue': row['revenue']} for row in channel['packages']}
    # Preserve the current UI's empty excluded row without excluding any V2 credit.
    ui['EXCLUDED_FROM_TOTALS_FUNNELS'] = {
        name for name in ui['EXCLUDED_FROM_TOTALS_FUNNELS']
        if not totals.get(name, {}).get('booked') and not totals.get(name, {}).get('closed')
    }
    ui['MONTHLY_BOOKED_GOAL'] = data['goals']['bookings']
    ui['MONTHLY_REVENUE_GOAL'] = data['goals']['revenue']
    progress = data['progress']
    return {
        'grand': legacy_metrics(data['totals']), 'group_totals': {},
        'funnel_totals': totals, 'funnel_data': details, 'tier_by_funnel': packages,
        'goals': {escape(name): goal for name, goal in data['goals']['channels'].items()},
        'vendhub_revenue': data['vendhub_arr'], 'month_label': label,
        'generated_at': datetime.fromisoformat(data['generated_at']).astimezone(PACIFIC).strftime('%B %d, %Y at %I:%M %p PT'),
        'day_of_month': progress['day'], 'days_in_month': progress['days'],
        'working_days_elapsed': progress['working_elapsed'], 'working_days_in_month': progress['working_days'],
        'badge_html': '<span class="archive-badge">Week View</span>' if view['kind'] == 'week' else '<span class="archive-badge">Archive</span>' if view['frozen'] else '',
    }


def month_href(row):
    return row.get('href') or (BASE + '/index.html' if row.get('live') else f"{BASE}/archives/{row['key']}.html")


def week_href(row):
    return row.get('href') or f"{BASE}/archives/{row['key']}.html"


def weeks_for_month(navigation, month):
    return [week for week in reversed(navigation['weeks'])
            if bool(week.get('supplemental')) == bool(month.get('supplemental'))
            and (week['month'] == month['key'] if month.get('supplemental')
                 else week['start'][:7] <= month['key'] <= week['end'][:7])]


def picker_html(data, navigation, ui):
    view = data.get('view', {})
    month = view.get('month', data['period'][:7])
    options = []
    for row in reversed(navigation['months']):
        options.append(f'<option value="{month_href(row)}" {"selected" if row["key"] == month else ""}>{escape(row["label"])}</option>')
    monthly = '<div class="month-picker"><select onchange="window.location.href=this.value">' + ''.join(options) + '</select></div>'
    selected_month = next((row for row in navigation['months'] if row['key'] == month), dict(key=month, live=True))
    weeks = [f'<option value="{month_href(selected_month)}">Full Month</option>']
    for row in weeks_for_month(navigation, selected_month):
        label = ui['week_display_label'](date.fromisoformat(row['start']), date.fromisoformat(row['end_exclusive']) - timedelta(days=1))
        weeks.append(f'<option value="{week_href(row)}" {"selected" if view.get("key") == row["key"] else ""}>{label}</option>')
    weekly = '<span class="picker-divider">|</span><div class="week-picker"><select onchange="window.location.href=this.value">' + ''.join(weeks) + '</select></div>'
    return monthly, weekly


def render_current_ui(data, output, navigation):
    ui = presentation_namespace()
    adapted = adapter(data, ui)
    month_picker, week_picker = picker_html(data, navigation, ui)
    html = re.sub(r'/mtd-funnel-dashboard/(?!v2/)', BASE + '/', ui['generate_html'](adapted, month_picker, week_picker))
    return html.replace(f'src="{BASE}/archives/picker.js"', f'src="{PICKER_SCRIPT}"')


def write_navigation(navigation, directory):
    ui = presentation_namespace()
    live = next((month for month in navigation['months'] if month.get('live')), None)
    weeks = {}
    for month in navigation['months']:
        entries = []
        for week in weeks_for_month(navigation, month):
            label = ui['week_display_label'](date.fromisoformat(week['start']), date.fromisoformat(week['end_exclusive']) - timedelta(days=1))
            entries.append(dict(key=week['key'], label=label, is_current=False, href=week_href(week)))
        for week in navigation['weeks']:
            if not week['frozen'] and month.get('live'):
                entries.append(dict(key='week-current', label=ui['week_display_label'](date.fromisoformat(week['start']), date.fromisoformat(week['end'])) + ' ▶', is_current=True))
        weeks[month['key']] = entries
    nav = dict(live_month=live['key'] if live else '', live_month_label=live['label'] if live else '',
               months=[dict(key=m['key'], label=m['label'], is_live=m.get('live', False), href=month_href(m), supplemental=m.get('supplemental', False)) for m in reversed(navigation['months'])], weeks=weeks,
               week_months={week['key']: week['month'] for week in navigation['weeks'] if not week.get('supplemental')})
    (directory/'picker-nav.json').write_text(json.dumps(nav, indent=2)+'\n')
    ui['ARCHIVES_DIR'] = directory
    ui['write_picker_js']()
    path = directory/'picker.js'
    script = path.read_text().replace("'/mtd-funnel-dashboard'", repr(BASE)).replace('/archives/nav.json', '/archives/picker-nav.json')
    script = script.replace(r'archives\/', r'archives\/(?:supplemental\/)?')
    script = script.replace('// Month picker —', "if (!path.includes('/supplemental/')) curMonth = nav.week_months[curWeek] || curMonth;\n\n    // Month picker —")
    script = script.replace("m.is_live ? BASE+'/index.html' : BASE+'/archives/'+m.key+'.html'", "m.href || (m.is_live ? BASE+'/index.html' : BASE+'/archives/'+m.key+'.html')")
    script = script.replace("isLive ? BASE+'/index.html' : BASE+'/archives/'+curMonth+'.html'", "(nav.months.find(m => m.key === curMonth) || {}).href || (isLive ? BASE+'/index.html' : BASE+'/archives/'+curMonth+'.html')")
    script = script.replace("${BASE+'/archives/'+w.key+'.html'}", "${w.href || BASE+'/archives/'+w.key+'.html'}")
    path.write_text(script)


def write_current_comparison(reports, path):
    for report in reports:
        if report['view']['kind'] != 'month':
            continue
        funnels = {}
        for row in report['channels']:
            metrics = legacy_metrics(row)
            metrics.update(
                show_pct=round(100 * row['showed'] / row['bookings'], 1) if row['bookings'] else None,
                qual_pct=round(100 * row['qualified'] / row['showed'], 1) if row['showed'] else None,
                cw_pct=round(100 * row['closed_won'] / row['bookings'], 1) if row['bookings'] else None,
                revenue=round(row['revenue']),
            )
            funnels[escape(row['channel'])] = metrics
        grand = legacy_metrics(report['totals'])
        grand['revenue'] = round(grand['revenue'])
        payload = dict(month_key=report['view']['key'], grand=grand, funnels=funnels)
        (path.parent/f"comparison-data-{report['view']['key']}.json").write_text(json.dumps(payload, indent=2)+'\n')
    html = (ROOT.parent/'archives/mom.html').read_text()
    html = html.replace('/mtd-funnel-dashboard', BASE).replace('/archives/nav.json', '/archives/picker-nav.json')
    html = html.replace('`data-${', '`comparison-data-${')
    html = html.replace('filter(m => !m.is_live)', 'filter(m => !m.is_live && !m.supplemental)')
    # Keep V2's qualified/showed definition in the TOTAL row as well as source rows.
    html = html.replace('g && bo ? g.qualified / bo * 100 : null', 'g && g.showed ? g.qualified / g.showed * 100 : null')
    html = html.replace('</body>', '<!-- V2 booking and attribution rules; original MTD comparison UI. -->\n</body>')
    path.write_text(html)
