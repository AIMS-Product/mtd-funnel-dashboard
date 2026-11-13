"""Shared reporting scopes and aggregate drilldowns over accepted V2 credits."""

from collections import defaultdict

SCHEMA_VERSION = 3
BOOKING_SCOPE = "vp-closers.v1"
APPOINTMENT_BOOKING_SCOPE = "vp-appointments.v2"
VP_BOOKING_CLOSERS = (
    "Christian Hartwell", "Scott Seymour", "Robin Perkins", "Eric Piccione",
    "Joe Vaughan", "Shreya Bechra", "Luke Herman", "Ariella Irvine", "Joe Dysert",
)
CLOSERS = (
    "Christian Hartwell", "Scott Seymour", "Robin Perkins", "Eric Piccione",
    "Joe Vaughan", "Shreya Bechra", "Luke Herman", "Ariella Irvine",
    "Oscar Pugh", "Joe Dysert",
)
OTHER_OWNER = "Other / Non-Closer"
METRICS = ("bookings", "marketing", "lane2", "social_dms", "showed", "qualified", "closed_won", "revenue")


def owner_name(value, users):
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        value = value.get("id") or value.get("name")
    value = " ".join(str(value or "").split())
    # Unresolved user IDs never appear in public reports.
    return users.get(value, "Unassigned" if value.startswith("user_") or not value else value)


def vp_closer_bookings(bookings, users):
    """Historical Lead Owner scope, retained for reconciled frozen archives."""
    return [row for row in bookings if owner_name(row.get("owner"), users) in VP_BOOKING_CLOSERS]


def vp_appointment_bookings(bookings, users):
    """Scope live bookings to VP offers and attribute them to the meeting user."""
    selected = []
    for row in bookings:
        if 'business_line' not in row:
            raise ValueError('VP appointment scope requires the source offer field')
        # The established offer policy reports verified blanks within VP.
        if row['business_line'] not in (None, '', 'Vendingpreneurs (VP)'):
            continue
        closer = row.get('appointment_closer')
        if isinstance(closer, str) and users.get(closer) in VP_BOOKING_CLOSERS:
            selected.append({**row, 'owner': closer})
    return selected


def booking_scope_label(scope):
    if scope == APPOINTMENT_BOOKING_SCOPE:
        return 'VP leads · appointment closer'
    if scope == BOOKING_SCOPE:
        return 'VP closer bookings · Lead Owner'
    return 'All-owner bookings · historical snapshot'


def rollup(bookings, won, key):
    groups = defaultdict(lambda: {**dict.fromkeys(METRICS, 0), "qualified_ids": set()})
    for row in bookings:
        group = groups[key(row)]
        group["bookings"] += 1
        group[{"Marketing": "marketing", "Lane 2": "lane2", "Social DMs": "social_dms"}[row["bucket"]]] += 1
        group["showed"] += int(row["showed"])
        if row["qualified"]:
            group["qualified_ids"].add(row["lead_id"])
    for row in won:
        group = groups[key(row)]
        group["closed_won"] += 1
        group["revenue"] += row["revenue"]
    result = []
    for value, group in groups.items():
        group["qualified"] = len(group.pop("qualified_ids"))
        result.append({"value": value, **group})
    return sorted(result, key=lambda row: (-row["bookings"], -row["revenue"], row["value"]))


def qualified_owner_counts(rows, owner_key=lambda row: row['owner']):
    """Allocate the distinct source/lead cohort using its stable meeting identity."""
    counts = defaultdict(int)
    seen = set()
    for row in sorted(rows, key=lambda row: row['meeting_id']):
        identity = (row['channel'], row['lead_id'])
        if row['qualified'] and identity not in seen:
            counts[owner_key(row)] += 1
            seen.add(identity)
    return counts


def build_breakdowns(bookings, won, users, *, appointment_qualification=False):
    channels = sorted({row["channel"] for row in bookings + won})
    details = {}
    for channel in channels:
        booked = [row for row in bookings if row["channel"] == channel]
        closed = [row for row in won if row["channel"] == channel]
        field = "utm_content" if channel == "Internal Webinar" else "utm_campaign"
        details[channel] = {
            "drilldowns": rollup(booked, closed, lambda row: row[field]),
            "packages": rollup([], closed, lambda row: row["package"]),
            "setters": rollup(booked, closed, lambda row: owner_name(row["setter"], users)),
        }
    setters = rollup(bookings, won, lambda row: owner_name(row["setter"], users))
    team = rollup(bookings, won, lambda row: owner_name(row["owner"], users)
                  if owner_name(row["owner"], users) in CLOSERS else OTHER_OWNER)
    if appointment_qualification:
        qualified = qualified_owner_counts(bookings, lambda row: owner_name(row['owner'], users))
        for row in team:
            row['qualified'] = qualified.get(row['value'], 0)
    return {"channels": details, "setters": setters, "team": team}
