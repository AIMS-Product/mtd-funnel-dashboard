# MTD Funnel V2 calculation rules

This document describes the report produced by [`build.py`](build.py) and the aggregate-only page produced by [`publish_shadow.py`](publish_shadow.py). It is pinned to rules version `booked_calls.v2.6-scheduled-anchor-candidate+any-meeting-clock+william-consult-retired-20261014`.

For exact title regular expressions, setters, caller exclusions, source aliases, Close field IDs, and cancellation settings, use [`rules.json`](rules.json) as the machine-readable authority. Apply title rules in array order. Do not reconstruct or maintain a second copy of those mappings from this prose. The builder is the executable authority where this document and implementation differ.

## 1. Source window and timezone

- Timezone: `America/Los_Angeles`.
- The report starts at midnight Pacific on the first calendar day of the current month.
- The MTD source cutoff is the build's `as_of` instant. Meeting and lead creation timestamps are included when they are at or after the start and strictly before `as_of`.
- Meetings are selected by Close `activity/meeting.date_created` (when the activity was created/booked), not by scheduled start or completion date. Convert Pacific window boundaries to UTC for the Close query, then apply the precise half-open interval `[start, as_of)` in code.
- Scheduled meeting start (`starts_at`) is a separate field used for the repeat clock. It must be present and timezone-aware.
- Close timestamps without an explicit timezone, malformed timestamps, or absent timestamps are not accepted as valid times.

## 2. Which meetings qualify

Each candidate must have a lead, a valid scheduled start, a creation time in the MTD window, a non-canceled event, and one of these statuses: `upcoming`, `in-progress`, or `completed`.

The title is matched case-insensitively using the ordered `title_rules` in `rules.json`:

1. The first matching active title-map rule assigns `Lane 2`, except a rule owned by Pearl Sathekge assigns `Social DMs`.
2. A rule with `retired_at_exclusive` is skipped when the meeting's creation time is at or after that timestamp.
3. If no roster rule matches, the Pearl fallback can assign `Social DMs` only when a contact's UTM source is in `pearl_accepted_utm_sources` and the title matches a `pearl_source_title_patterns` entry.
4. After those two checks, follow-up titles (`FOLLOWUP`) and non-booking titles (`NON_BOOKING`) are excluded from fallback classification. Otherwise, titles matching a `new_call_patterns` entry assign `Marketing`, unless the Close meeting creator is in `excluded_callers` or `setter_only_callers`.
5. Cancellation-prefixed titles are excluded by the separate cancellation test above. The exact regular expressions are constants in `build.py` and the approved mappings/pattern lists are in `rules.json`.

The title map takes precedence over the Pearl source fallback and Marketing patterns. Pearl Social DMs are their own booking bucket; they are not included in Lane 2. The title's setter/map determines the booking bucket. Lead source is resolved separately under section 5.

For a rule with `required_setter`, the builder compares it case-insensitively to the lead's Setter Name custom field. `setter_user_id` is retained as roster provenance but is not a title-match condition. The runtime uses the checked-in title map; it does not fetch a roster file during report generation.

The current map has 35 ordered title rules. None is flagged `historical`; the William Nowak `vending consult call` rule has an exclusive retirement timestamp of October 14, 2026 at 12:00 AM Pacific. The older historical cutoff in `rules.json` therefore does not exclude any current title rule.

Cancellation removes a candidate and excludes it from the repeat clock if **any** of these is true:

- Close status is `canceled`, `cancelled`, `declined-by-lead`, or `declined-by-org`;
- the linked Close outcome label is `Canceled` or `Cancelled` (case-insensitive); or
- the title starts with `Canceled` or `Cancelled`.

Other non-canceled candidate statuses are limited to the three active statuses above. A no-show or missing outcome does not cancel a meeting, so an otherwise qualifying booking keeps its credit. `Showed` is determined separately: only a normalized native outcome label exactly equal to `Completed` is a show.

## 3. Repeat clock and credit selection

The 30-day episode filter is applied to `Lane 2` and `Social DMs` candidates. Marketing title matches are counted directly and are not repeat-suppressed by this function.

For each lead with at least one Lane 2 or Social DM candidate, load that lead's Close meeting history (not just the MTD window). From that history:

- Ignore canceled/declined meetings under the cancellation test above.
- Ignore meetings without a valid `starts_at`.
- Keep every other meeting as a clock event, including meetings whose titles are not booking candidates.
- Sort by scheduled start, then creation time (missing creation time sorts last), then activity ID.
- The earliest event starts the clock. Each subsequent event at a gap of **720 hours or less** is inside the existing episode. It earns no second Lane 2/Social DM candidate credit, but it advances the clock to its own scheduled start. A qualifying candidate is eligible only when its scheduled start is **strictly more than 720 elapsed hours** after the previous non-canceled scheduled meeting.
- The earliest event after a gap greater than 720 hours starts a new episode; if it is a qualifying candidate, it earns that episode's one credit.

