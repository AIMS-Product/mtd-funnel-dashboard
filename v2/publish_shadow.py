#!/usr/bin/env python3
"""Render the public V2 shadow page from a private local Close snapshot.

The public page uses the existing MTD dashboard template, but only receives
whitelisted aggregate fields. Raw Close rows are never embedded; only plain attribution values and counts are included.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from datetime import date, datetime
from reporting import current_goals, display_metadata

ROOT = Path(__file__).resolve().parent
PRIVATE_DATA = ROOT / "public" / "data.json"
TEMPLATE = ROOT / "public" / "index.template.html"
OUTPUT = ROOT / "index.html"
TOTAL_FIELDS = (
    "leads_created", "bookings", "marketing", "lane2", "social_dms",
    "showed", "qualified", "closed_won", "revenue",
)
CHANNEL_FIELDS = (
    "channel", "leads_created", "bookings", "marketing", "lane2",
    "social_dms", "showed", "qualified", "closed_won", "revenue",
    "unrecoverable_booked_leads",
)


def public_data(source: Path) -> dict[str, Any]:
    raw = json.loads(source.read_text())
    totals = {key: raw["totals"][key] for key in TOTAL_FIELDS}
    channels = []
    for row in raw["channels"]:
        channel = {key: row[key] for key in CHANNEL_FIELDS}
        channel["drilldowns"] = []
        if channel["channel"] == "Internal Webinar":
            # Webinar attribution is reviewed at the content level; omit the
            # campaign layer and show each UTM content value directly.
            values: dict[str, int] = {}
            for campaign in row.get("drilldowns", []):
                for content in campaign.get("content", []):
                    value = content["name"]
                    values[value] = values.get(value, 0) + content["bookings"]
            channel["drilldowns"] = [
                {"value": value, "bookings": bookings}
                for value, bookings in sorted(values.items(), key=lambda item: (-item[1], item[0]))
            ]
            channels.append(channel)
            continue
        for campaign in row.get("drilldowns", []):
            campaign_bookings = 0
            for content in campaign.get("content", []):
                campaign_bookings += content["bookings"]
            channel["drilldowns"].append({
                "value": campaign["campaign"],
                "bookings": campaign_bookings,
            })
        channels.append(channel)
    start = date.fromisoformat(raw["period"].split(" through ")[0])
    cutoff = raw.get("source_cutoff", raw["generated_at"])
    return {
        "generated_at": raw["generated_at"],
        "source_cutoff": cutoff,
        "vendhub_arr": raw.get("vendhub_arr", 0.0),
        "progress": display_metadata(start, datetime.fromisoformat(cutoff)),
        "goals": current_goals(),
        "period": raw["period"],
        "rules_version": raw["rules_version"],
        "counted_meetings": raw["counted_meetings"],
        "excluded_repeat_candidates": raw["excluded_repeat_candidates"],
        "attribution_reviewed_at": raw.get("attribution_reviewed_at"),
        "lead_source_note": (
            "Lead source is shown separately from meeting-title booking attribution. "
            "Attribution values show aggregate counts only."
        ),
        "totals": totals,
        "channels": channels,
    }


def render_report(data: dict[str, Any], output: Path, navigation: dict | None = None) -> None:
    page = {**data, "navigation": navigation or {"months": [], "weeks": []}}
    serialized = json.dumps(page, ensure_ascii=False, separators=(",", ":"))
    serialized = serialized.replace("<", "\\u003c").replace(">", "\\u003e")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(TEMPLATE.read_text().replace("__V2_DATA__", serialized))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the aggregate-only public V2 shadow page")
    parser.add_argument("--source", type=Path, default=PRIVATE_DATA, help="Private local data.json from build.py")
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error(f"Private V2 snapshot not found: {args.source}")

    data = public_data(args.source)
    render_report(data, OUTPUT)
    print(f"Built public-safe V2 page: {OUTPUT}")
    print(f"Snapshot: {data['generated_at']}; qualifying bookings: {data['totals']['bookings']}")
    print("Output contains aggregate metrics only; lead and meeting rows are excluded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
