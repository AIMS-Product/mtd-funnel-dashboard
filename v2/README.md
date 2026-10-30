# MTD Funnel V2

V2 is a shadow implementation of the MTD funnel report. Its files and hosted page live under `v2/`; the production report at the repository root is unchanged.

V2 uses the **current MTD archive UI 1:1**, through its actual presentation functions and original month-comparison page. There is no separate V2 styling, badge, section layout, or extra button. Only V2 aggregates and V2-local navigation are supplied. The adapter loads presentation functions/constants only; legacy CRM extraction and booking selection are never run.

## Refresh and publish the shadow

The dedicated [`update_v2.yml`](../.github/workflows/update_v2.yml) GitHub Actions workflow refreshes V2 using the repository's existing `CLOSE_API_KEY` secret. A separate cron-job.org job dispatches it on `main` every 15 minutes at :00, :15, :30, and :45 in `America/Los_Angeles`, matching the current MTD refresh cadence. It can also be run manually from the Actions tab.

The workflow runs `python3 v2/refresh.py`, refreshing the full month and current week while maintaining V2's own monthly and weekly archives. It commits only `v2/index.html` and aggregate-only files under `v2/archives/` and `v2/reports/` for GitHub Pages. Its concurrency group prevents overlapping V2 builds, and it rebases before pushing to preserve updates from other dashboard jobs. The current MTD workflow, schedule, root dashboard, root reports, and root archives are unchanged.

## Expanded reporting

- **Month over Month** compares V2 source bookings, show/qualification/close rates, and revenue. October is the first month; additional months appear automatically. Legacy data is never mixed into V2 comparisons.
- Source expansion shows full campaign metrics (or content metrics for Internal Webinar), including independently attributed won deals with no booking in the selected window. Qualification counts remain distinct booked leads within each group.
- Revenue expansion shows aggregate program-tier and VendHub-plan counts, revenue, and average deal value.
- Setter detail appears inside the current UI's existing source expansion rows, with the same row styling. Lane 2 and Social DM booking credits remain separate in the saved setter CSVs. Booking/show/qualification attribution follows the credited meeting's setter; won deals and revenue follow the lead's current setter independently of booking date.
- The current UI's funnel-section collapse, campaign expansion, revenue/package expansion, and CSV button are reused unchanged. Both on-page and saved funnel CSVs include a TOTAL row. Python performs the same archive rounding as the current MTD.
- Each saved period includes a V2 funnel CSV and V2 team CSV. Team bookings, shows, and qualification use accepted V2 credits attributed to the current Lead Owner; won deals/revenue use the included V2 opportunities' owners. Closer subtotal, Other / Non-Closer, and all-V2 totals are separately labeled and reconciled. Qualified counts are distinct booked leads per owner.
- Team CSVs retain revenue goals (booked × 13% × $7,000), rate goals, and the existing current pipeline definition. Only the current MTD's independent open-qualified-pipeline helper is reused; its legacy booking and won-record selectors are never used. Pipeline is a generation-time snapshot of current closer-owned qualified leads within the trailing 30 days, valued at $7,000 × 20%, and is labeled separately from the report week.

The dedicated **Generate V2 Weekly and Team Reports** Actions workflow accepts start/end dates and generates both CSVs from a single V2 pull. It also supports custom reporting windows from October onward:

```bash
python3 v2/reports.py --start 2026-10-19 --end 2026-10-25
```

Existing October aggregate snapshots are upgraded once to add the new detail. Future refreshes retain finalized snapshots after that upgrade.

## Goals, projections, and archives

