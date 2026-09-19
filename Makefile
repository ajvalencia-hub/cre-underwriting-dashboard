# Developer shortcuts. GNU make; every target runs from the repo root.
#
#   make install       backend venv deps (runtime + dev) and frontend npm ci
#   make test          backend pytest (full suite incl. parity + goldens)
#   make parity        native-vs-Excel divergence table (LibreOffice mandatory)
#   make baseline      regenerate the Run-4 regression baseline (the guard
#                      refuses value changes unless BASELINE_ALLOW_VALUE_CHANGES)
#   make lint          ruff (backend app + tests) + oxlint (frontend)
#   make typecheck     mypy (backend, as CI: --python-version 3.12) + tsc -b
#   make gen-api       regenerate frontend/src/types/api.gen.ts from OpenAPI
#   make e2e           Playwright smoke (boots scratch-DB backend + Vite)
#   make build         frontend typecheck + production bundle
#   make docker        build the single-image app
#   make desktop-test  desktop shell tests (2 need macOS: fcntl / pyobjc)
#   make seed          load the demo deals (make seed ARGS="--dry-run")
#
# PY defaults to the backend venv (Scripts/python.exe on Windows,
# bin/python elsewhere); override with make test PY=/path/to/python.
# Recipes use POSIX sh syntax — on Windows run make from Git Bash.

ifeq ($(OS),Windows_NT)
PY ?= $(CURDIR)/backend/.venv/Scripts/python.exe
else
PY ?= $(CURDIR)/backend/.venv/bin/python
endif

ARGS ?=

.PHONY: help install test parity baseline lint typecheck gen-api e2e build docker desktop-test seed

help:
	@sed -n '2,19p' Makefile

install:
	"$(PY)" -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
	cd frontend && npm ci

test:
	cd backend && "$(PY)" -m pytest tests -q

parity:
	cd backend && "$(PY)" -m tests.parity.run --require-libreoffice

baseline:
	cd backend && UPDATE_BASELINE=1 "$(PY)" -m pytest tests/regression -q

lint:
	cd backend && "$(PY)" -m ruff check app tests
	cd frontend && npm run lint

typecheck:
	cd backend && "$(PY)" -m mypy --python-version 3.12
	cd frontend && npx tsc -b

gen-api:
	PYTHON="$(PY)" sh ./scripts/gen-api-types.sh

e2e:
	cd frontend && npx playwright test

build:
	cd frontend && npm run build

docker:
	docker compose build

desktop-test:
	"$(PY)" -m pytest desktop/tests -q

seed:
	cd backend && "$(PY)" scripts/seed_demo.py $(ARGS)
