# Autonomous Bug Fix — OSS4AI Hackathon

> **An AI agent that reads a Jira ticket, fixes the bug, validates it, and ships a PR — fully autonomously.**

This project demonstrates an end-to-end pipeline where an AI agent (OpenHands + Claude Sonnet) autonomously reads a bug report, reproduces the issue in a sandboxed environment, generates a fix, validates it against the test suite, and opens a pull request — with a human gate only at the final merge step.

---

## The Problem

AI coding agents can now fix real bugs. But autonomous fixing and *safely shipping* are two different things. The missing layer is:

- **Sandbox first** — reproduce the bug in isolation before touching prod
- **Validate the fix** — automated tests must pass before a PR is opened
- **Human gate** — PR review before merge; agent never self-merges
- **Safe deploy** — feature-flagged canary, not a full rollout
- **Self-improvement** — every failed fix is stored in a RAG store so the agent learns from history

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        TRIGGER                              │
│  Jira Ticket → label: "openhands" → webhook fires          │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  RAG CONTEXT INJECTION                      │
│  Query ChromaDB for similar past failures                   │
│  Prepend failure history to agent prompt                    │
│  Agent learns from mistakes before writing a single line    │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              AUTONOMOUS AGENT (OpenHands + Claude)          │
│                                                             │
│  ├── Reads Jira ticket (title + description)               │
│  ├── Clones repo into Docker sandbox                       │
│  ├── Reproduces the bug                                     │
│  ├── Writes targeted fix                                    │
│  ├── Runs full test suite → must pass                      │
│  └── Opens pull request referencing the Jira ticket        │
│                                                             │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                      HUMAN GATE                             │
│  Pull Request opened → links back to Jira ticket           │
│  Reviewer sees: fix diff + test results                     │
│  Approve → merge → deploy                                   │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                   PRODUCTION DEPLOY                         │
│  Feature-flagged canary (10% traffic)                       │
│  Auto-rollback if error rate spikes                         │
│  Failed fix → captured to RAG store for next run            │
└─────────────────────────────────────────────────────────────┘
```

---

## Demo Web App — TechStore

A simple Flask e-commerce product catalog with **two real bugs** planted for the demo.

### Bug 1 — Wrong Sale Price (UI Bug, always visible)
The discount calculation shows the **discount amount** instead of the **sale price**.

```
Product: Laptop Pro 15  |  Price: $1299.99  |  10% off
Expected sale price: $1,169.99
Actual (buggy):       $130.00   ← shows the discount, not the price
```

### Bug 2 — Crash on Product Detail (500 Error)
When a product has no reviews, viewing its detail page throws a `ZeroDivisionError` and returns a 500 error.

```
GET /product/3  →  ZeroDivisionError: division by zero  →  500 Internal Server Error
```

---

## Project Structure

```
autonomous-bug-fixer/
├── README.md
├── docker-compose.multi-repo.yml       ← multi-repo sandbox + prod
├── webhook/
│   ├── server.py                       ← Jira webhook receiver (Flask)
│   └── runner.py                       ← launches OpenHands subprocess
├── feedback/
│   ├── capture.py                      ← stores failed fixes in ChromaDB
│   ├── rag_store.py                    ← ChromaDB wrapper
│   ├── retriever.py                    ← semantic search over past failures
│   └── injector.py                     ← enriches agent prompt with failure history
├── test-webapp/                        ← Frontend (Flask) — contains Bug 1 + Bug 2
│   ├── app.py
│   ├── templates/
│   └── tests/test_app.py               ← 5 tests fail on buggy code
├── api-service/                        ← Backend REST API — Bug 3 (field rename)
│   ├── api.py
│   └── tests/test_api.py
├── integration-tests/
│   └── test_integration.py             ← catches cross-service contract bugs
└── bugs/
    ├── BUG-001.md                      ← single-repo: 500 crash on empty reviews
    └── BUG-002.md                      ← multi-repo: API field rename breaks frontend
