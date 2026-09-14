#!/usr/bin/env python3
"""
Meetings Booked — Per-Day Breakdown (one-off report)

The MTD Funnel dashboard only ever stores period-level totals (a single
number for the whole month, week, or archive) — it never persists which day
within that period each meeting fell on. This script re-derives that day-
level detail on demand, straight from Close, using the EXACT same "Booked"
methodology as fetch_and_build.py's aggregate_data(), so the total this
script reports for a period should match the dashboard's Booked KPI for
that same period.

Methodology mirrored from fetch_and_build.py (2026-09-14):
  - Every funnel except Reactivation Scrapers: "Booked" = lead's First Sales
    Call Booked Date custom field falls in the range. Bucketed by that field
    value directly (it's a date-only field, already Pacific-agnostic).
  - Reactivation Scrapers: "Booked" = a Close /activity/meeting/ whose title
    matches one of the 22 known Next Steps calendar-link patterns, whose
    lead's Funnel Name is "Reactivation Scrapers". Bucketed by the meeting's
    starts_at, converted to Pacific.
  - Excluded everywhere: leads with status Canceled (by Lead) or Outside the
    US, and leads whose BTC Business Line is "The Land Geek (TLG)".
  - Excluded from the TOTAL only (matches the dashboard's KPI tiles): the
    "LTF - Quiz Funnel" funnel.

Usage:
    CLOSE_API_KEY=xxx python3 meetings_by_day.py --start 2026-09-07 --end 2026-09-13

If you change any of these rules in fetch_and_build.py, mirror the change
here too — this is a standalone copy, not an import, so it won't pick up
dashboard changes automatically.
"""

import os
import re
import sys
import time
import argparse
from datetime import datetime, date, timedelta
from collections import defaultdict
from zoneinfo import ZoneInfo

import requests

PACIFIC = ZoneInfo("America/Los_Angeles")
CLOSE_API_KEY = os.environ["CLOSE_API_KEY"]

session = requests.Session()
session.auth = (CLOSE_API_KEY, "")
session.headers.update({"Content-Type": "application/json"})

# ── Custom Field IDs (mirrors fetch_and_build.py) ────────────────────────────
CF_FUNNEL_NAME   = "cf_xqDQE8fkPsWa0RNEve7hcaxKblCe6489XeZGRDzyPdX"  # Funnel Name DEAL (lead)
CF_FIRST_SALES   = "cf_LFdYEQ6bsgp49YjZzefypDmdVx8iwuakWDSLPLpVrBq"  # First Sales Call Booked Date (lead)
CF_BUSINESS_LINE = "cf_aJlNlilQZIgLLuhcymNN8fiOzewnFxrbWjLZFPmsucO"  # BTC Business Line (lead)

REACTIVATION_SCRAPERS_FUNNEL = "Reactivation Scrapers"

EXCLUDED_LEAD_STATUS_IDS = {
    "stat_hWIGHjzyNpl4YjIFSFz3VK4fp2ny10SFJLKAihmo4KT",  # Canceled (by Lead)
    "stat_YV4ZngDB4IGjLjlOf0YTFEWuKZJ6fhNxVkzQkvKYfdB",  # Outside the US
}

# Remove/comment out this line to include The Land Geek back in — matches
# the toggle in fetch_and_build.py's EXCLUDED_BUSINESS_LINES.
EXCLUDED_BUSINESS_LINES = {
    "The Land Geek (TLG)",
    "Publishing Profits Academy (PPA)",
}

# Excluded from the TOTAL only (matches the dashboard's KPI tiles) — not from
# the day-by-day breakdown output, so you can still see it there if present.
EXCLUDED_FROM_TOTALS_FUNNELS = {"LTF - Quiz Funnel"}

