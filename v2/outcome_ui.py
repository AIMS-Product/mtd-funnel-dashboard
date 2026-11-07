"""Reviewed Calls Occurred presentation using the existing MTD visual design.

Loaded as pure functions by archive_ui; legacy frozen reports use the original UI.
"""

def build_funnel_rows(funnel_data, funnel_totals, goals=None, day_of_month=1, days_in_month=30, tier_by_funnel=None):
    """Build <tr> HTML for each funnel and its UTM sub-rows, grouped by section."""
    all_funnels = set(funnel_data.keys())
    claimed     = set()
    rows        = []

    def funnel_row_html(funnel):
        t   = funnel_totals.get(funnel, {})
        bo  = t.get("booked", 0)
        # Zero suppression — hide rows with no activity (always show excluded funnels)
        if bo == 0 and t.get("occurred", 0) == 0 and t.get("unresolved", 0) == 0 and t.get("closed", 0) == 0 and funnel not in EXCLUDED_FROM_TOTALS_FUNNELS:
            return []
        sh  = t.get("showed", 0)
        qu  = t.get("qualified", 0)
        cl  = t.get("closed", 0)
        rev = t.get("revenue", 0.0)
        fid = funnel_slug(funnel)

        _goals      = goals or {}
        _goal       = _goals.get(funnel)
        _on_pace    = calc_on_pace(bo, _goal, day_of_month, days_in_month)
        _pc         = pace_class(bo, _on_pace, _goal)
        _is_excl    = funnel in EXCLUDED_FROM_TOTALS_FUNNELS
        _row_class  = "funnel-row funnel-row-excluded" if _is_excl else "funnel-row"
        _excl_note  = " *" if _is_excl else ""
        lc          = t.get("leads_created", 0)
        lc_disp     = lc if lc else "—"


        html = [f"""
    <tr class="{_row_class}" onclick="toggleUTM('{fid}')" data-fid="{fid}">
      <td class="col-name">
        <span class="chevron" id="chev-{fid}">›</span>{funnel}{_excl_note}
      </td>
      <td class="col-num">{lc_disp}</td>
      <td class="col-num">{bo if bo else "—"}</td>
      <td class="col-pace {_pc}">{pace_label(bo, _on_pace, _goal)}</td>
      <td class="col-goal">{goal_pct_label(bo, _goal)}</td>
      <td class="col-num">{t.get("occurred", 0)}</td>
      <td class="col-num">{sh if sh else "—"}</td>
      <td class="col-pct {pct_class(sh, t.get("occurred", 0))}">{pct(sh, t.get("occurred", 0))}</td>
      <td class="col-num">{qu if qu else "—"}</td>
      <td class="col-pct {pct_class(qu, t.get("occurred", 0))}">{pct(qu, t.get("occurred", 0))}</td>
      <td class="col-num">{cl if cl else "—"}</td>
      <td class="col-pct {pct_class(cl, t.get("occurred", 0), high=0.15, low=0.07)}">{pct(cl, t.get("occurred", 0))}</td>
      <td class="col-rev pkg-trigger" onclick="event.stopPropagation();togglePkg('{fid}')" title="Click to see package breakdown">{fmt_currency(rev)} <span class="pkg-chevron" id="pkgchev-{fid}">›</span></td>
      <td class="col-num">{rev_per_close(rev, cl)}</td>
    </tr>"""]

        # Package/tier sub-rows
        tiers = (tier_by_funnel or {}).get(funnel, {})
        for tier_name, tvals in sorted(tiers.items(), key=lambda x: -x[1]["revenue"]):
            tc  = tvals["count"]
            tr_ = tvals["revenue"]
            html.append(f"""
    <tr class="pkg-row" data-parent="{fid}" style="display:none">
      <td class="col-name col-pkg">↳ {tier_name}</td>
      <td class="col-num">—</td>
      <td class="col-num">—</td>
      <td class="col-pace"></td>
      <td class="col-goal"></td>
      <td class="col-num">—</td>
      <td class="col-num">—</td>
      <td class="col-pct"></td>
      <td class="col-num">—</td>
      <td class="col-pct"></td>
      <td class="col-num">{tc}</td>
      <td class="col-pct"></td>
      <td class="col-rev">{fmt_currency(tr_)}</td>
      <td class="col-num">{rev_per_close(tr_, tc)}</td>
    </tr>""")

        utms = funnel_data.get(funnel, {})
        for utm_label, vals in sorted(utms.items(), key=lambda x: -x[1]["booked"]):
            b  = vals["booked"]
            s  = vals["showed"]
            q  = vals["qualified"]
            c  = vals["closed"]
            r  = vals["revenue"]
            html.append(f"""
    <tr class="utm-row" data-parent="{fid}">
      <td class="col-name col-utm">↳ {utm_label}</td>
      <td class="col-num">—</td>
      <td class="col-num">{b if b else "—"}</td>
      <td class="col-pace"></td>
      <td class="col-goal"></td>
      <td class="col-num">{vals.get("occurred", 0)}</td>
      <td class="col-num">{s if s else "—"}</td>
      <td class="col-pct {pct_class(s, vals.get("occurred", 0))}">{pct(s, vals.get("occurred", 0))}</td>
      <td class="col-num">{q if q else "—"}</td>
      <td class="col-pct {pct_class(q, vals.get("occurred", 0))}">{pct(q, vals.get("occurred", 0))}</td>
      <td class="col-num">{c if c else "—"}</td>
      <td class="col-pct {pct_class(c, vals.get("occurred", 0), high=0.15, low=0.07)}">{pct(c, vals.get("occurred", 0))}</td>
      <td class="col-rev">{fmt_currency(r)}</td>
      <td class="col-num">{rev_per_close(r, c)}</td>
    </tr>""")
        return html

    # ── Grouped sections ──────────────────────────────────────────────────────
    for group_label, group_funnels in FUNNEL_GROUPS:
        # Only emit a section header if at least one funnel in this group has data
        # (or is in the defined list — always show defined funnels for consistency)
        grp_id = group_label.lower().replace(" ", "_").replace("-", "_")
        rows.append(f"""
    <tr class="section-header-row" onclick="toggleSection('{grp_id}')">
      <td colspan="14">
        <span class="section-chevron open" id="secchev-{grp_id}">›</span>FUNNEL BREAKDOWN — {group_label}
      </td>
    </tr>""")

        for funnel in group_funnels:
            claimed.add(funnel)
            # Always render the row even if no data (shows — across the board)
            # Tag each row with the section group so we can collapse the whole section
            section_rows = funnel_row_html(funnel)
            # Inject data-section attribute into first <tr> of each funnel block
            section_rows = [r.replace('<tr class="funnel-row"', f'<tr class="funnel-row" data-section="{grp_id}"', 1) for r in section_rows]
            rows.extend(section_rows)

    # ── Any funnels not in any group (safety net) ─────────────────────────────
    extras = sorted(all_funnels - claimed)
    if extras:
        rows.append(f"""
    <tr class="section-header-row" onclick="toggleSection('other')">
      <td colspan="14">
        <span class="section-chevron open" id="secchev-other">›</span>FUNNEL BREAKDOWN — OTHER
      </td>
    </tr>""")
        for funnel in extras:
            section_rows = funnel_row_html(funnel)
            section_rows = [r.replace('<tr class="funnel-row"', '<tr class="funnel-row" data-section="other"', 1) for r in section_rows]
            rows.extend(section_rows)

    return "\n".join(rows)

