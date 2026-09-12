# Developer shortcuts. GNU make; every target runs from the repo root.
#
#   make test        backend pytest (full suite incl. parity + goldens)
#   make parity      native-vs-Excel divergence table (needs LibreOffice)
#   make baseline    regenerate the Run-4 regression baseline (expansion only)
#   make lint        placeholder until the ruff pass lands
#   make typecheck   placeholder until the mypy pass lands
#   make e2e         Playwright smoke (boots scratch-DB backend + Vite)
#   make build       frontend typecheck + production bundle
#   make docker      build the single-image app
#
# Override PY on Windows:  make test PY=backend/.venv/Scripts/python.exe

PY ?= backend/.venv/bin/python
ifeq ($(OS),Windows_NT)
PY := backend/.venv/Scripts/python.exe
endif

.PHONY: help install test parity baseline lint typecheck e2e build docker seed

help:
	@sed -n '2,12p' Makefile

install:
	$(PY) -m pip install -r backend/requirements-dev.txt
	cd frontend && npm ci

test:
	cd backend && ../$(PY) -m pytest tests -q

parity:
	cd backend && ../$(PY) -m tests.parity.run --require-libreoffice

baseline:
	cd backend && UPDATE_BASELINE=1 ../$(PY) -m pytest tests/regression -q

# Placeholders: ruff / mypy are pinned in backend/requirements-dev.txt and
# configured in backend/pyproject.toml, but the codebase has not been
# formatted against them yet. A later pass swaps these echoes for the real
# commands (ruff check backend / mypy backend/app).
lint:
	@echo "lint: ruff not enabled yet (see backend/pyproject.toml)"
	cd frontend && npm run lint

typecheck:
	@echo "typecheck: mypy not enabled yet (see backend/pyproject.toml)"
	cd frontend && npx tsc -b

e2e:
	cd frontend && npx playwright test

build:
	cd frontend && npm run build

docker:
	docker compose build

seed:
	cd backend && ../$(PY) scripts/seed_demo.py
