"""V2 reporting periods and display metadata, independent of Close reads."""

from __future__ import annotations

import calendar
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PACIFIC = ZoneInfo("America/Los_Angeles")
ARCHIVE_START = date(2026, 10, 1)
MONTHLY_BOOKED_GOAL = 1241
MONTHLY_REVENUE_GOAL = 750000


@dataclass(frozen=True)
class ReportPeriod:
    kind: str
    start: date
    end: date  # Exclusive, in Pacific calendar dates.
    key: str

    def cutoff(self, now: datetime) -> datetime:
        return min(now.astimezone(PACIFIC), datetime.combine(self.end, time.min, PACIFIC))

    def view(self, now: datetime) -> dict:
        cutoff = self.cutoff(now)
        end = (cutoff - timedelta(microseconds=1)).date()
        return {
            "key": self.key, "kind": self.kind,
            "month": self.start.strftime("%Y-%m"),
            "start": self.start.isoformat(), "end": end.isoformat(),
            "end_exclusive": self.end.isoformat(),
            "frozen": cutoff < now or cutoff == datetime.combine(self.end, time.min, PACIFIC),
            "label": self.start.strftime("%B %Y") if self.kind == "month" else f"{self.start:%b} {self.start.day} – {end:%b} {end.day}, {end.year}",
        }


def report_periods(now: datetime) -> list[ReportPeriod]:
    """Cover October onward, including its opening partial Monday-Sunday week."""
    today = now.astimezone(PACIFIC).date()
    periods = []
    start = ARCHIVE_START
    while start <= today:
        end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        periods.append(ReportPeriod("month", start, end, start.strftime("%Y-%m")))
        start = end
    monday = ARCHIVE_START - timedelta(days=ARCHIVE_START.weekday())
    while monday <= today:
        end = monday + timedelta(days=7)
        periods.append(ReportPeriod("week", max(monday, ARCHIVE_START), end, f"week-{monday.isoformat()}"))
        monday = end
    return periods


def display_metadata(start: date, cutoff: datetime) -> dict:
    end = (cutoff.astimezone(PACIFIC) - timedelta(microseconds=1)).date()
    days = calendar.monthrange(start.year, start.month)[1]
    day = end.day if (end.year, end.month) == (start.year, start.month) else days
    working_days = sum(date(start.year, start.month, d).weekday() < 5 for d in range(1, days + 1))
    working_elapsed = sum(date(start.year, start.month, d).weekday() < 5 for d in range(1, day + 1))
    return {
        "day": day, "days": days,
        "working_days": working_days, "working_elapsed": working_elapsed,
        "elapsed_pct": round(100 * working_elapsed / working_days, 1) if working_days else 0,
    }


def current_goals() -> dict:
    return {
        "bookings": MONTHLY_BOOKED_GOAL,
        "revenue": MONTHLY_REVENUE_GOAL,
        "channels": json.loads((ROOT.parent / "goals.json").read_text()),
    }


def presentation(data: dict) -> dict:
    """Use Python's legacy rounding for both rendered pages and CSV exports."""
    goals, progress = data["goals"], data["progress"]
    for row in data["channels"]:
        goal = goals["channels"].get(row["channel"])
        projected = round(row["bookings"] / progress["day"] * progress["days"]) if row["bookings"] and progress["day"] else None
        row["display"] = {
            "projected": projected, "goal": goal,
            "goal_pct": round(100 * row["bookings"] / goal) if goal else None,
            "pace": "" if not goal or projected is None else "pace-exceed" if projected > goal else "pace-on" if projected == goal else "pace-behind",
        }
    data["goal_percentages"] = {
        "bookings": round(100 * data["totals"]["bookings"] / goals["bookings"]),
        "revenue": round(100 * data["totals"]["revenue"] / goals["revenue"]),
    }
    def formats(row):
        def percentage(numerator, denominator):
            return f"{100 * numerator / denominator:.1f}%" if denominator else "—"
        row["formats"] = {
            "show": percentage(row["showed"], row["bookings"]),
            "qualified": percentage(row["qualified"], row["showed"]),
            "qualified_booked": percentage(row["qualified"], row["bookings"]),
            "close": percentage(row["closed_won"], row["bookings"]),
            "qualified_close": percentage(row["closed_won"], row["qualified"]),
            "revenue": f"${row['revenue']:,.0f}",
            "average": f"${row['revenue'] / row['closed_won']:,.0f}" if row["closed_won"] else "—",
        }
    for row in [data["totals"], *data["channels"], *data.get("setters", []), *data.get("team", [])]:
        formats(row)
    for channel in data["channels"]:
        for row in channel["drilldowns"] + channel["packages"]:
            formats(row)
    data["arr_display"] = {"arr": f"${data['vendhub_arr']:,.0f}", "mrr": f"${data['vendhub_arr'] / 12:,.0f}"}
    return data