def generate_html(data, month_picker_html="", week_picker_html=""):
    grand       = data["grand"]
    gt          = data["group_totals"]
    ext         = gt.get("EXTERNAL",     {"booked":0,"showed":0,"qualified":0,"closed":0,"revenue":0.0})
    inh         = gt.get("IN-HOUSE",     {"booked":0,"showed":0,"qualified":0,"closed":0,"revenue":0.0})
    goals        = data.get("goals", {})
    day_of_month = data.get("day_of_month", 1)
    days_in_month= data.get("days_in_month", 30)
    tier_by_funnel = data.get("tier_by_funnel", {})
    funnel_rows  = build_funnel_rows(data["funnel_data"], data["funnel_totals"],
                                     goals, day_of_month, days_in_month,
                                     tier_by_funnel)

    g_lc      = grand.get("leads_created", 0)
    g_vh_rev  = data.get("vendhub_revenue", 0.0)
    day_num   = data.get("day_of_month",  1)
    days_tot  = data.get("days_in_month", 30)
    wd_num    = data.get("working_days_elapsed",  0)
    wd_tot    = data.get("working_days_in_month", 0)
    pct_month = round(wd_num / wd_tot * 100, 1) if wd_tot else 0
    g_bo  = grand["booked"]
    g_sh  = grand["showed"]
    g_qu  = grand["qualified"]
    g_cl  = grand["closed"]
    g_rev = grand["revenue"]

    _csv_slug = re.sub(r"[^a-z0-9]+", "-", data['month_label'].lower()).strip("-")
    if data.get('week_range_label'):
        _csv_slug += "-week"
    csv_filename = f"mtd-funnel-{_csv_slug}.csv"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>MTD Funnel Performance — {data['month_label']}</title>