- The header shows calendar-day progress, Monday–Friday working-day progress, and percentage of working days elapsed in Pacific time.
- Bookings and revenue use the existing MTD monthly targets: **1,241 bookings** and **$750,000 revenue**. Source-level goals are read from the existing root `goals.json` without modifying it. Weekly views retain full monthly targets and monthly pace references, matching the current MTD.
- Projected bookings use `(bookings / calendar day elapsed) × days in month`. The colors compare projected bookings to each source's goal. Conversion subtext includes show rate, qualification rate, booked-to-close, qualified-to-close, and average deal value.
- ARR uses the current MTD's VendHub-only tiers and package contributions, counted only for V2's included USD won opportunities. MRR is ARR divided by 12; no booking or revenue inclusion rules change.
- Archive coverage begins **October 1, 2026**. The opening partial week covers October 1–4 (its Monday-based filename is `week-2026-09-28`). Later weeks run Monday–Sunday. The current week updates with every refresh.
- A completed week or month is rebuilt once at rollover, then its aggregate snapshot is retained. Missing completed periods are filled automatically. Historical views are reconstructed from current Close records for their reporting window; they are not claims about the CRM's state at the original historical cutoff.
- All month/week navigation stays inside V2. Archived goals and figures remain tied to the saved aggregate snapshot. CSV exports contain source-level aggregates only.

### Supplemental historical archives

The same selectors also provide the original MTD's January–September 2026 monthly archives and its available April–September weekly archives. These are frozen copies under `v2/archives/supplemental/`, labeled **Historical · Original MTD rules** in the existing archive badge and **(Historical)** in the month selector. Their numbers, original snapshot timestamps, table details, CSV calculations, and UI are preserved; they are not recalculated with V2 rules. A manifest records each source page and its hash. Every refresh retains these copies and maintains navigation inside V2.

The September 28–October 4 legacy week has its own supplemental URL, separate from V2's October 1–4 partial week. Supplemental history is excluded from V2's month comparison. October onward continues to use V2 rules and V2's existing retention process.

To refresh V2, generate missing October-onward archives, and render all navigation:

```bash
python3 v2/refresh.py
```

To update presentation from saved aggregate archives without any Close reads:

```bash
python3 v2/refresh.py --render-only
```

Regression checks: `python3 -m unittest discover -s v2 -p 'test*.py'`.

To run the same refresh locally:

Set `CLOSE_API_KEY` in the runner environment, then run:

```bash
python3 v2/build.py
python3 v2/publish_shadow.py
```

`build.py` performs read-only Close API pulls and writes a private local snapshot and preview under `v2/public/`. Those files include lead and meeting details and are excluded from Git. `publish_shadow.py` copies only approved aggregate metrics into the familiar MTD dashboard layout and writes `v2/index.html`. The automated `refresh.py` uses that same whitelist, keeping detailed snapshots in a temporary private directory. Never add the private `v2/public/` outputs.

To regenerate the public page from an existing local snapshot without another Close pull:

```bash
python3 v2/publish_shadow.py --source v2/public/data.json
```

## V2 rules

The detailed replication guide is [`CALCULATION_RULES.md`](CALCULATION_RULES.md). It documents the time windows, meeting qualification and credit logic, lead-source attribution, metric formulas, display calculations, and implementation caveats. The exact machine-readable mappings and policy constants remain in [`rules.json`](rules.json), and [`build.py`](build.py) is the executable reference.

- Reporting period is based on Close meeting creation time in America/Los_Angeles.
- The meeting title and approved title map determine booking channel. Lead source is reported separately.
- Pearl's Social DMs are distinct from Lane 2.
- Only active/eligible Lane 2 title mappings earn Lane 2 credit. Canceled and declined meetings do not count as bookings and do not start the repeat clock.
- The 30-day repeat clock is anchored to scheduled meeting start. Any non-canceled scheduled meeting starts or advances the clock, even when its title does not earn booking credit. Exactly 720 elapsed hours remains inside the window; a new qualifying credit is eligible only after 720 hours.
- A qualifying no-show keeps its booking credit. A reschedule earns no second credit. A canceled meeting loses its credit; a later qualifying replacement may earn one under the repeat-clock rule.
- The public shadow shows aggregate totals and plain attributed-value rows under each source: campaign values generally, and UTM Content values for Internal Webinar. It also includes aggregate staff and package breakdowns. It omits lead names, meeting titles, Close links, IDs, and meeting-level drilldowns.

The pinned rule configuration is recorded in `rules.json`. Raw Close response data and the local detailed preview remain private and are not committed.
