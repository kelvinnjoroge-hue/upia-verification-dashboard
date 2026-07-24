#!/usr/bin/env python3
"""
Compact multi-day history store for the KE_UPIA ticket dashboard.

One file per calendar day (EAT) under a `history/` directory holds every
snapshot captured that day, compacted into short arrays instead of
repeated-key JSON objects -- at 15-minute cadence across many days the
per-record field-name overhead would otherwise dominate the file size.
`history/index.json` lists which day-files currently exist, both so the
GitHub Pages mirror's JS knows what it can fetch on demand and so old days
past the retention window get pruned.

Layout, relative to a history_dir (the GitHub Pages mirror checkout's
history/ subdirectory):
  index.json          -> {"days": ["2026-07-24", "2026-07-25", ...]}
  2026-07-24.json      -> {"workspaces": [...], "categories": [...],
                            "buckets": [...], "entries": [<compact entry>, ...]}

Each compact entry: {"t": "<ISO8601 generatedAt, EAT offset>",
                      "agents": [<responder id>, ...],
                      "rows": [[wsIdx, catIdx, bucketIdx, hasResponder(0/1),
                                hasFirstResponse(0/1), handlingSecsOrNull,
                                responderIdxOrNull], ...]}
Rows reference workspaces/categories/buckets by index (not name) and
responders by index into that entry's own `agents` list (not the raw
Freshservice id) purely to keep the encoding short -- none of this is an
attempt at obfuscation.
"""
import json, os
from datetime import datetime, timedelta

BUCKETS = ["resolved_approved", "returned", "declined", "in_progress", "other"]


def compact_entry(generated_at_iso, records, workspaces, categories):
    ws_index = {name: i for i, name in enumerate(workspaces)}
    cat_index = {name: i for i, name in enumerate(categories)}
    bucket_index = {b: i for i, b in enumerate(BUCKETS)}
    agent_ids, agent_pos = [], {}
    rows = []
    for r in records:
        responder_idx = None
        if r["hasResponder"]:
            rid = r["responder"]
            if rid not in agent_pos:
                agent_pos[rid] = len(agent_ids)
                agent_ids.append(rid)
            responder_idx = agent_pos[rid]
        rows.append([
            ws_index[r["workspace"]],
            cat_index[r["category"]],
            bucket_index[r["bucket"]],
            1 if r["hasResponder"] else 0,
            1 if r["hasFirstResponse"] else 0,
            r["handlingSecs"],
            responder_idx,
        ])
    return {"t": generated_at_iso, "agents": agent_ids, "rows": rows}


def _day_file(history_dir, day_str):
    return os.path.join(history_dir, f"{day_str}.json")


def load_day(history_dir, day_str, workspaces, categories):
    path = _day_file(history_dir, day_str)
    if not os.path.exists(path):
        return {"workspaces": workspaces, "categories": categories, "buckets": BUCKETS, "entries": []}
    with open(path) as f:
        return json.load(f)


def _bucket_key(iso, dedupe_minutes):
    dt = datetime.fromisoformat(iso)
    return dt.replace(minute=(dt.minute // dedupe_minutes) * dedupe_minutes, second=0, microsecond=0)


def append_entry(history_dir, day_str, entry, workspaces, categories, dedupe_minutes=15):
    """Appends entry to the day's file, replacing any existing entry whose
    timestamp rounds to the same dedupe_minutes bucket (so a re-run within
    the same interval overwrites rather than duplicates)."""
    os.makedirs(history_dir, exist_ok=True)
    day = load_day(history_dir, day_str, workspaces, categories)

    new_key = _bucket_key(entry["t"], dedupe_minutes)
    day["entries"] = [e for e in day["entries"] if _bucket_key(e["t"], dedupe_minutes) != new_key]
    day["entries"].append(entry)
    day["entries"].sort(key=lambda e: e["t"])

    with open(_day_file(history_dir, day_str), "w") as f:
        json.dump(day, f, separators=(",", ":"))
    return day


def update_index(history_dir, day_str, retention_days):
    """Registers day_str in index.json and prunes day-files older than
    retention_days. Returns the surviving list of day strings."""
    os.makedirs(history_dir, exist_ok=True)
    index_path = os.path.join(history_dir, "index.json")
    days = []
    if os.path.exists(index_path):
        with open(index_path) as f:
            days = json.load(f).get("days", [])
    if day_str not in days:
        days.append(day_str)
    days.sort()

    cutoff = (datetime.strptime(day_str, "%Y-%m-%d") - timedelta(days=retention_days)).strftime("%Y-%m-%d")
    kept = [d for d in days if d >= cutoff]
    removed = [d for d in days if d < cutoff]
    for d in removed:
        p = _day_file(history_dir, d)
        if os.path.exists(p):
            os.remove(p)

    with open(index_path, "w") as f:
        json.dump({"days": kept}, f)
    return kept


def recent_window(history_dir, now_dt, workspaces, categories, hours):
    """Compact entries from the last `hours` (up to and including now_dt),
    drawn from today's and (if the window straddles midnight) yesterday's
    day-file. Suitable for embedding directly in a page."""
    cutoff = now_dt - timedelta(hours=hours)
    days_to_check = sorted({cutoff.strftime("%Y-%m-%d"), now_dt.strftime("%Y-%m-%d")})
    entries = []
    for d in days_to_check:
        entries.extend(load_day(history_dir, d, workspaces, categories)["entries"])
    entries = [e for e in entries if datetime.fromisoformat(e["t"]) >= cutoff]
    entries.sort(key=lambda e: e["t"])
    return entries
