# MTD Funnel V2

V2 is a shadow implementation of the MTD funnel report. Its files and hosted page live under `v2/`; the production report at the repository root is unchanged.

## Refresh and publish the shadow

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

- Reporting period is based on Close meeting creation time in America/Los_Angeles.
- The meeting title and approved title map determine booking channel. Lead source is reported separately.
- Pearl's Social DMs are distinct from Lane 2.
- Only active/eligible Lane 2 title mappings earn Lane 2 credit. Canceled and declined meetings do not count as bookings and do not start the repeat clock.
- The 30-day repeat clock is anchored to scheduled meeting start. Any non-canceled scheduled meeting starts or advances the clock, even when its title does not earn booking credit. Exactly 720 elapsed hours remains inside the window; a new qualifying credit is eligible only after 720 hours.
- A qualifying no-show keeps its booking credit. A reschedule earns no second credit. A canceled meeting loses its credit; a later qualifying replacement may earn one under the repeat-clock rule.
- The public shadow uses aggregate totals and source rows, with aggregate UTM campaign/content drilldowns. It excludes lead names, meeting titles, Close links, IDs, and meeting-level drilldowns.

The pinned rule configuration is recorded in `rules.json`. Raw Close response data and the local detailed preview remain private and are not committed.
