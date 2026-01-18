.PHONY: help test test-verbose test-coverage up down restart build clean prepare-fixture db-reset venv venv-install

# Default target
help:
	@echo "Available commands:"
	@echo "  make venv          - Activate virtual environment (opens shell)"
	@echo "  make venv-install  - Create venv and install dependencies"
	@echo "  make test          - Run all tests"
	@echo "  make test-verbose  - Run tests with verbose output"
	@echo "  make test-coverage - Run tests with coverage report"
	@echo "  make prepare-fixture - Regenerate test fixture from real XLSX"
	@echo "  make up            - Start services (podman-compose up)"
	@echo "  make down          - Stop services"
	@echo "  make restart       - Restart services"
	@echo "  make build         - Build Docker images"
	@echo "  make clean         - Stop services and remove containers/images"
	@echo "  make db-reset      - Delete database file (requires services down)"

# Virtual Environment
venv:
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

# Testing
test:
	pytest tests/ -v

test-verbose:
	pytest tests/ -vv

test-coverage:
	pytest tests/ --cov=scraper --cov=api --cov-report=term-missing

prepare-fixture:
	python tests/prepare_fixture.py

# Docker/Podman Compose
up:
	podman-compose up -d

down:
	podman-compose down

restart: down up

build:
	podman-compose build

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
