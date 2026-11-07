"""Aggregate-only MTD presentation overlay for the agreed outcome cohort."""
from outcome_core import *

def mtd_public_candidate(reference,scheduled):
    """Swap only scheduled-derived metrics on the original public aggregate tree."""
    data=copy.deepcopy(reference);rows=scheduled['rows']
    def apply(group,matching):group.update(rollup(matching))
    apply(data['totals'],rows)
    existing={c['channel']:c for c in data['channels']}
    for channel in sorted({r['channel'] for r in rows}-existing.keys()):
        empty=dict.fromkeys(('leads_created','bookings','marketing','lane2','social_dms','showed','qualified','closed_won','revenue','unrecoverable_booked_leads'),0)
        new={'channel':channel,**empty,'drilldowns':[],'packages':[],'setters':[]};data['channels'].append(new);existing[channel]=new
    for channel in data['channels']:
        channel_rows=[r for r in rows if r['channel']==channel['channel']];apply(channel,channel_rows)
        for kind,key in [('drilldowns','utm_content' if channel['channel']=='Internal Webinar' else 'utm_campaign'),('setters','setter')]:
            children=channel[kind];present={r['value'] for r in children}
            for value in sorted({r[key] for r in channel_rows}-present):children.append({'value':value,**dict.fromkeys(aggregates.METRICS,0)})
            for child in children:apply(child,[r for r in channel_rows if r[key]==child['value']])
    for kind,key in [('team','owner'),('setters','setter')]:
        children=data[kind];present={r['value'] for r in children}
        for value in sorted({r[key] for r in rows}-present):children.append({'value':value,**dict.fromkeys(aggregates.METRICS,0)})
        for child in children:apply(child,[r for r in rows if r[key]==child['value']])
    data['scheduled_outcome_basis']=scheduled['placement']
    data['qualification_evidence']='Current lead flag; the separate reset automation has not been applied'
    from reporting import presentation
    data=presentation(data)
    def format_show(row):
        denominator=row.get('scheduled_calls',0)
        row.setdefault('formats',{})['show']=f"{100*row['showed']/denominator:.1f}%" if denominator else '—'
    for row in [data['totals'],*data['channels'],*data['team'],*data['setters']]:format_show(row)
    for channel in data['channels']:
        for row in channel['drilldowns']+channel['setters']:format_show(row)
    return data

def apply_occurred_mtd(reference, occurred, scheduled):
    # Reuse the existing aggregate-tree placement so source, setter and owner attribution
    # stay identical; replace rate denominators explicitly after that placement.
    # Seed owners/channels that have only unresolved elapsed calls as well, so their
    # separate unresolved counts reconcile without inventing an occurred call.
    data = mtd_public_candidate(mtd_public_candidate(reference, scheduled), occurred)
    def apply(group, elapsed, resolved):
        group.update(occurred_calls=len(resolved), no_shows=sum(occurred_kind(r) == 'no_show' for r in resolved),
                     scheduled_calls=len(elapsed), unresolved_calls=len(elapsed) - len(resolved))
        formats = group.setdefault('formats', {})
        for key, value in [('show', group['showed']), ('qualified', group['qualified']), ('close', group['closed_won'])]:
            formats[key] = f'{100 * value / len(resolved):.1f}%' if resolved else '—'
        formats['qualified_occurred'] = formats['qualified']
        # Keep unrelated native revenue/AOV values and avoid obsolete cohort labels.
        formats.pop('qualified_booked', None)
        formats.pop('qualified_close', None)
    apply(data['totals'], scheduled['rows'], occurred['rows'])
    for channel in data['channels']:
        elapsed = [r for r in scheduled['rows'] if r['channel'] == channel['channel']]
        resolved = [r for r in occurred['rows'] if r['channel'] == channel['channel']]
        apply(channel, elapsed, resolved)
        for kind, key in [('drilldowns', 'utm_content' if channel['channel'] == 'Internal Webinar' else 'utm_campaign'), ('setters', 'setter')]:
            for child in channel[kind]:
                apply(child, [r for r in elapsed if r[key] == child['value']], [r for r in resolved if r[key] == child['value']])
    for kind, key in [('team', 'owner'), ('setters', 'setter')]:
        for child in data[kind]:
            apply(child, [r for r in scheduled['rows'] if r[key] == child['value']], [r for r in occurred['rows'] if r[key] == child['value']])
    data['occurred_basis'] = occurred['placement']
    data['closed_won_basis'] = 'Native date_won in reporting period; no booking or scheduled-call join'
    return data
