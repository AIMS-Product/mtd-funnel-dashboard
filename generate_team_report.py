#!/usr/bin/env python3
"""
generate_team_report.py — Weekly Team Performance report (closer tiles + per-rep breakdown).

Usage:  python3 generate_team_report.py --start YYYY-MM-DD --end YYYY-MM-DD
Output: reports/team_report_YYYY-MM-DD_YYYY-MM-DD.csv

The window must be a FULL WEEK: exactly 7 consecutive days (end = start + 6).
Any start weekday is accepted (Fri–Thu to pair with the weekly funnel CSV,
or Mon–Sun to pair with the weekly archives).

Alignment with the rest of the repo
-----------------------------------
All exclusion rules (lead statuses, excluded won-owners, BTC Business Line,
LTF - Quiz Funnel) and Close field IDs are IMPORTED from generate_report.py,
so Team totals here tie out to reports/report_<start>_<end>.csv for the same
dates. If a matching weekly funnel CSV exists, a RECONCILIATION section is
written and any mismatch is flagged.

Metric definitions
------------------
  Booked      Leads with First Sales Call Booked Date in the window
              (net of Canceled (by Lead) / Outside the US; excl. TLG/PPA
              business lines and LTF - Quiz Funnel)
  Showed      Booked leads with First Call Show Up = Yes
  Qualified   Booked leads with Qualified (Opp) = Yes
  Closed Won  Sales-pipeline opps with date_won in the window (per opp)
  Revenue     Sum of won opp value (cents ÷ 100)
  Pipeline    Same basis as the Sales Manager Dashboard scorecard ("open leads"):
              ALL leads with Lead Owner = a closer AND Qualified (Opp) = Yes,
              excluding lead status Lost / Canceled (by Lead) / Outside the US /
              Closed-Won and any lead with a won Sales-pipeline opp.
              × PIPELINE_VALUE_PER_OPP × PIPELINE_WEIGHT (20%). Point-in-time
              snapshot at run time — NOT limited to the report window.
  Revenue Goal  Volume-based: Booked × GOAL_CLOSE_RATE_NET (13%) ×
                REVENUE_GOAL_AVG_DEAL ($7,000). Applied to the team and each rep.
  Show Rate               Showed ÷ Booked
  Close Rate (Net)        Closed Won ÷ Booked
  Close Rate (Qualified)  Closed Won ÷ Qualified

Rep attribution
---------------
  Booked / Showed / Qualified / Pipeline → lead's "Lead Owner" field
  Closed Won / Revenue                   → won opp's owner (user_id)
Anyone not in CLOSERS rolls into the "Other / Non-Closer" row, so the rep
rows + Other always sum to the Team numbers (except Pipeline, which is
closers-only by definition).
"""

import os, sys, csv, argparse
from datetime import datetime, date, timedelta
from pathlib import Path

# Shared rules + helpers — single source of truth with the weekly funnel CSV.
import generate_report as gr
from generate_report import (
    PACIFIC, CF_FIRST_SALES, CF_FUNNEL_NAME, CF_SHOW_UP, CF_QUALIFIED,
    CF_BUSINESS_LINE, PIPE_SALES, STAT_WON, EXCLUDED_LEAD_STATUS_IDS,
    EXCLUDED_WON_USER_IDS, EXCLUDED_FROM_TOTALS_FUNNELS,
    is_excluded_business_line, get_funnel_name, _is_yes, fmt_currency,
    fmt_ordinal, fetch_won_opps,
)

# ── Goals (weekly, team) ──────────────────────────────────────────────────────
# Revenue goal is volume-based (Joe): Booked × 13% × $7,000
# e.g. 150 booked → 19.5 deals × $7,000 = $136,500
REVENUE_GOAL_AVG_DEAL = 7_000
GOAL_PIPELINE         = 840_000
GOAL_SHOW_RATE        = 0.65
GOAL_CLOSE_RATE_NET   = 0.13   # Closed ÷ Booked (net)
GOAL_CLOSE_RATE_QUAL  = 0.20   # Closed ÷ Qualified

PIPELINE_VALUE_PER_OPP = 7_000  # $7,000 per open qualified opp (same avg deal as the revenue goal)
PIPELINE_WEIGHT        = 0.20   # Pipeline = 20% of gross (goal is set on the same 20% basis)

def revenue_goal(booked):
    return booked * GOAL_CLOSE_RATE_NET * REVENUE_GOAL_AVG_DEAL

