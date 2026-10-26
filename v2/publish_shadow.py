#!/usr/bin/env python3
"""Render the public V2 shadow page from a private local Close snapshot.

The public page uses the existing MTD dashboard template, but only receives
whitelisted aggregate fields. Raw Close rows and drilldowns are never embedded.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

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
)


def public_data(source: Path) -> dict[str, Any]:
    raw = json.loads(source.read_text())
    totals = {key: raw["totals"][key] for key in TOTAL_FIELDS}
    channels = []
    for row in raw["channels"]:
        channel = {key: row[key] for key in CHANNEL_FIELDS}
        channel["drilldowns"] = []
        for campaign in row.get("drilldowns", []):
            content_rows = []
            campaign_bookings = 0
            for content in campaign.get("content", []):
                # Use lead IDs only to deduplicate the aggregate qualification
                # count. No row-level values are included in public output.
                qualified_leads = {
                    str(meeting["lead_id"])
                    for meeting in content.get("rows", [])
                    if meeting.get("qualified") and meeting.get("lead_id")
                }
                content_rows.append({
                    "name": content["name"],
                    "bookings": content["bookings"],
                    "showed": content["showed"],
                    "qualified": len(qualified_leads),
                })
                campaign_bookings += content["bookings"]
            channel["drilldowns"].append({
                "campaign": campaign["campaign"],
                "bookings": campaign_bookings,
                "content": content_rows,
            })
        channels.append(channel)
    return {
        "generated_at": raw["generated_at"],
        "period": raw["period"],
        "rules_version": raw["rules_version"],
        "counted_meetings": raw["counted_meetings"],
        "excluded_repeat_candidates": raw["excluded_repeat_candidates"],
        "lead_source_note": (
            "Lead source is shown separately from meeting-title booking attribution. "
            "UTM campaign and content drilldowns show aggregate counts only."
        ),
        "totals": totals,
        "channels": channels,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the aggregate-only public V2 shadow page")
    parser.add_argument("--source", type=Path, default=PRIVATE_DATA, help="Private local data.json from build.py")
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error(f"Private V2 snapshot not found: {args.source}")

    data = public_data(args.source)
    serialized = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    serialized = serialized.replace("<", "\\u003c").replace(">", "\\u003e")
    html = TEMPLATE.read_text().replace("__V2_DATA__", serialized)
    OUTPUT.write_text(html)
    print(f"Built public-safe V2 page: {OUTPUT}")
    print(f"Snapshot: {data['generated_at']}; qualifying bookings: {data['totals']['bookings']}")
    print("Output contains aggregate metrics only; lead and meeting rows are excluded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
