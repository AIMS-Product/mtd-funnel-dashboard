# MTD Funnel V2

V2 is a shadow implementation of the MTD funnel report. Its files and hosted page live under `v2/`; the production report at the repository root is unchanged.

## Refresh and publish the shadow

The dedicated [`update_v2.yml`](../.github/workflows/update_v2.yml) GitHub Actions workflow refreshes V2 using the repository's existing `CLOSE_API_KEY` secret. A separate cron-job.org job dispatches it on `main` every 15 minutes at :00, :15, :30, and :45 in `America/Los_Angeles`, matching the current MTD refresh cadence. It can also be run manually from the Actions tab.

The workflow builds a fresh Close snapshot, renders the aggregate-only public page, and commits only `v2/index.html` for GitHub Pages. Its own concurrency group prevents overlapping V2 builds, and it rebases before pushing to preserve updates from other dashboard jobs. The current MTD workflow, schedule, root dashboard, and archives are unchanged.

To run the same refresh locally:

Set `CLOSE_API_KEY` in the runner environment, then run:

```bash
python3 v2/build.py
python3 v2/publish_shadow.py
```

`build.py` performs read-only Close API pulls and writes a private local snapshot and preview under `v2/public/`. Those files include lead and meeting details and are excluded from Git. `publish_shadow.py` copies only approved aggregate metrics into the familiar MTD dashboard layout and writes `v2/index.html`. For a script chain, publish only `v2/index.html`; never add the private `v2/public/` outputs.

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
- The public shadow shows aggregate totals and plain attributed-value rows under each source: campaign values generally, and UTM Content values for Internal Webinar. It omits campaign/content labels and hierarchy, lead names, meeting titles, Close links, IDs, and meeting-level drilldowns.

The pinned rule configuration is recorded in `rules.json`. Raw Close response data and the local detailed preview remain private and are not committed.
