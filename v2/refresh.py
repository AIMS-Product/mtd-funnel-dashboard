#!/usr/bin/env python3
"""Refresh V2 and retain aggregate-only monthly and weekly archives."""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime
from pathlib import Path

from build import CloseReader, build_dataset, load_api_key
from publish_shadow import public_data, render_report
from reporting import PACIFIC, ROOT, report_periods
from aggregates import SCHEMA_VERSION
from reports import pipeline_snapshot, write_exports, write_comparison
from archive_ui import write_navigation
from supplemental import retain_history

ARCHIVES = ROOT / "archives"


def refresh(now: datetime | None = None, *, render_only: bool = False) -> None:
    now = now or datetime.now(PACIFIC)
    ARCHIVES.mkdir(exist_ok=True)
    periods = report_periods(now)
    reader = None
    pipeline = None
    reports = []
    for period in periods:
        path = ARCHIVES / f"data-{period.key}.json"
        saved = json.loads(path.read_text()) if path.exists() else None
        view = period.view(now)
        # Re-read the just-completed period once at rollover, then retain it.
        if not render_only and (not saved or saved.get("schema_version") != SCHEMA_VERSION or not saved["view"]["frozen"]):
            reader = reader or CloseReader(load_api_key())
            print(f"Building V2 {period.key}: {period.start} through {view['end']}", flush=True)
            raw = build_dataset(reader, period.cutoff(now), period.start)
            raw["generated_at"] = now.isoformat()
            # Only the publisher's explicit aggregate whitelist can cross this boundary.
            with tempfile.TemporaryDirectory(prefix="mtd-v2-private-") as directory:
                source = Path(directory) / "data.json"
                source.write_text(json.dumps(raw))
                saved = {**public_data(source), "view": view}
            if raw.get("breakdowns") is not None:
                pipeline = pipeline or pipeline_snapshot(reader, now)
                saved["pipeline"] = pipeline
            path.write_text(json.dumps(saved, ensure_ascii=False, indent=2) + "\n")
        if saved:
            reports.append(saved)

    live_month = now.astimezone(PACIFIC).strftime("%Y-%m")
    navigation = {
        "months": [{**r["view"], "live": r["view"]["key"] == live_month} for r in reports if r["view"]["kind"] == "month"],
        "weeks": [r["view"] for r in reports if r["view"]["kind"] == "week"],
    }
    navigation = retain_history(navigation, ARCHIVES)
    (ARCHIVES / "nav.json").write_text(json.dumps(navigation, indent=2) + "\n")
    write_navigation(navigation, ARCHIVES)
    for report in reports:
        view = report["view"]
        render_report(report, ARCHIVES / f"{view['key']}.html", navigation)
        if view["kind"] == "month" and view["key"] == live_month:
            render_report(report, ROOT / "index.html", navigation)
        if view["kind"] == "week" and not view["frozen"]:
            render_report(report, ARCHIVES / "week-current.html", navigation)
        write_exports(report, ROOT / "reports", view["key"])
    write_comparison(reports, ARCHIVES / "mom.html")
    print("Published V2 monthly/weekly views; detailed Close rows remain private.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--render-only", action="store_true", help="Render existing aggregate archives without Close reads")
    args = parser.parse_args()
    refresh(render_only=args.render_only)