Thus the clock is a rolling 30 × 24-hour clock anchored to scheduled meeting start, not a calendar-month calculation and not anchored to lead creation or meeting creation. Any non-canceled scheduled meeting for a lead with Lane 2/Social DM candidates starts or advances that clock, even when its title earns no booking credit. A canceled meeting does not start or advance it. A canceled booking loses its candidate credit; a later qualifying replacement can earn credit if eligible under this same episode rule.

### Reschedule implementation note

`rules.json` contains `rescheduled_outcome_preserves_original_credit`, but `build.py` does not read that setting directly. In the implementation, a meeting with status `rescheduled` is not an active candidate status; as non-canceled history with a scheduled start, it can still advance the clock. An upcoming candidate is suppressed only when it falls within the rolling 720-hour window. There is no independent blanket rule that suppresses a replacement forever solely because its outcome says `Rescheduled`. This is the exact current code behavior and should be reconciled with the business rule before anyone reimplements that edge case differently.

## 4. Booked counts and bucket splits

- Each row in `counted` is one meeting credit.
- `Marketing` candidates are counted once per qualifying meeting activity.
- `Lane 2` and `Social DMs` candidates are counted only if selected as the one eligible qualifying candidate in an episode.
- Total Booked = Marketing + Lane 2 + Social DMs across all source channels.
- A lead may receive credits in more than one booking bucket/channel if separate qualifying activities meet the rules; deduplication is by meeting activity for the episode logic, not globally by person.
- On the V2 page, the top Total Booked card shows those three bucket totals directly.

## 5. Lead source and attribution

Booking bucket and lead source are different dimensions. The meeting title/map assigns `Marketing`, `Lane 2`, or `Social DMs`; source resolution assigns a lead-source channel.

For each booked lead (and for won leads when needed), source resolution is:

1. If the lead's Funnel Name custom field case-insensitively matches one of `marketing_sources` in `rules.json`, use that canonical source.
2. Otherwise inspect the contact UTM Source field for all contacts on the lead. Trim whitespace, case-fold, remove everything beginning with `&` or `?`, and map each value using `utm_source_map`.
3. Resolve to a channel only if the contacts yield exactly one distinct mapped source and no non-empty source value is unmapped. Repeated aliases mapping to the same source are fine.
4. If no source resolves, values conflict, or any non-empty source value is unmapped, assign `Unknown (Needs Review)`.

UTM Campaign, UTM Content, UTM Medium, Resource Tag, and the booking setter do **not** determine the lead-source channel. `source_medium_overrides` and `resource_tag_map` are empty and are not fallback rules. Unbooked leads created MTD are not contact-scanned for source fallback: their channel uses the recognized lead Funnel Name only; otherwise they are included under Unknown.

Close custom field IDs read by the builder (the rule file is still the authority for values and aliases):

| Object | Field ID | Use |
| --- | --- | --- |
| Lead | `lead_fields.funnel` in `rules.json` | First-choice lead source |
| Lead | `lead_fields.setter_name` in `rules.json` | Optional title-rule setter check |
| Lead | `cf_ZDx7NBQaDzV1yYrFcBMzt6cIYj81dAcswpNN0CQzCPS` | Qualified flag |
| Contact | `contact_utm_fields.source` in `rules.json` | Lead-source fallback and Pearl fallback |
| Contact | `cf_jnbd0xzUY3tuxzxiGxBs2hONuExeXMvAoTUM2R64Lq3` | Campaign drilldown |
| Contact | `cf_R7o66i0XPycLQHlxOLbIqk6c6j3oB8CzxF3e3apI1hn` | Webinar content drilldown |

Unknown booked leads have an additional private row-level status `unrecoverable_under_v2_rules` with a reason distinguishing missing UTM Source, an unmapped value, conflicting mapped sources, or mapped plus unmapped values. This status does not change the channel or infer a source from campaign/content. The public page reports only the aggregate number of reviewed unique booked leads; it does not expose lead names, IDs, meeting details, or raw UTM values.

## 6. UTM value drilldowns

For contacts in the Close response order, take the first non-empty UTM Campaign and first non-empty UTM Content independently. An absent value becomes `Unattributed`.

- For `Internal Webinar`, the public table groups booking credits by UTM Content value.
- For every other source channel, the public table groups booking credits by UTM Campaign value.
- These are aggregate booking-credit counts. The public page omits the Campaign/Content labels and nested drilldown hierarchy. It includes only approved plain values and counts.

## 7. Leads created

