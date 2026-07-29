#!/usr/bin/env python3
"""
KE_UPIA Ticket Operations -- Live Ticket Dashboard (CI build)

Runs via GitHub Actions every 15 minutes (see .github/workflows/refresh.yml)
directly in this repo's checkout. This repo *is* the history store and the
GitHub Pages site, so there's no separate mirror to sync to -- fetch, write
history/, write index.html, and the workflow commits+pushes.

This is the CI-adapted twin of ~/.freshservice-tracker/upia_verification_dashboard.py
(the copy used for local/manual rebuilds and as the reference the claude.ai
Artifact's cloud RemoteTrigger routine is kept in sync with). Differences,
both because this file lives in a PUBLIC repo:
  - FS_API_KEY is read from the environment ONLY -- no hardcoded fallback.
    The other copies default to a real key because they live in Kelvin's
    private freshservice-reports repo / are never committed anywhere public;
    committing that same fallback here would leak the live API key.
  - History dir, template, and output path are all relative to this repo
    root (the GitHub Actions checkout), not an absolute path under
    Kelvin's home directory.

See project memory (project_upia_verification_dashboard.md) for the full
history-store design, the compact row encoding, and why the claude.ai
Artifact and this mirror have different history-browsing capabilities.
"""
import os, sys, json, ssl, base64, urllib.request, urllib.error, time
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import history_store as hstore
from branch_whitelist import canonical_branch
from delay_classify import classify as classify_delay_driver

EAT = timezone(timedelta(hours=3))
API_KEY = os.environ.get("FS_API_KEY")
if not API_KEY:
    raise SystemExit("FS_API_KEY environment variable is required (set as a repo secret) -- refusing to run without it")
DOMAIN = os.environ.get("FS_DOMAIN", "https://4gcapital.freshservice.com")

HISTORY_DIR = os.path.join(HERE, "history")
TEMPLATE_PATH = os.path.join(HERE, "dashboard_template.html")
OUTPUT_PATH = os.path.join(HERE, "index.html")
# TODO: switch to "https://dashboard.4g-capital.com/" once the DNS CNAME
# record (dashboard.4g-capital.com -> kelvinnjoroge-hue.github.io, in Route 53)
# is live -- attempting the custom domain before DNS resolved caused GitHub
# Pages to 301-redirect the working github.io URL to the not-yet-resolving
# custom domain, taking the site offline, so this was reverted (2026-07-29).
MIRROR_URL = "https://kelvinnjoroge-hue.github.io/upia-verification-dashboard/"

WORKSPACES = [
    {"id": 15, "name": "KE_UPIA_Verification"},
    {"id": 6, "name": "KE_UPIA_Edit Bio Data"},
    {"id": 8, "name": "KE_UPIA_Dormant Reactivation"},
    {"id": 13, "name": "KE_UPIA_Reference Check"},
]

ST_OPEN, ST_PENDING, ST_RESOLVED, ST_CLOSED = 2, 3, 4, 5
ST_OPS_APPROVAL, ST_APPROVED, ST_REJECTED, ST_RETURNED = 6, 7, 8, 9

RESOLVED_APPROVED = {ST_RESOLVED, ST_CLOSED, ST_APPROVED}
RETURNED = {ST_RETURNED}
DECLINED = {ST_REJECTED}
IN_PROGRESS = {ST_OPEN, ST_PENDING, ST_OPS_APPROVAL}

CATEGORIES = ["Verification", "Mpesa checks", "Dormant reactivation", "Edit biodata"]
BUCKETS = hstore.BUCKETS

RETENTION_DAYS = 30
RECENT_WINDOW_HOURS = 24

_REQUEST_PACING_SECS = 0.3

CLASSIFICATION_CACHE_NAME = "delay_classifications.json"
NLV_SUB_CATEGORY = "New Loan Verification"
DORMANT_WORKSPACE = "KE_UPIA_Dormant Reactivation"
MAX_NEW_CLASSIFICATIONS_PER_RUN = 150


def delay_driver_group(record):
    """Which delay-driver breakdown panel a ticket belongs to, or None if
    ineligible. See the org-hosted build_dashboard.py for the full rationale
    (calibrated against real conversation samples per group)."""
    if record["workspace"] == "KE_UPIA_Verification" and record["subCategory"] == NLV_SUB_CATEGORY:
        return "New Loan Verification"
    if record["workspace"] == DORMANT_WORKSPACE:
        return "Dormant Reactivation"
    return None


def categorize(subject):
    s = (subject or "").lower()
    if "mpesa" in s or "m-pesa" in s:
        return "Mpesa checks"
    if "dormant" in s:
        return "Dormant reactivation"
    if "biodata" in s or "bio data" in s or "bio-data" in s or "edit bio" in s:
        return "Edit biodata"
    return "Verification"


def bucket_for(status):
    if status in RESOLVED_APPROVED:
        return "resolved_approved"
    if status in RETURNED:
        return "returned"
    if status in DECLINED:
        return "declined"
    if status in IN_PROGRESS:
        return "in_progress"
    return "other"


