"""
Simulate a Jira webhook firing so you can demo the full pipeline locally
without a real Jira instance.

Usage:
    # Terminal 1 — start the webhook server
    python webhook/server.py

    # Terminal 2 — fire a fake Jira event
    python demo/simulate_webhook.py           # BUG-001 (single-repo crash)
    python demo/simulate_webhook.py --bug 2   # BUG-002 (multi-repo $0.00 prices)
    python demo/simulate_webhook.py --dry-run # print payload, don't send
"""
from __future__ import annotations
import json
import sys
import os
import textwrap

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "http://localhost:5050/webhook/jira")

# ── Fake Jira payloads ────────────────────────────────────────────────────────

def _make_payload(
    key: str,
    summary: str,
    description: str,
    repo_url: str,
    event: str = "jira:issue_updated",
) -> dict:
    return {
        "webhookEvent": event,
        "issue": {
            "key": key,
            "fields": {
                "summary": summary,
                "description": description,
                "labels": [{"name": "openhands"}, {"name": "bug"}],
                "customfield_repo": repo_url,
                "priority": {"name": "High"},
                "status":   {"name": "Open"},
            },
        },
        "user": {"displayName": "QA Engineer"},
        "changelog": {
            "items": [{"field": "labels", "toString": "openhands bug"}],
        },
    }


PAYLOADS = {
    "1": _make_payload(
        key         = "BUG-001",
        summary     = "500 crash on product detail page when reviews list is empty",
        description = textwrap.dedent("""\
            Viewing /product/3 (USB-C Hub, 0 reviews) throws ZeroDivisionError.

            Steps to reproduce:
            1. Open http://localhost:5000
            2. Click "View Details" on USB-C Hub
            3. Observe 500 error page

            Root cause: avg_rating = sum(reviews) / len(reviews) crashes on empty list.

            Acceptance criteria:
            - GET /product/3 returns HTTP 200
            - Shows "No reviews yet" for products with empty review list
            - All tests in tests/test_app.py pass
        """),
        repo_url = "https://github.com/Mauttaram/autonomous-bug-fixer",
    ),
    "2": _make_payload(
        key         = "BUG-002",
        summary     = "All discounted products show $0.00 — API field renamed",
        description = textwrap.dedent("""\
            After the latest api-service deployment, all discounted products show $0.00.

            Root cause: api-service renamed `sale_price` → `final_price`.
            Frontend still reads `sale_price`, gets None, silently shows $0.00.

            Affects two repos:
            - api-service:  rename `final_price` back to `sale_price` in api.py
            - test-webapp:  verify frontend reads `sale_price` (no change needed if API reverts)

            Acceptance criteria:
            - All discounted products show correct prices
            - Integration tests pass (integration-tests/test_integration.py)
            - Both repos have passing unit tests
        """),
        repo_url = "https://github.com/Mauttaram/autonomous-bug-fixer",
    ),
}

# ── Send ──────────────────────────────────────────────────────────────────────

def send(bug_num: str = "1", dry_run: bool = False) -> None:
    payload = PAYLOADS.get(bug_num)
    if not payload:
        print(f"Unknown bug number '{bug_num}'. Choose: {list(PAYLOADS.keys())}")
        sys.exit(1)

    ticket_id = payload["issue"]["key"]
    summary   = payload["issue"]["fields"]["summary"]

    print(f"\n{'─'*60}")
    print(f"  Simulating Jira webhook — {ticket_id}")
    print(f"  Summary: {summary[:60]}")
    print(f"  Target:  {WEBHOOK_URL}")
    print(f"{'─'*60}\n")

    if dry_run:
        print("DRY RUN — payload that would be sent:")
        print(json.dumps(payload, indent=2))
        return

    try:
        import requests
        resp = requests.post(
            WEBHOOK_URL,
            json    = payload,
            headers = {"Content-Type": "application/json"},
            timeout = 10,
        )
        print(f"Response: HTTP {resp.status_code}")
        print(json.dumps(resp.json(), indent=2))
        if resp.status_code == 202:
            print(f"\n✓  Webhook accepted — OpenHands agent started in background.")
            print(f"   Watch the webhook server logs for progress.")
        else:
            print(f"\n⚠  Unexpected status code: {resp.status_code}")
    except Exception as exc:
        print(f"\n✗  Failed to reach webhook server: {exc}")
        print(f"   Make sure the server is running:  python webhook/server.py")


if __name__ == "__main__":
    bug_num = "1"
    dry_run = False

    args = sys.argv[1:]
    if "--dry-run" in args:
        dry_run = True
        args.remove("--dry-run")
    if "--bug" in args:
        idx = args.index("--bug")
        if idx + 1 < len(args):
            bug_num = args[idx + 1]
    elif args and args[0].isdigit():
        bug_num = args[0]

    send(bug_num=bug_num, dry_run=dry_run)