Fetch leads whose Close `date_created` is in `[Pacific month start, as_of)`. Exclude leads whose status ID is in `excluded_lead_status_ids` in `rules.json`. Count each returned lead once under its resolved lead-source channel using section 5. This is a lead count, not a meeting credit. Leads with no recognized source are counted under Unknown; no contact UTM fallback is run for the unbooked created-lead population. This lead-status exclusion applies to the Leads Created metric; it is not applied as an additional filter to booked meeting candidates or won opportunities.

## 8. Showed, qualified, wins, and revenue

- **Showed:** Counted booking credits whose native Close outcome label normalizes to `Completed`. Show rate = Showed ÷ Booked.
- **Qualified:** A counted lead is qualified when the lead's qualification custom field normalizes to `yes`, `true`, or `1`. Aggregate qualified counts use distinct lead IDs per channel, so repeat meeting credits for one qualified lead do not inflate that channel's qualified-lead count. Qualification rates shown are Qualified ÷ Showed and Qualified ÷ Booked.
- **Closed Won:** Fetch Close opportunities where `status_type=won`, with `date_won` from the first day of the current Pacific month through the `as_of` Pacific calendar date inclusive. Exclude opportunities owned by `excluded_closers`. Each eligible opportunity counts once; this is an opportunity count, not a distinct-lead count.
- **Closed Revenue:** Sum eligible opportunity values. The established Close values are in cents; parse the first whitespace-delimited value, remove `$` and commas, then divide by 100. Invalid or missing values contribute $0. If an opportunity has a currency and it is not USD, exclude it; a missing currency is accepted.
- Opportunity source channel is resolved from the linked lead under section 5. When the lead Funnel Name is not recognized, contacts are fetched for source fallback.
- Revenue per Close = Closed Revenue ÷ Closed Won; show `$0` average deal when there are no wins and `—` in the table's Rev / Close column.

**Cutoff caveat:** Opportunities use date-only `date_won` filters through the snapshot's Pacific calendar date. Unlike meeting and lead creation, the opportunity query is not clipped to the exact `as_of` time of day. A same-day win later than the displayed snapshot time can therefore be included if already returned by Close.

## 9. Display calculations

- Percentages are computed as `100 × numerator / denominator`, to one decimal place. A zero denominator displays `—`.
- Show rate = showed ÷ booked.
- Qualification rates = qualified ÷ showed and qualified ÷ booked.
- Close rates = closed won ÷ booked and closed won ÷ qualified.
- Revenue / Close = revenue ÷ closed won.
- Show and qualification rate colors: green at 70% or more; amber at 50% to under 70%; red below 50%.
- Close-rate colors: green at 15% or more; amber at 7% to under 15%; red below 7%.
- Header progress uses the reporting month's calendar day and total days; working-day progress counts Monday–Friday through that day. Percentage elapsed is working days elapsed ÷ working days in the month.
- Projected bookings = round(booked ÷ calendar day elapsed × days in month). Goal % = rounded booked ÷ the source's monthly goal × 100, with the target shown in parentheses. Sources without a target have no goal percentage or pace color. Total rows omit projection and goal percentage.
- Monthly targets remain 1,241 bookings and $750,000 revenue. Per-source targets come from the existing root `goals.json`. Weekly views retain the same full monthly targets and monthly pace reference, matching the current MTD. Saved archive snapshots retain their goals.
- Projected bookings above target are green, equal to target yellow, and below target red.
- ARR follows the current MTD's VendHub package contributions: VendHub-only tiers contribute the full included won opportunity value; Bronze contributes $1,200, Silver and Scale $2,998 each. MRR = ARR ÷ 12. These are calculated over the same included USD won opportunities as V2 revenue.
- Currency and counts use US formatting; the top Closed Revenue KPI rounds to whole dollars.

## 10. Refresh, privacy, and reproducibility

Use the exact `rules.json` and `build.py` from the same commit. The scheduled workflow refreshes the live month and week, fills missing October-onward history, and maintains aggregate-only archives:

```bash
python3 v2/refresh.py
```

Archive coverage starts October 1, 2026, including the partial October 1–4 week. All intervals use an exclusive Pacific midnight cutoff after their last day, including daylight-saving transitions. Completed periods are finalized once at rollover and retained; the current month/week continue refreshing. Historical periods are reconstructed from current Close records within those windows, including the outcomes and attribution available when rebuilt. They do not reproduce an unavailable historical CRM state. `generated_at` records the actual rebuild time, while `source_cutoff` records the reporting-window boundary.

`build.py` uses read-only Close GET requests. The standalone builder writes private row-level output under `v2/public/`; automated refreshes keep that data in temporary private storage. `publish_shadow.py` whitelists only aggregate values for `v2/index.html` and V2's HTML/JSON archives. Do not publish or commit `v2/public/data.json` or `v2/public/index.html`; they contain lead and meeting details. The current MTD and its archives remain unchanged.