def _api_get(path, retries=3, rate_limit_retries=6):
    url = f"{DOMAIN}{path}"
    creds = base64.b64encode(f"{API_KEY}:X".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {creds}"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    net_attempt = 0
    rate_limit_attempt = 0
    while True:
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=45) as r:
                data = json.loads(r.read())
            time.sleep(_REQUEST_PACING_SECS)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 429:
                rate_limit_attempt += 1
                if rate_limit_attempt > rate_limit_retries:
                    raise
                retry_after = e.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else min(60, 5 * rate_limit_attempt)
                print(f"  [warn] 429 rate limited -- waiting {wait}s (retry {rate_limit_attempt}/{rate_limit_retries})...")
                time.sleep(wait)
                continue
            raise
        except (TimeoutError, OSError) as e:
            net_attempt += 1
            if net_attempt > retries:
                raise
            print(f"  [warn] API request failed ({e}) -- retry {net_attempt}/{retries}...")
            time.sleep(3)


def fetch_today_tickets_for_workspace(workspace_id, today_start):
    tickets = []
    page = 1
    while True:
        data = _api_get(
            f"/api/v2/tickets?workspace_id={workspace_id}&include=stats,requester"
            f"&order_by=created_at&order_type=desc&per_page=100&page={page}"
        )
        batch = data.get("tickets", [])
        if not batch:
            break
        stop = False
        for t in batch:
            created = datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")).astimezone(EAT)
            if created >= today_start:
                tickets.append(t)
            else:
                stop = True
                break
        if stop or len(batch) < 100:
            break
        page += 1
    return tickets


def fetch_today_tickets():
    # Freshservice's offset/page pagination is only stable when the sort key
    # (created_at) is unique across the boundary -- two tickets created in the
    # same second can straddle a page split and come back on both pages.
    # Dedupe by id defensively rather than assume that never happens.
    today_start = datetime.now(EAT).replace(hour=0, minute=0, second=0, microsecond=0)
    all_tickets = []
    seen_ids = set()
    for ws in WORKSPACES:
        tickets = fetch_today_tickets_for_workspace(ws["id"], today_start)
        for t in tickets:
            if t["id"] in seen_ids:
                continue
            seen_ids.add(t["id"])
            t["_workspace_name"] = ws["name"]
            all_tickets.append(t)
    return all_tickets, today_start


def fetch_agent_directory():
    directory = {}
    page = 1
    while True:
        data = _api_get(f"/api/v2/agents?per_page=100&page={page}")
        batch = data.get("agents", [])
        if not batch:
            break
        for a in batch:
            name = f"{(a.get('first_name') or '').strip()} {(a.get('last_name') or '').strip()}".strip()
            directory[str(a["id"])] = name or f"Agent {a['id']}"
        if len(batch) < 100:
            break
        page += 1
    return directory


def fetch_conversation_text(ticket_id):
    texts = []
    page = 1
    while True:
        data = _api_get(f"/api/v2/tickets/{ticket_id}/conversations?per_page=100&page={page}")
        batch = data.get("conversations", [])
        texts.extend(c.get("body_text") or "" for c in batch)
        if not data.get("meta", {}).get("has_more"):
            break
        page += 1
    return "\n".join(texts)


def _classification_cache_path(base_dir):
    return os.path.join(base_dir, CLASSIFICATION_CACHE_NAME)


def load_classification_cache(base_dir):
    path = _classification_cache_path(base_dir)
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


def save_classification_cache(base_dir, cache):
    with open(_classification_cache_path(base_dir), "w") as f:
        json.dump(cache, f, separators=(",", ":"))


def prune_classification_cache(cache, retention_days, now):
    cutoff = now - timedelta(days=retention_days)
    return {
        ticket_id: entry for ticket_id, entry in cache.items()
        if datetime.fromisoformat(entry["classified_at"]) >= cutoff
    }


def classify_delay_drivers(records, base_dir, now):
    cache = prune_classification_cache(load_classification_cache(base_dir), RETENTION_DAYS, now)
    new_counts = {}
    total_new = 0
    for r in records:
        group = r["delayDriverGroup"]
        if group is None or r["bucket"] != "resolved_approved":
            continue
        key = str(r["id"])
        cached = cache.get(key)
        if cached:
            r["delayDriver"] = cached["label"]
            continue
        if new_counts.get(group, 0) >= MAX_NEW_CLASSIFICATIONS_PER_RUN:
            continue
        text = fetch_conversation_text(r["id"])
        label = classify_delay_driver(text)
        r["delayDriver"] = label
        cache[key] = {"label": label, "classified_at": now.isoformat()}
        new_counts[group] = new_counts.get(group, 0) + 1
        total_new += 1
    save_classification_cache(base_dir, cache)
    breakdown = ", ".join(f"{g}: {n}" for g, n in new_counts.items()) or "none"
    print(f"  [delay-driver] classified {total_new} new ticket(s) this run ({breakdown}) "
          f"(cache now holds {len(cache)} entries)")
    return records


