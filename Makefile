.PHONY: help test test-verbose test-coverage test-ai test-stable test-sync test-status test-worker test-one-calendar test-in-place test-real-api test-all clean-podman clean-all clean-calendars-dry-run clean-calendars up down restart build prepare-fixture db-reset venv-activate venv-install run-scraper run-api run-all

# Default target
help:
	@echo "Available commands:"
	@echo ""
	@echo "Setup:"
	@echo "  make venv-activate - Activate virtual environment (opens shell)"
	@echo "  make venv-install  - Create venv and install dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  make test          - Run all tests (skips AI/real API tests)"
	@echo "  make test-all      - Run ALL tests including real API tests"
	@echo "  make test-verbose  - Run tests with verbose output"
	@echo "  make test-coverage - Run tests with coverage report"
	@echo "  make test-ai       - Run AI integration tests (uses real Groq tokens)"
	@echo "  make test-real-api - Run Google Calendar real API tests"
	@echo "  make test-stable   - Run stable ID tests"
	@echo "  make test-sync     - Run calendar sync tests"
	@echo "  make test-status   - Run calendar status tests"
	@echo "  make test-worker   - Run background worker tests"
	@echo "  make test-one-calendar - Run one calendar per group tests"
	@echo "  make test-in-place - Run in-place update tests"
	@echo ""
	@echo "Development:"
	@echo "  make prepare-fixture - Regenerate test fixture from real XLSX"
	@echo "  make run-scraper   - Run scraper (fetches data, parses, writes to DB)"
	@echo "  make run-api       - Start API server (Flask on port 3333)"
	@echo "  make run-all       - Run scraper then start API server"
	@echo ""
	@echo "Docker/Podman:"
	@echo "  make up            - Start services (podman-compose up)"
	@echo "  make down          - Stop services"
	@echo "  make restart       - Restart services"
	@echo "  make build         - Build Docker images"
	@echo "  make clean         - Stop services and remove containers/images"
	@echo "  make clean-podman  - Clean all podman containers and images"
	@echo "  make clean-all     - Full cleanup (podman + database)"
	@echo ""
	@echo "Calendar Cleanup:"
	@echo "  make clean-calendars-dry-run - Check for orphaned calendars (dry run)"
	@echo "  make clean-calendars        - Delete orphaned calendars (requires confirmation)"
	@echo ""
	@echo "Database:"
	@echo "  make db-reset      - Delete database file (requires services down)"

# Virtual Environment
venv-activate:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@bash -c "source venv/bin/activate && exec bash"

venv-install:
	python3 -m venv venv
	venv/bin/pip install --upgrade pip
	venv/bin/pip install -r requirements.txt
	@echo "✅ Virtual environment created and dependencies installed"
	@echo "   Activate with: source venv/bin/activate"

# Testing (automatically uses venv if available)
test:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo "🧪 Running all tests (excluding AI and real API tests)..."
	venv/bin/pytest tests/ -v -m "not ai_integration and not real_api"

test-all:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo "🧪 Running ALL tests (including real API tests)..."
	@echo "⚠️  This will make real Google Calendar API calls!"
	venv/bin/pytest tests/ -v

test-verbose:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/pytest tests/ -vv -m "not ai_integration and not real_api"

test-coverage:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/pytest tests/ --cov=scraper --cov=api --cov=services --cov-report=term-missing -m "not ai_integration and not real_api"

test-ai:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo "🧪 Running AI integration tests (uses real Groq tokens)..."
	venv/bin/pytest tests/ --use-ai-tokens -v -m ai_integration

test-real-api:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo "🧪 Running Google Calendar real API tests..."
	@echo "⚠️  This will make real Google Calendar API calls!"
	venv/bin/pytest tests/test_google_calendar_real_api.py -v -m real_api

test-stable:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/pytest tests/test_stable_ids.py -v

test-sync:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/pytest tests/test_calendar_sync.py -v

test-status:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/pytest tests/test_calendar_status.py -v

test-worker:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/pytest tests/test_background_worker.py -v

test-one-calendar:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/pytest tests/test_one_calendar_per_group.py -v

test-in-place:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/pytest tests/test_in_place_updates.py -v

prepare-fixture:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/python tests/prepare_fixture.py

# Docker/Podman Compose - Auto-detect which is available
COMPOSE_CMD := $(shell command -v podman-compose 2>/dev/null || command -v docker-compose 2>/dev/null || echo "")
ifeq ($(COMPOSE_CMD),)
    $(error Neither podman-compose nor docker-compose found. Please install one of them.)
endif

up:
	@echo "Using: $(COMPOSE_CMD)"
	$(COMPOSE_CMD) up -d

down:
	@echo "Using: $(COMPOSE_CMD)"
	$(COMPOSE_CMD) down

restart: down up

build:
	@echo "Using: $(COMPOSE_CMD)"
	$(COMPOSE_CMD) build

rebuild: clean build
	@echo "✅ Images rebuilt (clean build)"

# Cleanup
clean: down
	@echo "🧹 Cleaning up containers and images..."
	@if command -v podman-compose >/dev/null 2>&1; then \
		podman-compose down --rmi all --volumes || true; \
	elif command -v docker-compose >/dev/null 2>&1; then \
		docker-compose down --rmi all --volumes || true; \
	fi
	@echo "✅ Cleanup complete"

clean-podman:
	@echo "🧹 Cleaning up all podman containers and images..."
	@if command -v podman >/dev/null 2>&1; then \
		podman stop $$(podman ps -aq) 2>/dev/null || true; \
		podman rm $$(podman ps -aq) 2>/dev/null || true; \
		podman rmi $$(podman images -q) 2>/dev/null || true; \
		podman system prune -af --volumes 2>/dev/null || true; \
		echo "✅ Podman cleanup complete"; \
	else \
		echo "⚠️  podman not found, skipping"; \
	fi

clean-all: clean-podman db-reset
	@echo "✅ Full cleanup complete (podman + database)"

# Database
db-reset:
	@if [ -f database/waste_schedule.db ]; then \
		rm database/waste_schedule.db; \
		echo "✅ Database deleted"; \
	else \
		echo "⚠️  Database file not found"; \
	fi

# Scraper and API
run-scraper:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo "🚀 Running scraper (with AI parsing and calendar creation)..."
	venv/bin/python scraper/main.py

run-scraper-skip-ai:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo "🚀 Running scraper (skip AI, traditional parser only)..."
	venv/bin/python scraper/main.py --skip-ai

run-api:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo "🚀 Starting API server on http://localhost:3333..."
	venv/bin/python api/app.py

run-all: run-scraper
	@echo ""
	@echo "✅ Scraper completed. Starting API server..."
	@$(MAKE) run-api
