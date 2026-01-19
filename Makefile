.PHONY: help test test-verbose test-coverage test-ai up down restart build clean prepare-fixture db-reset venv-activate venv-install

# Default target
help:
	@echo "Available commands:"
	@echo "  make venv-activate - Activate virtual environment (opens shell)"
	@echo "  make venv-install  - Create venv and install dependencies"
	@echo "  make test          - Run all tests (uses venv automatically, skips AI integration tests)"
	@echo "  make test-verbose  - Run tests with verbose output (skips AI integration tests)"
	@echo "  make test-coverage - Run tests with coverage report (skips AI integration tests)"
	@echo "  make test-ai       - Run AI integration tests ONLY (uses real Groq tokens)"
	@echo "  make prepare-fixture - Regenerate test fixture from real XLSX"
	@echo "  make up            - Start services (podman-compose up)"
	@echo "  make down          - Stop services"
	@echo "  make restart       - Restart services"
	@echo "  make build         - Build Docker images"
	@echo "  make clean         - Stop services and remove containers/images"
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
	venv/bin/pytest tests/ -v

test-verbose:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/pytest tests/ -vv

test-coverage:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/pytest tests/ --cov=scraper --cov=api --cov-report=term-missing

test-ai:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/pytest tests/ --use-ai-tokens -v -m ai_integration

prepare-fixture:
	@if [ ! -d "venv" ]; then \
		echo "⚠️  Virtual environment not found. Run: make venv-install"; \
		exit 1; \
	fi
	venv/bin/python tests/prepare_fixture.py

# Docker/Podman Compose
up:
	podman-compose up -d

down:
	podman-compose down

restart: down up

build:
	podman-compose build

rebuild: clean build
	@echo "✅ Images rebuilt (clean build)"

# Cleanup
clean: down
	podman-compose down --rmi all --volumes

# Database
db-reset:
	@if [ -f database/waste_schedule.db ]; then \
		rm database/waste_schedule.db; \
		echo "✅ Database deleted"; \
	else \
		echo "⚠️  Database file not found"; \
	fi
