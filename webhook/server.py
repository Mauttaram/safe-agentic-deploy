"""
Jira webhook receiver — the entry point for the full pipeline.

Jira setup (one-time):
  Project Settings → Webhooks → Create
    URL:    http://<your-server>:5050/webhook/jira
    Events: Issue updated (label change)

When Jira fires the webhook (issue labelled "openhands"):
  1. Parse the Jira payload
  2. Build RAG-enriched OpenHands task prompt
  3. Run OpenHands agent in Docker
  4. On failure → auto-capture to RAG store

Run:
    python webhook/server.py
    # or with gunicorn in prod:
    gunicorn -w 1 -b 0.0.0.0:5050 "webhook.server:app"
"""
from __future__ import annotations
import os
import sys
import threading
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, request, jsonify

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TRIGGER_LABEL   = "openhands"       # Jira label that triggers the agent
REPO_FIELD      = "customfield_repo" # Jira custom field holding the repo URL
                                     # Set in Jira: Project settings → Fields


# ── Webhook endpoint ──────────────────────────────────────────────────────────

@app.route("/webhook/jira", methods=["POST"])
def jira_webhook():
    """
    Receives Jira issue-updated events.
    Fires the OpenHands agent when the 'openhands' label is added.
    """
    payload = request.get_json(force=True, silent=True)
    if not payload:
        return jsonify({"error": "empty payload"}), 400

    event_type = payload.get("webhookEvent", "")
    if event_type not in ("jira:issue_created", "jira:issue_updated"):
        return jsonify({"skipped": f"event {event_type} not handled"}), 200

    issue  = payload.get("issue", {})
    fields = issue.get("fields", {})
    labels = [lbl.get("name", "") if isinstance(lbl, dict) else lbl
              for lbl in fields.get("labels", [])]

    if TRIGGER_LABEL not in labels:
        return jsonify({"skipped": "label 'openhands' not present"}), 200

    ticket_id    = issue.get("key", "UNKNOWN")
    ticket_title = fields.get("summary", "")
    ticket_body  = _extract_body(fields)
    repo_url     = fields.get(REPO_FIELD) or (fields.get("description") or "")[:200]

    log.info("Triggered by Jira: %s — %s", ticket_id, ticket_title)

    # Fire the agent in a background thread so the webhook returns immediately.
    # Jira expects a quick 200 — the actual agent run takes minutes.
    thread = threading.Thread(
        target=_run_agent_async,
        args=(ticket_id, ticket_title, ticket_body, repo_url),
        daemon=True,
    )
    thread.start()

    return jsonify({
        "status":   "accepted",
        "ticket":   ticket_id,
        "message":  f"OpenHands agent started for {ticket_id}",
    }), 202


@app.route("/webhook/rollback", methods=["POST"])
def rollback_webhook():
    """
    Called by the canary deploy monitor when error rate spikes.
    Captures the rollback event into the RAG store.

    Expected JSON body:
    {
        "ticket_id":    "BUG-001",
        "ticket_title": "...",
        "ticket_body":  "...",
        "repo_url":     "...",
        "diff":         "git diff output",
        "error_output": "error log / metrics"
    }
    """
    payload = request.get_json(force=True, silent=True)
    if not payload:
        return jsonify({"error": "empty payload"}), 400

    required = ["ticket_id", "ticket_title", "repo_url", "diff", "error_output"]
    missing  = [k for k in required if not payload.get(k)]
    if missing:
        return jsonify({"error": f"missing fields: {missing}"}), 400

    from webhook.runner import capture_rollback
    result = capture_rollback(
        ticket_id    = payload["ticket_id"],
        ticket_title = payload["ticket_title"],
        ticket_body  = payload.get("ticket_body", ""),
        repo_url     = payload["repo_url"],
        diff         = payload["diff"],
        error_output = payload["error_output"],
    )
    return jsonify({"status": "captured", **result}), 201


@app.route("/health", methods=["GET"])
def health():
    from feedback.rag_store import RAGStore
    store = RAGStore()
    return jsonify({
        "status":          "ok",
        "rag_store_count": store.count(),
        "trigger_label":   TRIGGER_LABEL,
    })


@app.route("/failures", methods=["GET"])
def list_failures():
    """Quick inspect — list recent failures in the RAG store."""
    from feedback.rag_store import RAGStore
    store = RAGStore()
    query = request.args.get("q", "bug fix failure")
    n     = int(request.args.get("n", 10))
    results = store.query(query, n_results=min(n, store.count() or 1))
    return jsonify(results)


# ── Async agent runner ────────────────────────────────────────────────────────

def _run_agent_async(
    ticket_id: str, ticket_title: str, ticket_body: str, repo_url: str,
) -> None:
    """Runs in a background thread — builds enriched prompt, fires OpenHands."""
    try:
        from feedback.injector import build_enriched_task
        from webhook.runner    import run_openhands_task

        enriched_task = build_enriched_task(
            ticket_id    = ticket_id,
            ticket_title = ticket_title,
            ticket_body  = ticket_body,
            repo         = repo_url,
        )

        result = run_openhands_task(
            ticket_id     = ticket_id,
            ticket_title  = ticket_title,
            ticket_body   = ticket_body,
            repo_url      = repo_url,
            enriched_task = enriched_task,
        )

        if result["success"]:
            log.info("[%s] Agent succeeded — PR: %s", ticket_id, result.get("pr_url"))
        else:
            log.warning("[%s] Agent failed — failure captured (event_id=%s)",
                        ticket_id, result.get("event_id"))

    except Exception as exc:
        log.exception("[%s] Unexpected error in agent runner: %s", ticket_id, exc)


# ── Body extraction helpers ───────────────────────────────────────────────────

def _extract_body(fields: dict) -> str:
    """
    Jira description can be Atlassian Document Format (ADF) or plain text.
    We flatten it to a plain string for the agent prompt.
    """
    desc = fields.get("description", "")
    if isinstance(desc, dict):
        return _flatten_adf(desc)
    return str(desc or "")


def _flatten_adf(node: dict, depth: int = 0) -> str:
    """Recursively flatten Atlassian Document Format to plain text."""
    if depth > 20:
        return ""
    node_type = node.get("type", "")
    if node_type == "text":
        return node.get("text", "")
    lines = []
    for child in node.get("content", []):
        lines.append(_flatten_adf(child, depth + 1))
    sep = "\n" if node_type in ("paragraph", "heading", "bulletList", "listItem") else ""
    return sep.join(lines)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    log.info("Jira webhook server listening on port %d", port)
    log.info("Endpoint: POST http://0.0.0.0:%d/webhook/jira", port)
    app.run(host="0.0.0.0", port=port, debug=False)