# Next Steps title patterns — mirrors fetch_and_build.py's
# NEXT_STEPS_TITLE_PATTERNS (sourced from AIMS-Product/close-first-sales-meeting's
# update_field.py, 2026-09-11). Detection AND attribution both come from title.
NEXT_STEPS_TITLE_PATTERNS = [
    (re.compile(r"vendingpren[eu]+rs?\s+-\s+next\s+steps\s+call", re.IGNORECASE),     "Charlie Ingram"),
    (re.compile(r"vendingpren[eu]+rs?\s+call\s+-\s+next\s+steps", re.IGNORECASE),     "Jacob Hepner"),
    (re.compile(r"vendingpren[eu]+rs?\s+next\s+steps\s+call", re.IGNORECASE),         "Vince Bartolini"),
    (re.compile(r"vendingpren[eu]+rs?\s+next\s+steps\s+session", re.IGNORECASE),      "Pearl Sathekge"),
    (re.compile(r"vendingpren[eu]+rs?\s+discovery\s+-\s+next\s+steps", re.IGNORECASE), "Kelly Schrader"),
    (re.compile(r"vendingpren[eu]+rs?\s+-\s+next\s+steps(?!\s+call)", re.IGNORECASE), "Jacob Herbig"),
    (re.compile(r"vendingpren[eu]+r\s+next\s+steps", re.IGNORECASE),                  "William Nowak"),
    (re.compile(r"vending\s+discovery\s+call\s+-\s+next\s+steps", re.IGNORECASE),     "August Young"),
    (re.compile(r"vending\s+discovery\s+-\s+next\s+steps", re.IGNORECASE),            "Spencer Reynolds"),
    (re.compile(r"vendingpren[eu]+rs?\s+strategy\s*-?\s*next\s+steps", re.IGNORECASE), "Amy Mulch"),
    (re.compile(r"vending\s+opportunity\s*-?\s*next\s+steps", re.IGNORECASE),          "Cassie Caraballo"),
    (re.compile(r"vendingpren[eu]+rs?\s+connect\s*-?\s*next\s+steps", re.IGNORECASE),  "Jessica Zatkin"),
    (re.compile(r"vending\s+success\s*-?\s*next\s+steps", re.IGNORECASE),              "Abigail Garza"),
    (re.compile(r"vendingpren[eu]+rs?\s+momentum\s*-?\s*next\s+steps", re.IGNORECASE), "Connor George"),
    (re.compile(r"vendingpren[eu]+rs?\s+launch\s*-?\s*next\s+steps", re.IGNORECASE),   "Dana Lesiuk"),
    (re.compile(r"vendingpren[eu]+rs?\s+pathway\s*-?\s*next\s+steps", re.IGNORECASE),  "Naria Torres"),
    (re.compile(r"vendingpren[eu]+rs?\s+blueprint\s*-?\s*next\s+steps", re.IGNORECASE), "Melia King"),
    (re.compile(r"vendingpren[eu]+rs?\s+compass\s*-?\s*next\s+steps", re.IGNORECASE),  "Josh Stoffel"),
    (re.compile(r"vendingpren[eu]+rs?\s+horizon\s*-?\s*next\s+steps", re.IGNORECASE),  "Beatrice Braescu Cojocaru"),
    (re.compile(r"vendingpren[eu]+rs?\s+elevate\s*-?\s*next\s+steps", re.IGNORECASE),  "Catalina"),
    (re.compile(r"vendingpren[eu]+rs?\s+catalyst\s*-?\s*next\s+steps", re.IGNORECASE), "Raiya"),
    (re.compile(r"vendingpren[eu]+rs?\s+clarity\s*-?\s*next\s+steps", re.IGNORECASE),  "Luna"),
]


def match_next_steps_setter(title):
    for pattern, setter in NEXT_STEPS_TITLE_PATTERNS:
        if pattern.search(title):
            return setter
    return None


def is_excluded_business_line(lead):
    raw = lead.get(f"custom.{CF_BUSINESS_LINE}")
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    val = str(raw).strip() if raw else ""
    return val in EXCLUDED_BUSINESS_LINES


def get_funnel_name(lead):
    raw = lead.get(f"custom.{CF_FUNNEL_NAME}")
    val = (raw or "").strip()
    return val if val else "Unknown (Needs Review)"


def close_get(endpoint, params=None):
    """GET from Close API with 0.5s throttle and 429 retry logic."""
    time.sleep(0.5)
    url = f"https://api.close.com/api/v1/{endpoint}"
    for attempt in range(5):
        resp = session.get(url, params=params or {}, timeout=60)
        if resp.status_code == 429:
            wait = float(resp.headers.get("Retry-After", 5))
            print(f"  Rate limited — waiting {wait}s...", flush=True)
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()


def fetch_booked_leads(start_date, end_date):
    """Leads where First Sales Call Booked Date falls in [start_date, end_date]."""
    start_str = start_date.strftime("%Y-%m-%d")
    end_str   = end_date.strftime("%Y-%m-%d")
    query = f'custom.{CF_FIRST_SALES} >= "{start_str}" AND custom.{CF_FIRST_SALES} <= "{end_str}"'
    print(f"Fetching booked leads ({start_str} → {end_str})...", flush=True)
    leads, skip = [], 0
    while True:
        data = close_get("lead/", {
            "query":   query,
            "_fields": (f"id,status_id,"
                        f"custom.{CF_FUNNEL_NAME},"
                        f"custom.{CF_FIRST_SALES},"
                        f"custom.{CF_BUSINESS_LINE}"),
            "_limit":  200,
            "_skip":   skip,
        })
        batch = data.get("data", [])
        leads.extend(batch)
        if not data.get("has_more"):
            break
        skip += 200
    print(f"  Total booked leads: {len(leads)}", flush=True)
    return leads


