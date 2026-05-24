.PHONY: help install sandbox prod test test-api test-integration seed demo webhook clean

help:
	@echo ""
	@echo "Safe Agentic Deploy — OSS4AI Hackathon"
	@echo "======================================="
	@echo ""
	@echo "  make install          Install Python deps (RAG + webhook)"
	@echo ""
	@echo "  make sandbox          Start buggy app  → http://localhost:5000"
	@echo "  make prod             Start fixed app  → http://localhost:8080"
	@echo "  make sandbox-multi    Multi-repo sandbox (both services)"
	@echo "  make prod-multi       Multi-repo prod   (both services)"
	@echo ""
	@echo "  make test             Run test-webapp unit tests (should FAIL on buggy code)"
	@echo "  make test-api         Run api-service unit tests (should FAIL on buggy code)"
	@echo "  make test-integration Run cross-service integration tests"
	@echo ""
	@echo "  make seed             Seed RAG store with past failure history"
	@echo "  make demo             Dry-run demo: RAG retrieval + enriched prompt"
	@echo "  make demo-bug2        Same demo but for BUG-002 (multi-repo)"
	@echo "  make webhook          Start the Jira webhook server on :5050"
	@echo "  make simulate         POST a fake Jira webhook to the local server"
	@echo ""
	@echo "  make clean            Remove RAG store, __pycache__, Docker containers"
	@echo ""

# ── Dependencies ──────────────────────────────────────────────────────────────

PYTHON := $(shell test -f .venv/bin/python3 && echo .venv/bin/python3 || command -v python3 || command -v python)

install:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install -r test-webapp/requirements.txt
	$(PYTHON) -m pip install -r api-service/requirements.txt

# ── App environments ──────────────────────────────────────────────────────────

sandbox:
	@echo "Starting buggy sandbox → http://localhost:5000"
	@echo "  Bug 1 visible on homepage (wrong sale prices)"
	@echo "  Bug 2 visible at /product/3 (500 crash)"
	docker compose -f test-webapp/docker-compose.yml --profile sandbox up --build

prod:
	@echo "Starting prod (fixed) → http://localhost:8080"
	docker compose -f test-webapp/docker-compose.yml --profile prod up --build

sandbox-multi:
	@echo "Starting multi-repo sandbox → frontend :5000 | api :8001"
	@echo "  Bug 3 visible: all sale prices show $0.00"
	docker compose -f docker-compose.multi-repo.yml --profile sandbox up --build

prod-multi:
	@echo "Starting multi-repo prod → frontend :8080 | api :8002"
	docker compose -f docker-compose.multi-repo.yml --profile prod up --build

# ── Tests ─────────────────────────────────────────────────────────────────────

test:
	@echo "Running test-webapp unit tests (expect FAILURES on buggy code)"
	$(PYTHON) -m pytest test-webapp/tests/ -v --tb=short

test-api:
	@echo "Running api-service unit tests (expect FAILURES on buggy code)"
	$(PYTHON) -m pytest api-service/tests/ -v --tb=short

test-integration:
	@echo "Running integration tests (requires sandbox-multi to be running)"
	docker compose -f docker-compose.multi-repo.yml --profile integration run --rm integration-test

# ── Demo ──────────────────────────────────────────────────────────────────────

seed:
	@echo "Seeding RAG store with past failure history..."
	$(PYTHON) demo/seed_failures.py

demo: seed
	@echo "Running RAG feedback loop demo (dry run)..."
	$(PYTHON) demo/run_demo.py

demo-bug2: seed
	$(PYTHON) demo/run_demo.py --bug BUG-002

webhook:
	@echo "Starting Jira webhook server on http://localhost:5050"
	$(PYTHON) webhook/server.py

simulate:
	@echo "Sending simulated Jira webhook (BUG-001) to localhost:5050..."
	$(PYTHON) demo/simulate_webhook.py

# ── Cleanup ───────────────────────────────────────────────────────────────────

clean:
	@echo "Removing RAG store, pycache, Docker containers..."
	rm -rf feedback/store/chroma feedback/store/raw
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	docker compose -f test-webapp/docker-compose.yml down 2>/dev/null || true
	docker compose -f docker-compose.multi-repo.yml down 2>/dev/null || true
	@echo "Done."