```

---

## Running the Demo

### 1. Start the webhook server
```bash
cd autonomous-bug-fixer
pip install -r requirements.txt
python webhook/server.py
# listening on http://localhost:5050
```

### 2. Trigger the autonomous agent via Jira
Add the `openhands` label to a Jira issue. The webhook fires, the agent runs, and a PR appears on GitHub — no human involved until code review.

Or simulate it locally:
```bash
python demo/simulate_webhook.py
```

### 3. Watch the agent work
```
[TEC-1] STEP 1/5 — Querying RAG store for similar past failures
[TEC-1] STEP 2/5 — Enriched task prompt built
[TEC-1] STEP 3/5 — Launching OpenHands agent (sandbox + Claude Sonnet)
[runner] Starting OpenHands for TEC-1...
[runner] OpenHands exited (rc=0) after 288.0s
[runner] Success — PR: https://github.com/your-org/repo/pull/2
[TEC-1] STEP 4/5 — Tests passed ✓
[TEC-1] STEP 5/5 — PR opened
[TEC-1] ✓ PIPELINE COMPLETE — bug fixed and shipped safely
```

### 4. Start the sandbox (buggy version)
```bash
cd test-webapp
docker-compose up sandbox
```
Open http://localhost:5000 — wrong sale prices (Bug 1).
Click **USB-C Hub** — 500 crash (Bug 2).

### 5. Verify fix in sandbox after agent runs
```bash
docker-compose up sandbox   # rebuild with agent's patch
```
- http://localhost:5000 → sale prices correct
- http://localhost:5000/product/3 → shows "No reviews yet" instead of crashing

---

## Tools Used

| Layer | Tool |
|---|---|
| AI Agent | [OpenHands](https://github.com/OpenHands/OpenHands) (open source) |
| LLM Backend | Claude Sonnet 4.6 (Anthropic) |
| Issue Tracking | Jira (webhook trigger) |
| Sandbox | Docker (isolated, ephemeral) |
| Failure Memory | ChromaDB + sentence-transformers (local, offline) |
| Root Cause Inference | Claude Haiku (fast, cheap) |
| Web App | Python / Flask |

---

## RAG Feedback Loop — The Agent Gets Smarter Over Time

Every failed fix (test failure or production rollback) is automatically captured, embedded, and stored in a local vector database. The **next time a similar ticket arrives**, the agent's prompt is enriched with the relevant failure history — so it doesn't repeat the same mistake.

```
┌─────────────────────────────────────────────────────────────┐
│  New Jira Ticket                                            │
│  e.g. "ZeroDivisionError in product detail"                 │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  feedback/retriever.py                                      │
│  Embed ticket title + body → query ChromaDB                 │
│  Return top-3 similar past failures (similarity ≥ 0.5)     │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  feedback/injector.py                                       │
│  Prepend failure context block to the OpenHands task prompt │
│                                                             │
│  ## Past Similar Fix Failures — Learn From These           │
│  ### Failure 1 (similarity: 87%)                           │
│  - Ticket: BUG-001                                          │
│  - Root cause: forgot to guard against empty list before   │
│    division — fix added check but broke avg when len == 1  │
│  - Failing diff: ...                                        │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  OpenHands Agent runs with enriched context                 │
│  Studies past failures BEFORE writing any code              │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┴────────────┐
              │                         │
              ▼                         ▼
     Fix passes tests           Fix fails / rollback
     → PR opened                → feedback/capture.py
                                  ├── Claude Haiku infers
                                  │   root cause from diff+log
                                  ├── Saved to ChromaDB
                                  └── Raw JSON audit trail
                                      feedback/store/raw/
```

### Why RAG, Not Fine-Tuning?

| | RAG (this approach) | Fine-tuning |
|---|---|---|
| Setup time | Minutes | Days + GPU budget |
| Update latency | Instant (add to store) | Retrain cycle |
| Traceability | Every injection is visible in the prompt | Black box in weights |
| Cost | Free (local ChromaDB + offline embeddings) | $100s per run |
| Works with closed models | Yes | No |

---

## Multi-Repo Support

Real bugs often span two repos. BUG-002 demonstrates this: `api-service` renamed `sale_price` → `final_price`, breaking the frontend. Neither repo's unit tests catch it — only the integration test does.

The agent autonomously fixes both repos and opens two coordinated PRs. Deploy order is enforced: API first, then frontend.

```bash
# See the bug ($0.00 sale prices)
docker-compose -f docker-compose.multi-repo.yml --profile sandbox up

# Run integration tests
docker-compose -f docker-compose.multi-repo.yml --profile integration run --rm integration-test

# After agent fixes and PRs merge
docker-compose -f docker-compose.multi-repo.yml --profile prod up
```

---

## Key Safety Properties

| Property | How |
|---|---|
| Isolation | Agent runs inside Docker, never touches prod directly |
| Reversibility | Every change is a git commit; one `git revert` undoes it |
| Validation | Tests must pass before PR is opened — agent cannot skip this |
| Human gate | PR review required before merge; agent never self-merges |
| Auditability | PR links back to Jira ticket; full agent action log available |
| Blast radius | Prod deploy is canary (10% traffic) with auto-rollback |
| Self-improvement | Failed fixes fed back into RAG store; agent learns from history |