<style>
  :root {{
    --bg:        #f4f6f9;
    --surface:   #ffffff;
    --surface2:  #f0f2f7;
    --border:    #dde1ea;
    --border2:   #e8eaf0;
    --text:      #1a1f36;
    --muted:     #8792a2;
    --muted2:    #5c6680;
    --green:     #0e9f6e;
    --green-dim: #0e9f6e20;
    --red:       #e02424;
    --red-dim:   #e0242420;
    --amber:     #d97706;
    --blue:      #2563eb;
    --purple:    #7c3aed;
    --accent:    #4f46e5;
  }}

  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, sans-serif;
    font-size: 13px;
    min-height: 100vh;
  }}

  /* Light mode card shadow */
  .kpi {{
    box-shadow: 0 1px 3px rgba(0,0,0,0.07), 0 1px 2px rgba(0,0,0,0.04);
  }}
  table {{
    box-shadow: 0 1px 3px rgba(0,0,0,0.06);
    border-radius: 8px;
    overflow: hidden;
  }}

  /* ── Header ── */
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    padding: 28px 36px 0;
  }}
  .header-left h1 {{
    font-size: 20px;
    font-weight: 700;
    color: var(--text);
    letter-spacing: -0.01em;
  }}
  .header-left .sub {{
    font-size: 11.5px;
    color: var(--muted2);
    margin-top: 3px;
  }}
  .header-right {{
    text-align: right;
    font-size: 11px;
    color: var(--muted2);
    line-height: 1.6;
  }}
  .header-right .snapshot-label {{
    font-weight: 600;
    color: var(--muted2);
    display: block;
  }}

  /* ── KPI Cards ── */
  .kpis {{
    display: grid;
    grid-template-columns: repeat(7, minmax(0, 1fr));
    gap: 14px;
    padding: 24px 36px;
  }}
  .kpi {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px 20px;
    position: relative;
    overflow: hidden;
  }}
  .kpi::before {{
    content: "";
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: var(--kpi-accent, var(--accent));
    opacity: 0.6;
  }}
  .kpi .label {{
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--muted2);
    margin-bottom: 8px;
  }}
  .kpi .value {{
    font-size: 34px;
    font-weight: 700;
    line-height: 1;
    color: var(--kpi-color, var(--text));
  }}
  .kpi .kpi-sub {{
    font-size: 11px;
    color: var(--muted2);
    margin-top: 5px;
  }}
  .kpi-goal-pct {{
    position: absolute;
    top: 18px;
    right: 20px;
    font-size: 11px;
    font-weight: 600;
    color: var(--muted2);
  }}
  .kpi-split {{
    display: flex;
    gap: 6px;
    margin-top: 10px;
    padding-top: 9px;
    border-top: 1px solid var(--border);
  }}
  .kpi-split-item {{
    flex: 1;
    background: var(--surface2);
    border-radius: 6px;
    padding: 6px 8px;
  }}
  .kpi-split-item .split-label {{
    font-size: 9.5px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
    margin-bottom: 2px;
  }}
  .kpi-split-item .split-value {{
    font-size: 14px;
    font-weight: 700;
    color: var(--text);
    line-height: 1.1;
  }}
  .compact-stats {{
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: var(--muted2);
  }}
  .compact-stats strong {{
    color: var(--text);
    font-weight: 600;
  }}
  .cs-sep {{
    color: var(--border);
    font-size: 14px;
  }}

  .kpi-split-item .split-rate {{
    font-size: 10px;
    color: var(--muted2);
    margin-top: 1px;
  }}

  /* ── Section label ── */
  .section-label {{
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 6px 36px 10px;
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
  }}
  .section-label::after {{
    content: "";
    flex: 1;
    height: 1px;
    background: var(--border);
  }}

  /* ── Table ── */
  .table-wrap {{
    padding: 0 36px 40px;
    overflow-x: auto;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
  }}

  thead th {{
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
    padding: 8px 12px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
    font-weight: 500;
  }}
  thead th.col-num,
  thead th.col-pct,
  thead th.col-rev {{ text-align: right; }}

  /* Funnel parent rows */
  .funnel-row {{
    cursor: pointer;
    border-top: 1px solid var(--border2);
    transition: background 0.1s;
  }}
  .funnel-row:hover {{ background: rgba(79,70,229,0.04); }}
  .funnel-row td {{ padding: 11px 12px; }}

  /* UTM sub-rows */
  .utm-row {{
    display: none;
    background: rgba(79,70,229,0.025);
  }}
  .utm-row.open {{ display: table-row; }}
  .utm-row td {{ padding: 7px 12px; }}
  .utm-row + .utm-row td {{ border-top: 1px solid var(--border2); }}

  .pkg-row {{ display: none; background: #faf9ff; }}
  .pkg-row.open {{ display: table-row; }}
  .pkg-row td {{
    padding: 10px 12px;
    color: var(--muted) !important;
    font-weight: 400 !important;
  }}
  .pkg-row + .pkg-row td {{ border-top: 1px solid var(--border2); }}
  .pkg-row .col-rev  {{ color: #7bc4a0 !important; font-weight: 400 !important; }}
  .pkg-row .col-num  {{ color: var(--muted) !important; }}
  .col-pkg {{
    color: var(--muted2) !important;
    font-size: 12px;
    padding-left: 28px !important;
  }}
  .pkg-trigger {{ cursor: pointer; user-select: none; }}
  .pkg-trigger:hover {{ opacity: 0.75; }}
  .pkg-chevron {{
    font-size: 11px; color: #c0c8d4; margin-left: 4px;
    display: inline-block; transition: transform 0.15s;
  }}
  .pkg-chevron.open {{ transform: rotate(90deg); color: var(--muted2); }}

  /* Total row */
  .total-row {{
    border-top: 2px solid var(--border);
    font-weight: 700;
    background: var(--surface2);
    color: var(--text);
  }}
  .total-row td {{ padding: 12px 12px; }}

  /* Cell types */
  .col-name   {{ min-width: 190px; font-weight: 500; white-space: nowrap; }}
  .col-utm    {{ color: var(--muted2); padding-left: 32px !important; font-weight: 400; }}
  .col-num    {{ text-align: right; color: var(--text); }}
  .col-pct    {{ text-align: right; font-weight: 500; }}
  .col-rev    {{ text-align: right; color: var(--green); font-weight: 500; }}

  /* Excluded-from-totals funnel rows — grayed out */
  .funnel-row-excluded td {{ color: var(--muted) !important; }}
  .funnel-row-excluded .col-rev {{ color: var(--muted) !important; }}
  .funnel-row-excluded .col-pct {{ color: var(--muted) !important; }}
  .funnel-row-excluded .col-pace {{ color: var(--muted) !important; }}
  .funnel-row-excluded .col-goal {{ color: var(--muted) !important; }}

  .col-pct.good {{ color: var(--green); }}
  .col-pct.bad  {{ color: var(--red); }}
  .col-pct.mid  {{ color: var(--amber); }}

  .col-pace  {{ text-align: right; font-size: 12px; color: var(--muted); }}
  .col-goal  {{ text-align: right; font-size: 12px; color: var(--muted); }}
  .col-pace.pace-exceed  {{ color: var(--green); font-weight: 600; }}
  .col-pace.pace-on      {{ color: #ca8a04;      font-weight: 500; }}
  .col-pace.pace-behind  {{ color: var(--red);   font-weight: 500; }}

  /* Chevron toggle */
  .chevron {{
    display: inline-block;
    width: 16px;
    color: var(--muted);
    font-size: 14px;
    transition: transform 0.15s ease;
    transform: rotate(0deg);
    line-height: 1;
  }}
  .chevron.open {{ transform: rotate(90deg); color: var(--accent); }}

  /* Section header rows */
  .section-header-row td {{
    padding: 16px 12px 6px;
    font-size: 10.5px;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--accent);
    font-weight: 700;
    border-top: 2px solid var(--border);
    background: transparent;
    cursor: pointer;
    user-select: none;
  }}
  .section-header-row td:hover {{ color: #a5b4fc; }}
  .section-header-row:first-child td {{ border-top: none; }}
  .section-chevron {{
    display: inline-block;
    width: 14px;
    margin-right: 4px;
    transition: transform 0.15s ease;
    opacity: 0.7;
  }}
  .section-chevron.open {{ transform: rotate(90deg); }}

  /* Progress bar mini (optional decoration on booked column) */
  /* Pickers row */
  .pickers-row {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 6px;
    flex-wrap: wrap;
    justify-content: flex-end;
  }}
  /* Month picker */
  .month-picker {{
    display: flex;
    align-items: center;
    gap: 7px;
  }}
  .month-picker select, .week-picker select {{
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
    cursor: pointer;
    outline: none;
  }}
  .month-picker select:hover, .week-picker select:hover {{
    border-color: var(--accent);
  }}
  /* Week picker */
  .week-picker {{
    display: flex;
    align-items: center;
    gap: 7px;
  }}
  .picker-divider {{
    color: var(--border);
    font-size: 16px;
    line-height: 1;
    margin: 0 2px;
  }}
  .archive-badge {{
    display: inline-block;
    background: #fef3c7;
    color: #92400e;
    border: 1px solid #fcd34d;
    border-radius: 4px;
    font-size: 10px;
    font-weight: 600;
    padding: 2px 7px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    white-space: nowrap;
  }}

  /* CSV download button */
  .csv-download-btn {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: var(--surface);
    color: var(--muted2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 6px 12px;
    font-size: 12px;
    font-family: inherit;
    cursor: pointer;
    white-space: nowrap;
    flex-shrink: 0;
  }}
  .csv-download-btn:hover {{
    border-color: var(--accent);
    color: var(--accent);
  }}

  @media (max-width: 960px) {{
    .kpis {{ grid-template-columns: repeat(2, 1fr); }}
    .header {{ flex-direction: column; gap: 12px; }}
    .header-right {{ text-align: left; }}
  }}
</style>
</head>
<body>

<!-- Header -->
<div class="header">
  <div class="header-left">
    <h1>MTD Funnel Performance
      <a href="/mtd-funnel-dashboard/archives/mom.html"
         style="font-size:12px; font-weight:500; color:var(--accent); margin-left:14px;
                text-decoration:none; vertical-align:middle;">
        Month over Month →
      </a>
    </h1>
    <p class="sub">Vendingpreneurs · All Sales Calls · {data['month_label']}{data.get('week_range_label','')}</p>
  </div>
  <div class="header-right">
    <div class="pickers-row">
      <div class="compact-stats">
        <span class="cs-item">Day <strong>{day_num}/{days_tot}</strong></span>
        <span class="cs-sep">·</span>
        <span class="cs-item">Working days <strong>{wd_num}/{wd_tot}</strong></span>
        <span class="cs-sep">·</span>
        <span class="cs-item"><strong>{pct_month}%</strong> elapsed</span>
      </div>
      <span class="picker-divider">|</span>
      {month_picker_html}{week_picker_html}
    </div>
    <span class="snapshot-label">{data.get("badge_html","") or "Snapshot"}</span>
    {data['generated_at']}<br>
    Source · Close CRM
  </div>
</div>

<!-- KPI Cards -->
<div class="kpis">
  <div class="kpi" style="--kpi-accent:#6366f1; --kpi-color:#6366f1;">
    <div class="label">Leads Created</div>
    <div class="value">{g_lc}</div>
    <div class="kpi-sub">new leads MTD</div>
  </div>
  <div class="kpi" style="--kpi-accent:#4f46e5; --kpi-color:var(--text);">
    <div class="kpi-goal-pct">{goal_pct_corner(g_bo, MONTHLY_BOOKED_GOAL)}</div>
    <div class="label">Total Booked</div>
    <div class="value">{g_bo}<span style="font-size:15px; font-weight:400; color:var(--muted); margin-left:10px;">/ {MONTHLY_BOOKED_GOAL:,} <span style="font-size:12px;">goal</span></span></div>
    <div class="kpi-sub">new first calls MTD</div>
  </div>
  <div class="kpi" style="--kpi-accent:#0891b2; --kpi-color:#0891b2;">
    <div class="label">Calls Occurred</div>
    <div class="value">{grand.get("occurred", 0)}</div>
    <div class="kpi-sub">{g_sh} showed · {grand.get("no_shows", 0)} no shows</div>
    <div class="kpi-sub">{grand.get("unresolved", 0)} unresolved · excluded</div>
  </div>
  <div class="kpi" style="--kpi-accent:#2563eb; --kpi-color:#2563eb;">
    <div class="label">Showed</div>
    <div class="value">{g_sh}</div>
    <div class="kpi-sub">{pct(g_sh, grand.get("occurred", 0))} show rate</div>
  </div>
  <div class="kpi" style="--kpi-accent:#7c3aed; --kpi-color:#7c3aed;">
    <div class="label">Qualified</div>
    <div class="value">{g_qu}</div>
    <div class="kpi-sub">{pct(g_qu, grand.get("occurred", 0))} of calls occurred</div>
  </div>
  <div class="kpi" style="--kpi-accent:#d97706; --kpi-color:#d97706;">
    <div class="label">Closed Won</div>
    <div class="value">{g_cl}</div>
    <div class="kpi-sub">{pct(g_cl, grand.get("occurred", 0))} close rate · date won</div>
  </div>
  <div class="kpi" style="--kpi-accent:#0e9f6e; --kpi-color:#0e9f6e;">
    <div class="kpi-goal-pct">{goal_pct_corner(g_rev, MONTHLY_REVENUE_GOAL)}</div>
    <div class="label">Closed Revenue</div>
    <div class="value">{fmt_currency(g_rev)}<span style="font-size:15px; font-weight:400; color:var(--muted); margin-left:10px;">/ {fmt_currency(MONTHLY_REVENUE_GOAL)}</span></div>
    <div class="kpi-sub">{rev_per_close(g_rev, g_cl)} avg deal{f'  ·  <span style="color:#7bc4a0; font-weight:600;">ARR {fmt_currency(g_vh_rev)}</span>  <span style="color:#7bc4a0; opacity:0.75; font-size:11px;">MRR {fmt_currency(g_vh_rev / 12)}</span>' if g_vh_rev else ""}</div>
  </div>
</div>

<!-- Table -->
<div class="section-label">Funnel Breakdown — Booked → Calls Occurred → Showed → Qualified → Closed Won → Revenue</div>

<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th class="col-name">Funnel</th>
        <th class="col-num">Leads</th>
        <th class="col-num">Booked</th>
        <th class="col-pace">Projected</th>
        <th class="col-goal">Goal %</th>
        <th class="col-num" title="Completed + No Show; excludes cancellations, future calls and unresolved outcomes">Occurred</th>
        <th class="col-num">Showed</th>
        <th class="col-pct" title="Period numerator divided by Calls Occurred">Show %</th>
        <th class="col-num">Qualified</th>
        <th class="col-pct" title="Period numerator divided by Calls Occurred">Qual %</th>
        <th class="col-num">Closed</th>
        <th class="col-pct" title="Period numerator divided by Calls Occurred">CW %</th>
        <th class="col-rev">Revenue</th>
        <th class="col-num">Rev / Close</th>
      </tr>
    </thead>
    <tbody>
{funnel_rows}

    <tr class="total-row">
      <td class="col-name">TOTAL</td>
      <td class="col-num">{g_lc if g_lc else "—"}</td>
      <td class="col-num">{g_bo}</td>
      <td class="col-pace">—</td>
      <td class="col-goal">—</td>
      <td class="col-num">{grand.get("occurred", 0)}</td>
      <td class="col-num">{g_sh}</td>
      <td class="col-pct {pct_class(g_sh, grand.get("occurred", 0))}">{pct(g_sh, grand.get("occurred", 0))}</td>
      <td class="col-num">{g_qu}</td>
      <td class="col-pct {pct_class(g_qu, grand.get("occurred", 0))}">{pct(g_qu, grand.get("occurred", 0))}</td>
      <td class="col-num">{g_cl}</td>
      <td class="col-pct {pct_class(g_cl, grand.get("occurred", 0), high=0.15, low=0.07)}">{pct(g_cl, grand.get("occurred", 0))}</td>
      <td class="col-rev">{fmt_currency(g_rev)}</td>
      <td class="col-num">{rev_per_close(g_rev, g_cl)}</td>
    </tr>
    </tbody>
  </table>
</div>

<script src="/mtd-funnel-dashboard/archives/picker.js"></script>
<script>
  function togglePkg(fid) {{
    const pkgRows = document.querySelectorAll(`.pkg-row[data-parent="${{fid}}"]`);
    const chevron = document.getElementById("pkgchev-" + fid);
    const isOpen  = chevron && chevron.classList.contains("open");
    pkgRows.forEach(r => {{
      r.style.display = isOpen ? "none" : "table-row";
      r.classList.toggle("open", !isOpen);
    }});
    if (chevron) chevron.classList.toggle("open", !isOpen);
  }}

  function toggleUTM(fid) {{
    const utmRows = document.querySelectorAll(`.utm-row[data-parent="${{fid}}"]`);
    const chevron = document.getElementById("chev-" + fid);
    const isOpen  = chevron.classList.contains("open");
    utmRows.forEach(r => r.classList.toggle("open", !isOpen));
    chevron.classList.toggle("open", !isOpen);
  }}

  function toggleSection(grpId) {{
    const chevron  = document.getElementById("secchev-" + grpId);
    const isOpen   = chevron.classList.contains("open");
    // All funnel rows and their utm sub-rows in this section
    const funnelRows = document.querySelectorAll(`.funnel-row[data-section="${{grpId}}"]`);
    funnelRows.forEach(row => {{
      row.style.display = isOpen ? "none" : "";
      // Also collapse any open UTM sub-rows within this section
      const fid = row.dataset.fid;
      if (fid) {{
        const utmRows = document.querySelectorAll(`.utm-row[data-parent="${{fid}}"]`);
        if (isOpen) {{
          utmRows.forEach(r => r.classList.remove("open"));
          const utmChev = document.getElementById("chev-" + fid);
          if (utmChev) utmChev.classList.remove("open");
        }}
      }}
    }});
    chevron.classList.toggle("open", !isOpen);
  }}

  function csvEscape(value) {{
    const s = String(value == null ? "" : value);
    if (/["\\n,]/.test(s)) {{
      return '"' + s.replace(/"/g, '""') + '"';
    }}
    return s;
  }}

  function downloadFunnelCSV() {{
    const table = document.querySelector(".table-wrap table");
    if (!table) return;

    const headerCells = Array.from(table.querySelectorAll("thead th"))
      .map(th => th.textContent.replace(/\s+/g, " ").trim());
    const rows = [headerCells];

    table.querySelectorAll("tbody tr").forEach(tr => {{
      // Only export top-level funnel rows and the TOTAL row — skip section
      // headers and the collapsible UTM/package sub-rows.
      if (!tr.classList.contains("funnel-row") && !tr.classList.contains("total-row")) return;
      const cells = Array.from(tr.children).map(td =>
        td.textContent.replace(/[›▶]/g, "").replace(/\s+/g, " ").trim()
      );
      rows.push(cells);
    }});

    const csv = rows.map(r => r.map(csvEscape).join(",")).join("\\r\\n");
    const blob = new Blob([csv], {{ type: "text/csv;charset=utf-8;" }});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "{csv_filename}";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }}
</script>

<div style="padding: 24px 36px 32px; border-top: 1px solid var(--border); margin-top: 8px; display:flex; align-items:flex-start; justify-content:space-between; gap:20px; flex-wrap:wrap;">
  <p style="font-size: 11px; color: var(--muted); line-height: 1.7; max-width: 640px; margin:0;">
    <strong style="color: var(--muted2);">Projected</strong> — End-of-month estimate based on current daily booking pace:
    <em>(Booked ÷ Days Elapsed) × Days in Month</em>. Color reflects projected vs goal.
    &nbsp;&nbsp;<strong style="color: var(--muted2);">*</strong> — Funnel excluded from top-line totals and KPI tiles.
    <span style="color: var(--green); font-weight:600;">Green</span> = exceeding pace &nbsp;·&nbsp;
    <span style="color: #ca8a04; font-weight:600;">Yellow</span> = on pace &nbsp;·&nbsp;
    <span style="color: var(--red); font-weight:600;">Red</span> = behind pace.
    Funnels without a goal show —.
    Goals are updated monthly in <code style="font-size:10.5px; background:var(--surface2); padding:1px 4px; border-radius:3px;">goals.json</code>.
  </p>
  <button type="button" class="csv-download-btn" onclick="downloadFunnelCSV()">⬇ Download CSV</button>
</div>

</body>
</html>"""