def fetch_reactivation_scraper_meetings(start_date, end_date):
    """Next Steps meetings for Reactivation Scrapers — pages through ALL
    meetings (no server-side date filter available) and filters client-side."""
    starts_min = datetime(start_date.year, start_date.month, start_date.day,
                          0, 0, 0, tzinfo=PACIFIC)
    starts_max = datetime(end_date.year, end_date.month, end_date.day,
                          23, 59, 59, tzinfo=PACIFIC)
    print(f"Fetching RS Next Steps meetings ({start_date} → {end_date})...", flush=True)
    results, scanned, skip = [], 0, 0
    while True:
        data = close_get("activity/meeting", {"_limit": 100, "_skip": skip})
        batch = data.get("data", [])
        if not batch:
            break
        for m in batch:
            scanned += 1
            starts_raw = m.get("starts_at") or ""
            if not starts_raw:
                continue
            try:
                starts_dt = datetime.fromisoformat(
                    starts_raw.replace("Z", "+00:00")
                ).astimezone(PACIFIC)
            except Exception:
                continue
            if not (starts_min <= starts_dt <= starts_max):
                continue
            title = (m.get("title") or "").strip()
            setter = match_next_steps_setter(title)
            if setter is None:
                continue
            results.append({"lead_id": m["lead_id"], "starts_at": starts_raw, "setter": setter})
        if not data.get("has_more"):
            break
        skip += 100
    print(f"  RS Next Steps meetings found: {len(results)} (scanned {scanned} total)", flush=True)
    return results


def fetch_lead(lead_id):
    return close_get(f"lead/{lead_id}", {
        "_fields": f"id,status_id,custom.{CF_FUNNEL_NAME},custom.{CF_BUSINESS_LINE}"
    })


def main():
    parser = argparse.ArgumentParser(description="Meetings Booked — per-day breakdown")
    parser.add_argument("--start", required=True, help="Start date, YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date, YYYY-MM-DD (inclusive)")
    args = parser.parse_args()

    start_date = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_date   = datetime.strptime(args.end, "%Y-%m-%d").date()
    if end_date < start_date:
        sys.exit("--end must be on or after --start")

    by_day        = defaultdict(int)             # day_str -> count (all funnels)
    by_day_funnel = defaultdict(lambda: defaultdict(int))  # day_str -> {funnel: count}
    lead_cache    = {}

    # ── Every funnel except Reactivation Scrapers: FSCBD-based ───────────────
    for lead in fetch_booked_leads(start_date, end_date):
        lid = lead.get("id")
        if not lid:
            continue
        lead_cache[lid] = lead
        if lead.get("status_id") in EXCLUDED_LEAD_STATUS_IDS:
            continue
        if is_excluded_business_line(lead):
            continue
        funnel = get_funnel_name(lead)
        if funnel == REACTIVATION_SCRAPERS_FUNNEL:
            continue  # RS uses the meeting-title methodology below, not FSCBD
        day_str = lead.get(f"custom.{CF_FIRST_SALES}")
        if not day_str:
            continue
        by_day_funnel[day_str][funnel] += 1
        if funnel not in EXCLUDED_FROM_TOTALS_FUNNELS:
            by_day[day_str] += 1

    # ── Reactivation Scrapers: title-matched meetings ─────────────────────────
    for mtg in fetch_reactivation_scraper_meetings(start_date, end_date):
        lid = mtg["lead_id"]
        lead = lead_cache.get(lid)
        if lead is None:
            lead = fetch_lead(lid)
            lead_cache[lid] = lead
        if lead.get("status_id") in EXCLUDED_LEAD_STATUS_IDS:
            continue
        if is_excluded_business_line(lead):
            continue
        if get_funnel_name(lead) != REACTIVATION_SCRAPERS_FUNNEL:
            continue  # title matched but lead isn't actually RS — skip
        starts_dt = datetime.fromisoformat(mtg["starts_at"].replace("Z", "+00:00")).astimezone(PACIFIC)
        day_str = starts_dt.strftime("%Y-%m-%d")
        by_day_funnel[day_str][REACTIVATION_SCRAPERS_FUNNEL] += 1
        by_day[day_str] += 1

    # ── Report ────────────────────────────────────────────────────────────────
    print()
    print(f"Meetings Booked by Day — {start_date} to {end_date}")
    print("=" * 56)
    total = 0
    d = start_date
    while d <= end_date:
        day_str = d.strftime("%Y-%m-%d")
        count = by_day.get(day_str, 0)
        total += count
        bar = "█" * count
        print(f"  {d.strftime('%a %Y-%m-%d')}   {count:>4}   {bar}")
        d += timedelta(days=1)
    print("-" * 56)
    print(f"  {'TOTAL':<24}{total:>4}")
    print()
    print("(LTF - Quiz Funnel is excluded from this total, matching the dashboard's")
    print(" KPI tiles — same as fetch_and_build.py's EXCLUDED_FROM_TOTALS_FUNNELS.")
    print(" It still shows up in the per-day funnel breakdown below.)")

    print()
    print("Per-day funnel breakdown:")
    print("=" * 56)
    d = start_date
    while d <= end_date:
        day_str = d.strftime("%Y-%m-%d")
        funnels = by_day_funnel.get(day_str, {})
        if funnels:
            print(f"  {d.strftime('%a %Y-%m-%d')}:")
            for funnel, count in sorted(funnels.items(), key=lambda kv: -kv[1]):
                flag = "  (excluded from total)" if funnel in EXCLUDED_FROM_TOTALS_FUNNELS else ""
                print(f"    {count:>4}  {funnel}{flag}")
        d += timedelta(days=1)


if __name__ == "__main__":
    main()