def weighted_pipeline(open_opps):
    return open_opps * PIPELINE_VALUE_PER_OPP * PIPELINE_WEIGHT

# ── Closer roster (rep-dashboard REP_QUOTAS + Joe Dysert, who also takes calls
#    and closes deals) — everyone here gets a rep row and counts toward Pipeline ─
CLOSERS = [
    "Christian Hartwell",
    "Scott Seymour",
    "Robin Perkins",
    "Eric Piccione",
    "Joe Vaughan",
    "Shreya Bechra",
    "Luke Herman",
    "Ariella Irvine",
    "Oscar Pugh",
    "Joe Dysert",
]
OTHER_ROW = "Other / Non-Closer"

# Flag a non-closer Lead Owner with at least this many booked calls in the
# week — usually means a new closer who needs adding to CLOSERS.
NEW_CLOSER_FLAG_THRESHOLD = 3

# ── Close IDs used only here ──────────────────────────────────────────────────
CF_LEAD_OWNER = "cf_gOfS9pFwext58oberEegLyix8hZzeHrxhCZOVh3P3rd"

STAT_LEAD_LOST       = "stat_aR2jBa8YnTNZmHAnPsnlQuinBdaXpSBCkZGP3UvoBlV"
STAT_LEAD_CLOSED_WON = "stat_0oW3iRpVp9z5DJq0cuwI1HgR0XhHAhykEPPIq4TFsxd"
# Lead statuses that remove a qualified lead from Pipeline — matches
# CLOSED_LEAD_STATUSES in sales-manager-dashboard/scripts/fetch_data.py
PIPELINE_EXCLUDED_LEAD_STATUSES = EXCLUDED_LEAD_STATUS_IDS | {
    STAT_LEAD_LOST, STAT_LEAD_CLOSED_WON,
}

close_get = gr.close_get


# ── Helpers ───────────────────────────────────────────────────────────────────
def rate(num, den):
    return num / den if den else None

def fmt_rate(r):
    return "" if r is None else f"{r * 100:.1f}%"

def pct_of_goal(actual, goal):
    if actual is None or not goal:
        return ""
    return f"{actual / goal * 100:.0f}%"

def status_vs_goal(actual, goal):
    if actual is None:
        return "No Data"
    return "At/Above Goal" if actual >= goal else "Below Goal"

def fetch_org_users():
    """{user_id: full name}. Paginates — late-alphabet users sit on page 2+."""
    users, skip = {}, 0
    while True:
        data = close_get("user/", {"_limit": 100, "_skip": skip})
        for u in data.get("data", []):
            users[u["id"]] = " ".join(f"{u.get('first_name', '')} {u.get('last_name', '')}".split())
        if not data.get("has_more"):
            break
        skip += 100
    return users

def resolve_owner(raw, user_map):
    """Lead Owner may come back as a user id, a name, or a {id, name} dict."""
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    if not raw:
        return None
    if isinstance(raw, dict):
        uid = raw.get("id", "")
        if uid in user_map:
            return user_map[uid]
        name = " ".join(str(raw.get("name", "")).split())
        return name or None
    s = " ".join(str(raw).split())
    return user_map.get(s, s) or None

def bucket(name):
    return name if name in CLOSERS else OTHER_ROW

def fetch_open_qualified_by_closer():
    """Open qualified book per closer — same query and exclusions as
    fetch_open_leads_per_rep() in the Sales Manager Dashboard scorecard."""
    counts, dropped = {}, {"closed lead status": 0, "has won opp": 0}
    print("Fetching open qualified pipeline per closer...", flush=True)
    for rep_name in CLOSERS:
        n, skip = 0, 0
        while True:
            data = close_get("lead/", {
                "query":   f'"Lead Owner":"{rep_name}" "Qualified (Opp)":"Yes"',
                "_fields": "id,status_id,opportunities",
                "_limit":  200, "_skip": skip,
            })
            for lead in data.get("data", []):
                if lead.get("status_id") in PIPELINE_EXCLUDED_LEAD_STATUSES:
                    dropped["closed lead status"] += 1; continue
                if any(o.get("pipeline_id") == PIPE_SALES and o.get("status_id") == STAT_WON
                       for o in (lead.get("opportunities") or [])):
                    dropped["has won opp"] += 1; continue
                n += 1
            if not data.get("has_more"):
                break
            skip += 200
        counts[rep_name] = n
    print(f"  Open qualified leads: {sum(counts.values())} across {len(counts)} closers", flush=True)
    return counts, dropped


