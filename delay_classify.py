"""
Delay-driver keyword classifier for New Loan Verification tickets on the
KE_UPIA_Verification dashboard. Ported from the one-off "KE_UPIA_Verification
Tickets Report" generator's classify_delays.py
(/private/tmp/claude-502/.../394b09f8-ec34-4157-a9a3-8a4f5f92dba7/scratchpad/classify_delays.py),
per Kelvin's request to reuse that report's concept for the live dashboard.

This is an approximate heuristic over each ticket's full conversation/email
thread text, not manual case-by-case review -- it was calibrated in that
earlier report against a manually-read 40-ticket sample before running on
a full day's tickets. Only meaningful for tickets whose sub_category is
"New Loan Verification" and that have reached a resolved/closed/approved
state (a ticket's conversation is still growing while open, so classifying
too early risks a wrong label based on an incomplete thread).
"""
import re

CATEGORIES = [
    ("BM/SM approval needed (defaulter-linked reference)", [
        r"\bdefaulter", r"bm to interact", r"bm approve", r"sm to approve",
        r"bm and sm", r"sm interact", r"bm advise", r"@bm", r"sm to approved",
    ]),
    ("Automated KYC/AML vendor check", [
        r"smile id", r"\bkyc\b", r"\baml\b",
    ]),
    ("Loan officer/branch data correction needed", [
        r"provide correct", r"update the stock", r"consent signature",
        r"tallies on mpesa", r"correct home direction", r"does not have receipt",
        r"update stock", r"registered under.*wrong number", r"correct number that tallies",
    ]),
    ("Client/referee unreachable or unresponsive", [
        r"unresponsive", r"unreachable", r"no answer", r"not going through",
        r"\boffline\b", r"no response", r"did not confirm", r"not confirm",
        r"\bsilent\b", r"\bfaulty\b", r"\bbusy\b", r"third party", r"hanged up",
        r"call dropped", r"went silent", r"not aware of the business", r"wrong number",
    ]),
]

NO_SIGNAL_LABEL = "No clear delay signal (straightforward resolution)"

# Fixed, ordered list of every label classify() can return -- used by
# history_store.py to index-encode delayDriver in compact history rows.
# Must stay in sync with CATEGORIES above + NO_SIGNAL_LABEL (kept as two
# separate lists rather than derived, same convention as build_dashboard.py's
# BUCKETS/bucket_for() pairing).
DELAY_DRIVERS = [label for label, _ in CATEGORIES] + [NO_SIGNAL_LABEL]


def classify(text, debug=False):
    t = (text or "").lower()
    for label, patterns in CATEGORIES:
        for p in patterns:
            if re.search(p, t):
                return (label, p) if debug else label
    return (NO_SIGNAL_LABEL, None) if debug else NO_SIGNAL_LABEL
