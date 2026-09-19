#!/bin/sh
# Regenerate frontend/src/types/api.gen.ts from the backend's OpenAPI schema
# (roadmap #22). CI runs this and fails if the committed file differs, so
# the frontend's types can't silently drift from what the API returns.
#   ./scripts/gen-api-types.sh            (uses backend/.venv if present)
#   PYTHON=python3 ./scripts/gen-api-types.sh
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PY=${PYTHON:-"$ROOT/backend/.venv/bin/python"}
[ -x "$PY" ] || PY=python3
SPEC=$(mktemp -t openapi.XXXXXX)
STORE=$(mktemp -d -t cre-openapi.XXXXXX)
# Importing the app runs startup (migrations etc.): point it at scratch
# storage so generating types never touches real data.
(cd "$ROOT/backend" && CRE_STORAGE_ROOT="$STORE" "$PY" -c \
  "import json, sys; from app.main import app; json.dump(app.openapi(), sys.stdout, sort_keys=True)") > "$SPEC"
(cd "$ROOT/frontend" && npx --no-install openapi-typescript "$SPEC" --empty-objects-unknown -o src/types/api.gen.ts)
rm -rf "$SPEC" "$STORE"