# ── Fetch ─────────────────────────────────────────────────────────────────────
def fetch_booked_leads(start_date, end_date):
    s, e = start_date.isoformat(), end_date.isoformat()
    query = f'custom.{CF_FIRST_SALES} >= "{s}" AND custom.{CF_FIRST_SALES} <= "{e}"'
    fields = ",".join([
        "id", "display_name", "status_id",
        f"custom.{CF_FUNNEL_NAME}", f"custom.{CF_SHOW_UP}", f"custom.{CF_QUALIFIED}",
        f"custom.{CF_BUSINESS_LINE}", f"custom.{CF_LEAD_OWNER}",
    ])
    print(f"Fetching booked leads ({s} → {e})...", flush=True)
    leads, skip = [], 0
    while True:
        data = close_get("lead/", {"query": query, "_fields": fields,
                                   "_limit": 200, "_skip": skip})
        leads.extend(data.get("data", []))
        if not data.get("has_more"):
            break
        skip += 200
    print(f"  Booked leads returned: {len(leads)}", flush=True)
    return leads


# ── Aggregate ─────────────────────────────────────────────────────────────────
def empty_row():
    return {"booked": 0, "showed": 0, "qualified": 0, "qual_open": 0,
            "closed": 0, "revenue": 0.0}

def aggregate(start_date, end_date):
    user_map = fetch_org_users()
    print(f"  Org users: {len(user_map)}", flush=True)

    reps = {name: empty_row() for name in CLOSERS}
    reps[OTHER_ROW] = empty_row()
    team = empty_row()

    notes = {
        "excluded_status": 0, "excluded_business_line": 0, "excluded_funnel": 0,
        "no_owner": 0, "pipeline_dropped": {},
        "other_owners_booked": {}, "other_owners_revenue": {},
        "won_excluded_user": 0, "won_excluded_bl": 0, "won_excluded_funnel": 0,
        "won_lead_lookup_failed": 0,
    }

    # Booked / Showed / Qualified / Pipeline (lead-level, by Lead Owner)
    for lead in fetch_booked_leads(start_date, end_date):
        if lead.get("status_id") in EXCLUDED_LEAD_STATUS_IDS:
            notes["excluded_status"] += 1; continue
        if is_excluded_business_line(lead):
            notes["excluded_business_line"] += 1; continue
        if get_funnel_name(lead) in EXCLUDED_FROM_TOTALS_FUNNELS:
            notes["excluded_funnel"] += 1; continue

        owner = resolve_owner(lead.get(f"custom.{CF_LEAD_OWNER}"), user_map)
        if not owner:
            notes["no_owner"] += 1
        row_key = bucket(owner or "")
        if row_key == OTHER_ROW:
            label = owner or "(no Lead Owner)"
            notes["other_owners_booked"][label] = notes["other_owners_booked"].get(label, 0) + 1

        showed    = _is_yes(lead.get(f"custom.{CF_SHOW_UP}"))
        qualified = _is_yes(lead.get(f"custom.{CF_QUALIFIED}"))

        for tgt in (team, reps[row_key]):
            tgt["booked"] += 1
            tgt["showed"] += showed
            tgt["qualified"] += qualified

    # Pipeline — open qualified book per closer (scorecard method, snapshot)
    open_counts, notes["pipeline_dropped"] = fetch_open_qualified_by_closer()
    for name, n in open_counts.items():
        reps[name]["qual_open"] = n
        team["qual_open"] += n

    # Closed Won / Revenue (per opp, by opp owner) — same rules as generate_report.py
    lead_cache, seen = {}, set()
    for opp in fetch_won_opps(start_date, end_date):
        if opp.get("user_id") in EXCLUDED_WON_USER_IDS:
            notes["won_excluded_user"] += 1; continue
        if opp["id"] in seen:
            continue
        seen.add(opp["id"])

        lid = opp.get("lead_id")
        if lid not in lead_cache:
            try:
                lead_cache[lid] = close_get(f"lead/{lid}/", {
                    "_fields": f"id,custom.{CF_FUNNEL_NAME},custom.{CF_BUSINESS_LINE}"})
            except Exception:
                lead_cache[lid] = {}
                notes["won_lead_lookup_failed"] += 1
        lead_obj = lead_cache[lid] or {}
        if lead_obj and is_excluded_business_line(lead_obj):
            notes["won_excluded_bl"] += 1; continue
        funnel = get_funnel_name(lead_obj) if lead_obj else "No Attribution"
        if funnel in EXCLUDED_FROM_TOTALS_FUNNELS:
            notes["won_excluded_funnel"] += 1; continue

        owner = user_map.get(opp.get("user_id"), "") or "(unknown user)"
        row_key = bucket(owner)
        value = (opp.get("value") or 0) / 100
        if row_key == OTHER_ROW:
            notes["other_owners_revenue"][owner] = notes["other_owners_revenue"].get(owner, 0) + value
        for tgt in (team, reps[row_key]):
            tgt["closed"] += 1
            tgt["revenue"] += value

    return team, reps, notes


