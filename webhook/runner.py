"""
Runs the OpenHands agent subprocess and captures failures back into the RAG store.

Called by webhook/server.py after building the enriched task prompt.
On success: logs the result.
On failure: calls feedback.capture to store the failure in ChromaDB.
"""
from __future__ import annotations
import os
import subprocess
import tempfile
import time
from pathlib import Path

CONFIG_PATH = "openhands-config.toml"


def run_openhands_task(
    ticket_id:     str,
    ticket_title:  str,
    ticket_body:   str,
    repo_url:      str,
    enriched_task: str,
    config_path:   str = CONFIG_PATH,
    timeout:       int = 1800,      # 30 min max per ticket
) -> dict:
    """
    Run OpenHands with the enriched task prompt.

    Returns:
        {"success": True, "pr_url": "..."}
        {"success": False, "event_id": "...", "root_cause": "...", "error_output": "..."}
    """
    workspace = os.path.join(os.getcwd(), "workspace", ticket_id)
    os.makedirs(workspace, exist_ok=True)

    # Run OpenHands via the locally installed pip package (avoids Docker-in-Docker
    # issues on macOS). It still uses the host Docker daemon for the sandbox runtime.
    python = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                          ".venv", "bin", "python3")
    if not os.path.exists(python):
        python = "python3"

    env = {
        **os.environ,
        "LLM_API_KEY":    os.environ.get("ANTHROPIC_API_KEY", os.environ.get("LLM_API_KEY", "")),
        "LLM_MODEL":      "anthropic/claude-sonnet-4-6",
        "WORKSPACE_BASE": workspace,
        "GITHUB_TOKEN":   os.environ.get("GITHUB_TOKEN", ""),
        "LOG_ALL_EVENTS": "true",
    }

    cmd = [
        python, "-m", "openhands.core.main",
        "-t", enriched_task,
    ]

    print(f"[runner] Starting OpenHands for {ticket_id}...")
    start = time.time()

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".log", delete=False) as log_file:
        log_path = log_file.name

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        elapsed = round(time.time() - start, 1)
        output  = result.stdout + result.stderr

        Path(log_path).write_text(output)
        print(f"[runner] OpenHands exited (rc={result.returncode}) after {elapsed}s")

        if result.returncode == 0:
            pr_url = _extract_pr_url(output)
            print(f"[runner] Success — PR: {_hyperlink(pr_url) if pr_url else 'see agent logs'}")
            return {"success": True, "pr_url": pr_url, "log": log_path}

        # ── Failure path ──────────────────────────────────────────────────────
        diff = _extract_diff(output)
        root_cause, event_id = _capture_to_rag(
            ticket_id    = ticket_id,
            ticket_title = ticket_title,
            ticket_body  = ticket_body,
            repo_url     = repo_url,
            diff         = diff,
            error_output = output,
            event_type   = "test_failure",
        )
        return {
            "success":      False,
            "event_id":     event_id,
            "root_cause":   root_cause,
            "error_output": output[:2000],
            "log":          log_path,
        }

    except subprocess.TimeoutExpired:
        error = f"OpenHands timed out after {timeout}s"
        print(f"[runner] {error}")
        _, event_id = _capture_to_rag(
            ticket_id    = ticket_id,
            ticket_title = ticket_title,
            ticket_body  = ticket_body,
            repo_url     = repo_url,
            diff         = "",
            error_output = error,
            event_type   = "test_failure",
        )
        return {"success": False, "event_id": event_id, "error_output": error}

    except FileNotFoundError:
        return {
            "success":      False,
            "error_output": "Docker not found — is Docker Desktop running?",
        }


def capture_rollback(
    ticket_id:     str,
    ticket_title:  str,
    ticket_body:   str,
    repo_url:      str,
    diff:          str,
    error_output:  str,
) -> dict:
    """
    Called by the canary deploy monitor when error rate spikes post-deploy.
    Stores the rollback event so future agents avoid the same mistake.
    """
    root_cause, event_id = _capture_to_rag(
        ticket_id    = ticket_id,
        ticket_title = ticket_title,
        ticket_body  = ticket_body,
        repo_url     = repo_url,
        diff         = diff,
        error_output = error_output,
        event_type   = "rollback",
    )
    print(f"[runner] Rollback captured — event_id={event_id}")
    return {"event_id": event_id, "root_cause": root_cause}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _capture_to_rag(
    ticket_id: str, ticket_title: str, ticket_body: str, repo_url: str,
    diff: str, error_output: str, event_type: str,
) -> tuple[str, str]:
    """Store failure in ChromaDB, return (root_cause, event_id)."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from feedback.capture import capture_failure
    event = capture_failure(
        event_type   = event_type,
        ticket_id    = ticket_id,
        ticket_title = ticket_title,
        ticket_body  = ticket_body,
        repo         = repo_url,
        diff         = diff,
        error_output = error_output,
    )
    return event.root_cause, event.event_id


def _hyperlink(url: str, label: str | None = None) -> str:
    """Render a terminal-clickable OSC 8 hyperlink (works in iTerm2, macOS Terminal, VS Code)."""
    text = label or url
    return f"\033]8;;{url}\033\\{text}\033]8;;\033\\"


def _extract_pr_url(output: str) -> str:
    """Pull the GitHub PR URL out of OpenHands stdout."""
    import re
    pr_pattern = r"https://github\.com/[^\s]+/pull/\d+"

    # Priority 1: URL on a creation line ("created pull request", "opened PR", etc.)
    created = re.findall(
        r"(?i)(?:creat|open|submit|push)(?:ed|ing)[^\n]*(" + pr_pattern + r")",
        output,
    )
    if created:
        return created[-1]

    # Priority 2: URL alone on its own line — exactly what `gh pr create` prints.
    solo = re.findall(r"^\s*(" + pr_pattern + r")\s*$", output, re.MULTILINE)
    if solo:
        return solo[-1]

    return ""


def _extract_diff(output: str) -> str:
    """
    Pull the git diff out of the OpenHands log.
    OpenHands prints `git diff` output when it commits a patch.
    """
    import re
    match = re.search(r"(diff --git .+?)(?=\n\[|$)", output, re.DOTALL)
    return match.group(1)[:3000] if match else ""
