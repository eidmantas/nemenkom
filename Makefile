.PHONY: help test lint format typecheck audit clean-podman clean-all clean-calendars-dry-run clean-calendars up down restart build db-reset venv-activate venv-install run-scraper run-api run-all

# Default target
help:
	@echo "Available commands:"
	@echo ""
	@echo "Setup:"
	@echo "  make venv-activate - Activate virtual environment (opens shell)"
	@echo "  make venv-install  - Create venv and install dependencies"
	@echo ""
	@echo "Testing:"
	@echo "  make test          - Run tests (skips AI Agent + Google Calendar API)"
	@echo "  make test-ai       - Run AI Agent tests only"
	@echo "  make test-calendar - Run Google Calendar API tests only"
	@echo "  make test-all      - Run tests including AI Agent (skips Google Calendar API)"
	@echo "  make lint          - Run ruff lint"
	@echo "  make format        - Run ruff format"
	@echo "  make typecheck     - Run pyright"
	@echo "  make audit         - Run pip-audit"
	@echo ""
	@echo "Development:"
	@echo "  make run-scraper   - Run scraper (fetches data, parses, writes to DB)"
	@echo "  make run-api       - Start API server (Flask on port 3333)"
	@echo "  make run-calendar  - Start calendar worker"
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
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@bash -c "source venv/bin/activate && exec bash"

venv-install:
	python3 -m venv venv
	venv/bin/pip install --upgrade pip
	venv/bin/pip install -r requirements.txt
	@echo " Virtual environment created and dependencies installed"
	@echo "   Activate with: source venv/bin/activate"

# Testing (automatically uses venv if available)
test:
	@if [ ! -d "venv" ]; then \
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo " Running tests (excluding AI Agent + Google Calendar API)..."
	THROTTLE_DISABLED=1 venv/bin/pytest tests/ -v -m "not ai_integration and not real_api"

test-ai:
	@if [ ! -d "venv" ]; then \
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo " Running AI integration tests..."
	THROTTLE_DISABLED=1 venv/bin/pytest tests/ -v -m "ai_integration"

test-calendar:
	@if [ ! -d "venv" ]; then \
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo " Running Google Calendar API tests..."
	THROTTLE_DISABLED=1 venv/bin/pytest tests/ -v -m "real_api"

test-all:
	@if [ ! -d "venv" ]; then \
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo " Running tests (including AI integration; excluding real API)..."
	THROTTLE_DISABLED=1 venv/bin/pytest tests/ -v -m "not real_api"

lint:
	@if [ ! -d "venv" ]; then \
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/ruff check .

format:
	@if [ ! -d "venv" ]; then \
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/ruff format .

typecheck:
	@if [ ! -d "venv" ]; then \
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/pyright

audit:
	@if [ ! -d "venv" ]; then \
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/pip-audit

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
	@echo " Images rebuilt (clean build)"

# Cleanup
clean: down
	@echo "Cleaning up containers and images..."
	@if command -v podman-compose >/dev/null 2>&1; then \
		podman-compose down --rmi all --volumes || true; \
	elif command -v docker-compose >/dev/null 2>&1; then \
		docker-compose down --rmi all --volumes || true; \
	fi
	@echo " Cleanup complete"

clean-podman:
	@echo "Cleaning up all podman containers and images..."
	@if command -v podman >/dev/null 2>&1; then \
		podman stop $$(podman ps -aq) 2>/dev/null || true; \
		podman rm $$(podman ps -aq) 2>/dev/null || true; \
		podman rmi $$(podman images -q) 2>/dev/null || true; \
		podman system prune -af --volumes 2>/dev/null || true; \
		echo " Podman cleanup complete"; \
	else \
		echo "  podman not found, skipping"; \
	fi

clean-all: clean-podman db-reset
	@echo " Full cleanup complete (podman + database)"

# Database
db-reset:
	@if [ -f services/database/waste_schedule.db ]; then \
		rm services/database/waste_schedule.db; \
		echo " Database deleted"; \
	else \
		echo "  Database file not found"; \
	fi

# Scraper and API
run-scraper:
	@if [ ! -d "venv" ]; then \
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo " Running scraper (with AI parsing)..."
	venv/bin/python services/scraper/main.py

run-scraper-skip-ai:
	@if [ ! -d "venv" ]; then \
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo " Running scraper (skip AI, traditional parser only)..."
	venv/bin/python services/scraper/main.py --skip-ai

run-api:
	@if [ ! -d "venv" ]; then \
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo " Starting API server on http://localhost:3333..."
	venv/bin/python services/api/app.py

run-calendar:
	@if [ ! -d "venv" ]; then \
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo " Starting calendar worker..."
	venv/bin/python services/calendar/worker.py

run-all: run-scraper
	@echo ""
	@echo " Scraper completed. Starting API server..."
	@$(MAKE) run-api

# Calendar cleanup
clean-calendars-dry-run:
	@if [ ! -d "venv" ]; then \
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo " Checking for orphaned calendars (dry run)..."
	venv/bin/python -c "from services.calendar import cleanup_orphaned_calendars; cleanup_orphaned_calendars(dry_run=True)"

clean-calendars:
	@if [ ! -d "venv" ]; then \
		echo "  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	@echo "  WARNING: This will DELETE orphaned calendars from Google Calendar!"
	@echo "   Orphaned calendars are those that exist in Google but not in the database."
	@read -p "   Are you sure? Type 'yes' to continue: " confirm && [ "$$confirm" = "yes" ] || exit 1
	@echo "  Deleting orphaned calendars..."
	venv/bin/python -c "from services.calendar import cleanup_orphaned_calendars; cleanup_orphaned_calendars(dry_run=False)"