# ── Reconciliation against the weekly funnel CSV ──────────────────────────────
def load_funnel_csv_totals(start, end):
    path = Path("reports") / f"report_{start}_{end}.csv"
    if not path.exists():
        return None, path
    wanted = {"Total Booked": "booked", "Showed": "showed", "Qualified": "qualified",
              "Closed Won": "closed", "Revenue": "revenue"}
    out, in_kpi = {}, False
    with open(path, newline="") as f:
        for row in csv.reader(f):
            if not row:
                continue
            if row[0].startswith("## "):
                in_kpi = row[0] == "## KPI SUMMARY"; continue
            if in_kpi and row[0] in wanted and len(row) > 1:
                raw = row[1].replace("$", "").replace(",", "").strip()
                try:
                    out[wanted[row[0]]] = float(raw)
                except ValueError:
                    pass
    return out, path


# ── CSV ───────────────────────────────────────────────────────────────────────
def write_csv(start_date, end_date, team, reps, notes):
    out_dir = Path("reports"); out_dir.mkdir(exist_ok=True)
    start, end = start_date.isoformat(), end_date.isoformat()
    fname = out_dir / f"team_report_{start}_{end}.csv"

    team_pipeline_gross = team["qual_open"] * PIPELINE_VALUE_PER_OPP
    team_pipeline   = weighted_pipeline(team["qual_open"])
    team_rev_goal   = revenue_goal(team["booked"])
    team_show       = rate(team["showed"], team["booked"])
    team_close_net  = rate(team["closed"], team["booked"])
    team_close_qual = rate(team["closed"], team["qualified"])
    warnings = []

    with open(fname, "w", newline="") as f:
        w = csv.writer(f)

        # ── Metadata ──────────────────────────────────────────────────────────
        w.writerow(["## REPORT METADATA"])
        w.writerow(["Report", "Team Performance — Closers"])
        w.writerow(["Start Date", start])
        w.writerow(["End Date", end])
        w.writerow(["Week Ending", fmt_ordinal(end_date)])
        w.writerow(["Date Range Label",
                    f"{start_date.strftime('%B %-d')} – {end_date.strftime('%B %-d, %Y')}"])
        w.writerow(["Generated At", datetime.now(PACIFIC).strftime("%B %-d, %Y at %-I:%M %p PT")])
        w.writerow(["Pipeline Value Per Qualified Opp", fmt_currency(PIPELINE_VALUE_PER_OPP)])
        w.writerow(["Pipeline Weight", f"{PIPELINE_WEIGHT * 100:.0f}%"])
        w.writerow(["Pipeline Basis", "Open qualified book as of Generated At (snapshot, not limited to the week)"])
        w.writerow(["Revenue Goal Basis",
                    f"Booked × {GOAL_CLOSE_RATE_NET * 100:.0f}% × {fmt_currency(REVENUE_GOAL_AVG_DEAL)} "
                    f"= {team['booked'] * GOAL_CLOSE_RATE_NET:.1f} deals × {fmt_currency(REVENUE_GOAL_AVG_DEAL)}"])
        w.writerow(["Closers", "; ".join(CLOSERS)])
        w.writerow([])

        # ── Top tiles ─────────────────────────────────────────────────────────
        w.writerow(["## TEAM KPI TILES"])
        w.writerow(["Tile", "Actual", "Goal", "% of Goal", "Status", "Numerator", "Denominator", "Definition"])
        w.writerow(["Team Revenue Closed", fmt_currency(team["revenue"]), fmt_currency(team_rev_goal),
                    pct_of_goal(team["revenue"], team_rev_goal), status_vs_goal(team["revenue"], team_rev_goal),
                    team["closed"], team["booked"],
                    f"Won opp value in window (numerator = deals). Goal = Booked × "
                    f"{GOAL_CLOSE_RATE_NET * 100:.0f}% × {fmt_currency(REVENUE_GOAL_AVG_DEAL)} (denominator = booked)"])
        w.writerow(["Team Pipeline", fmt_currency(team_pipeline), fmt_currency(GOAL_PIPELINE),
                    pct_of_goal(team_pipeline, GOAL_PIPELINE), status_vs_goal(team_pipeline, GOAL_PIPELINE),
                    team["qual_open"], "", f"All open qualified leads owned by closers (snapshot) × "
                    f"{fmt_currency(PIPELINE_VALUE_PER_OPP)} × {PIPELINE_WEIGHT * 100:.0f}%"])
        w.writerow(["Team Show Rate", fmt_rate(team_show), fmt_rate(GOAL_SHOW_RATE),
                    pct_of_goal(team_show, GOAL_SHOW_RATE), status_vs_goal(team_show, GOAL_SHOW_RATE),
                    team["showed"], team["booked"], "Showed ÷ Booked"])
        w.writerow(["Team Close Rate (Booked → Closed, Net)", fmt_rate(team_close_net), fmt_rate(GOAL_CLOSE_RATE_NET),
                    pct_of_goal(team_close_net, GOAL_CLOSE_RATE_NET), status_vs_goal(team_close_net, GOAL_CLOSE_RATE_NET),
                    team["closed"], team["booked"], "Closed Won ÷ Booked (net of Canceled / Outside US)"])
        w.writerow(["Team Close Rate (Qualified → Closed)", fmt_rate(team_close_qual), fmt_rate(GOAL_CLOSE_RATE_QUAL),
                    pct_of_goal(team_close_qual, GOAL_CLOSE_RATE_QUAL), status_vs_goal(team_close_qual, GOAL_CLOSE_RATE_QUAL),
                    team["closed"], team["qualified"], "Closed Won ÷ Qualified"])
        w.writerow([])

        # ── Supporting counts ─────────────────────────────────────────────────
        w.writerow(["## TEAM COUNTS"])
        w.writerow(["Metric", "Value"])
        w.writerow(["Booked", team["booked"]])
        w.writerow(["Showed", team["showed"]])
        w.writerow(["Qualified", team["qualified"]])
        w.writerow(["Qual Rate (Qualified ÷ Showed)", fmt_rate(rate(team["qualified"], team["showed"]))])
        w.writerow(["Open Qualified Opps (Closers)", team["qual_open"]])
        w.writerow(["Pipeline (Gross, before 20%)", fmt_currency(team_pipeline_gross)])
        w.writerow(["Revenue Goal (Deals Needed)", f"{team['booked'] * GOAL_CLOSE_RATE_NET:.1f}"])
        w.writerow(["Closed Won", team["closed"]])
        w.writerow(["Avg Deal", fmt_currency(team["revenue"] / team["closed"]) if team["closed"] else ""])
        w.writerow([])

        # ── Rep breakdown ─────────────────────────────────────────────────────
        w.writerow(["## REP BREAKDOWN"])
        w.writerow(["Rep", "Revenue", "Revenue Goal", "% of Rev Goal", "Closed Won", "Avg Deal",
                    "Pipeline", "Open Qualified Opps",
                    "Booked", "Showed", "Show %", "Qualified", "Qual %",
                    "Close % (Booked → Closed, Net)", "Close % (Qualified → Closed)"])

        def rep_line(name, r, is_other=False):
            return [
                name, fmt_currency(r["revenue"]), fmt_currency(revenue_goal(r["booked"])),
                pct_of_goal(r["revenue"], revenue_goal(r["booked"])), r["closed"],
                fmt_currency(r["revenue"] / r["closed"]) if r["closed"] else "",
                "" if is_other else fmt_currency(weighted_pipeline(r["qual_open"])),
                "" if is_other else r["qual_open"],
                r["booked"], r["showed"], fmt_rate(rate(r["showed"], r["booked"])),
                r["qualified"], fmt_rate(rate(r["qualified"], r["showed"])),
                fmt_rate(rate(r["closed"], r["booked"])),
                fmt_rate(rate(r["closed"], r["qualified"])),
            ]

        closer_rows = sorted(((n, reps[n]) for n in CLOSERS),
                             key=lambda x: (-x[1]["revenue"], -x[1]["booked"], x[0]))
        for name, r in closer_rows:
            w.writerow(rep_line(name, r))
        w.writerow(rep_line(OTHER_ROW, reps[OTHER_ROW], is_other=True))
        w.writerow(rep_line("TOTAL", team))
        w.writerow([])

        # ── Reconciliation ────────────────────────────────────────────────────
        # Self-check: closers + Other must equal Team
        for k in ("booked", "showed", "qualified", "closed", "revenue"):
            s = sum(reps[n][k] for n in CLOSERS) + reps[OTHER_ROW][k]
            if abs(s - team[k]) > 0.01:
                warnings.append(f"Rep rows don't sum to Team for {k}: {s} vs {team[k]}")

        funnel_totals, funnel_path = load_funnel_csv_totals(start, end)
        w.writerow(["## RECONCILIATION"])
        if funnel_totals is None:
            w.writerow([f"No weekly funnel CSV found at {funnel_path} — run Generate Weekly Report "
                        f"for the same dates to reconcile."])
        else:
            w.writerow(["Metric", "This Report", "Weekly Funnel CSV", "Difference", "Match"])
            for label, key in (("Booked", "booked"), ("Showed", "showed"), ("Qualified", "qualified"),
                               ("Closed Won", "closed"), ("Revenue", "revenue")):
                mine = round(team[key]) if key == "revenue" else team[key]
                theirs = funnel_totals.get(key)
                if theirs is None:
                    w.writerow([label, mine, "", "", "n/a"]); continue
                diff = mine - theirs
                ok = abs(diff) < (1 if key == "revenue" else 0.5)
                w.writerow([label, mine, int(theirs), int(diff), "YES" if ok else "NO"])
                if not ok:
                    warnings.append(f"{label} differs from {funnel_path.name} by {int(diff)} "
                                    f"(CRM fields may have changed since that CSV was generated)")
        w.writerow([])

        # ── Data notes / anomaly flags ────────────────────────────────────────
        w.writerow(["## DATA NOTES"])
        w.writerow(["Booked leads excluded — Canceled / Outside US status", notes["excluded_status"]])
        w.writerow(["Booked leads excluded — business line (TLG/PPA)", notes["excluded_business_line"]])
        w.writerow(["Booked leads excluded — LTF - Quiz Funnel", notes["excluded_funnel"]])
        w.writerow(["Booked leads with no Lead Owner (in Other row)", notes["no_owner"]])
        for why, n in sorted(notes["pipeline_dropped"].items()):
            w.writerow([f"Closer qualified leads not in Pipeline — {why}", n])
        w.writerow(["Won opps excluded — excluded owner", notes["won_excluded_user"]])
        w.writerow(["Won opps excluded — business line (TLG/PPA)", notes["won_excluded_bl"]])
        w.writerow(["Won opps excluded — LTF - Quiz Funnel", notes["won_excluded_funnel"]])
        if notes["won_lead_lookup_failed"]:
            w.writerow(["Won opps whose lead lookup failed (counted as No Attribution)",
                        notes["won_lead_lookup_failed"]])
            warnings.append(f"{notes['won_lead_lookup_failed']} won opp lead lookup(s) failed")
        for owner, n in sorted(notes["other_owners_booked"].items(), key=lambda x: -x[1]):
            w.writerow([f"Other row — booked owned by {owner}", n])
            if owner != "(no Lead Owner)" and n >= NEW_CLOSER_FLAG_THRESHOLD:
                warnings.append(f"{owner} owns {n} booked calls but isn't in CLOSERS — new closer?")
        for owner, v in sorted(notes["other_owners_revenue"].items(), key=lambda x: -x[1]):
            w.writerow([f"Other row — revenue closed by {owner}", fmt_currency(v)])
        w.writerow([])

        w.writerow(["## WARNINGS"])
        if warnings:
            for msg in warnings:
                w.writerow([f"⚠️ {msg}"])
        else:
            w.writerow(["None"])

    print(f"\nWritten: {fname}", flush=True)
    for msg in warnings:
        print(f"  ⚠️ {msg}", flush=True)
    return fname


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True, help="Week start YYYY-MM-DD")
    p.add_argument("--end",   required=True, help="Week end YYYY-MM-DD (start + 6 days)")
    args = p.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date   = date.fromisoformat(args.end)
    if end_date != start_date + timedelta(days=6):
        sys.exit(f"ERROR: window must be a full week (7 days). {args.start} → {args.end} is "
                 f"{(end_date - start_date).days + 1} day(s); expected end date "
                 f"{(start_date + timedelta(days=6)).isoformat()}.")
    if end_date > datetime.now(PACIFIC).date():
        print(f"  ⚠️ End date {args.end} is in the future — the week isn't complete yet.", flush=True)

    print(f"\n=== Team performance report: {args.start} → {args.end} ===\n", flush=True)
    team, reps, notes = aggregate(start_date, end_date)
    write_csv(start_date, end_date, team, reps, notes)

if __name__ == "__main__":
    main()