def to_records(tickets, agent_directory):
    records = []
    for t in tickets:
        stats = t.get("stats") or {}
        status = t.get("status")
        responder = t.get("responder_id")
        resolved_at = stats.get("resolved_at")
        resolution_secs = stats.get("resolution_time_in_secs")
        cf = t.get("custom_fields") or {}
        requester = t.get("requester") or {}
        rec = {
            "id": t["id"],
            "subject": t.get("subject"),
            "workspace": t["_workspace_name"],
            "category": categorize(t.get("subject")),
            "subCategory": t.get("sub_category"),
            "branch": canonical_branch(cf.get("branch")),
            "bucket": bucket_for(status),
            "hasResponder": responder is not None,
            "responder": responder,
            "responderName": agent_directory.get(str(responder)) if responder else None,
            "requesterName": requester.get("name"),
            "hasFirstResponse": stats.get("first_responded_at") is not None,
            "createdAt": t.get("created_at"),
            "resolvedAt": resolved_at,
            "handlingSecs": resolution_secs if (resolved_at and resolution_secs is not None) else None,
            "delayDriver": None,
            "statusPending": status == ST_PENDING,
        }
        rec["delayDriverGroup"] = delay_driver_group(rec)
        records.append(rec)
    return records


def write_ticket_listing(records, base_dir, day_str):
    tickets_dir = os.path.join(base_dir, "tickets")
    os.makedirs(tickets_dir, exist_ok=True)
    payload = {
        "generatedAt": datetime.now(EAT).isoformat(),
        "tickets": [
            {
                "id": r["id"],
                "subject": r["subject"],
                "workspace": r["workspace"],
                "category": r["category"],
                "subCategory": r["subCategory"],
                "branch": r["branch"],
                "bucket": r["bucket"],
                "agent": r["responderName"],
                "requester": r["requesterName"],
                "createdAt": r["createdAt"],
                "resolvedAt": r["resolvedAt"],
                "handlingSecs": r["handlingSecs"],
                "delayDriver": r["delayDriver"],
                "delayDriverGroup": r["delayDriverGroup"],
            }
            for r in records
        ],
    }
    with open(os.path.join(tickets_dir, f"{day_str}.json"), "w") as f:
        json.dump(payload, f, separators=(",", ":"))


def build_snapshot():
    now = datetime.now(EAT)

    print("[upia-verification] Fetching agent directory...")
    agent_directory = fetch_agent_directory()

    tickets, today_start = fetch_today_tickets()
    records = to_records(tickets, agent_directory)
    other = [r for r in records if r["bucket"] == "other"]
    if other:
        print(f"  [warn] {len(other)} ticket(s) have a status outside the known set -- "
              f"excluded from the outcome buckets but still counted in Received.")

    print("[upia-verification] Classifying delay drivers for resolved New Loan Verification tickets...")
    records = classify_delay_drivers(records, HERE, now)

    workspace_names = [w["name"] for w in WORKSPACES]
    entry = hstore.compact_entry(now.isoformat(), records, workspace_names, CATEGORIES)

    day_str = now.strftime("%Y-%m-%d")
    hstore.append_entry(HISTORY_DIR, day_str, entry, workspace_names, CATEGORIES)
    available_days = hstore.update_index(HISTORY_DIR, day_str, RETENTION_DAYS)
    recent = hstore.recent_window(HISTORY_DIR, now, workspace_names, CATEGORIES, RECENT_WINDOW_HOURS)

    write_ticket_listing(records, HERE, day_str)

    return {
        "generatedAt": now.isoformat(),
        "windowStart": today_start.isoformat(),
        "categories": CATEGORIES,
        "workspaces": workspace_names,
        "buckets": BUCKETS,
        "branches": hstore.BRANCH_WHITELIST,
        "delayDrivers": hstore.DELAY_DRIVERS,
        "delayDriverGroups": hstore.DELAY_DRIVER_GROUPS,
        "agentDirectory": agent_directory,
        "recent": recent,
        "availableDays": available_days,
        "mirrorUrl": MIRROR_URL,
        "recordCount": len(records),
    }


def build_html(snapshot, template_path, output_path):
    with open(template_path, "r") as f:
        template = f.read()
    payload = base64.b64encode(json.dumps(snapshot, separators=(",", ":")).encode()).decode()
    html = template.replace("__SNAPSHOT_B64__", payload)
    with open(output_path, "w") as f:
        f.write(html)
    return output_path


def main():
    print("[upia-verification] Fetching today's tickets across 4 workspaces...")
    snapshot = build_snapshot()
    print(f"  {snapshot['recordCount']} tickets fetched "
          f"(window start {snapshot['windowStart']}); "
          f"{len(snapshot['recent'])} snapshot(s) in the embedded recent window, "
          f"{len(snapshot['availableDays'])} day(s) in the history store")
    out_path = build_html(snapshot, TEMPLATE_PATH, OUTPUT_PATH)
    print(f"[upia-verification] HTML written to {out_path}")


if __name__ == "__main__":
    main()
