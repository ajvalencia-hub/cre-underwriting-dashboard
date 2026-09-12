# CRE Underwriting Dashboard

A commercial-real-estate underwriting workbench: screen a deal on a napkin,
extract documents into structured inputs, compute full return metrics with a
native pro-forma engine (or through your own Excel model), benchmark the
assumptions against public data and a comps database, stress the deal, and
render an IC memo / deck.

**Stack:** React 19 / TypeScript / Vite / Tailwind (`frontend/`), FastAPI /
SQLAlchemy / SQLite / openpyxl (`backend/`). One Docker image serves both.
See [`ARCHITECTURE.md`](ARCHITECTURE.md) for the module map.

## Features (tabs in sidebar order)

- **Deals** — the pipeline home. Two boards, **Acquisitions** and
  **Developments**, each with its own stage registry (see
  [Dealflows](#dealflows)), plus an *untyped* strip for legacy deals that
  predate typed creation (assign a type inline). Per-deal: inline stage
  changes, staleness badges (per-stage thresholds), bulk status, saved views
  + CSV, **Share** (self-contained read-only HTML), **Deck** (one-page
  .pptx) and the full 8-slide **IC deck**, **archive / unarchive** (soft
  delete that keeps scenarios, notes and attachments), **clone** (what-if
  copy), versioned JSON **export / import**, an input **history** drawer
  with diff + undoable restore, a **file cabinet** (attachments with preview
  / download / delete) and a **notes** timeline, and **critical dates**
  (deadline strip + header chips). Every working session is a persistent,
  autosaved deal; scenarios scope to the active deal.
- **0. Quick Screen** — two back-of-napkin screens, one per dealflow:
  **development** (yield on cost vs exit cap with solve-for, inline
  sensitivity grid, perm-takeout check sized by the full engine) and
  **acquisition** (cap rate / cash-on-cash / DSCR). Shareable via URL
  params; "Send to Deal Inputs" seeds the full form.
- **1. Documents** — upload rent rolls / T-12s / OMs (xlsx, csv, pdf).
  Deterministic parsers with an LLM fallback (optional `ANTHROPIC_API_KEY`),
  OCR for scanned PDFs (optional Tesseract), classification, and a
  human-review gate: named cross-validation checks (pass/warn/fail) with
  failures requiring explicit acknowledgment — nothing is ever auto-applied.
  The **OM-to-deal wizard** chains upload → confirm types → extract → review
  → a new deal with provenance rows (resumable draft).
- **2. Template & Mapping** — upload your firm's Excel model, map schema
  fields to cells / named ranges (sheet-scoped names and merged cells
  handled), generate populated workbooks, optionally recalculated
  server-side via LibreOffice.
- **3. Deal Inputs** — the schema-driven form. **Compute (native)** produces
  40+ return metrics with the built-in pro-forma engine — no template
  required — including constraint-based debt sizing (LTV / DSCR / debt
  yield), the governing constraint, a rate/NOI stress grid, and an insurance
  stress when opex detail is on. Income models: multifamily unit mix,
  commercial lease-level rent rolls (escalations, NNN / base-year-stop /
  fixed recoveries, free rent, probability-weighted rollover with TI/LC
  below NOI, WALT), or both (mixed-use) with component NOI splits and
  optional per-component exit caps. Opex as flat fields or per-line detail
  (annual / per-unit / PSF / % of EGI, recoverable flags). Value-add layers
  (renovation program, loss-to-lease burn-off), capital-stack layers (GP
  fees, mezz / pref tranche, floating-rate senior debt with SOFR curve +
  cap, reserves + escrows), assumption presets, property-tax assessor
  lookup (Miami-Dade), address benchmarks (Census ACS, HUD FMR, FHFA, BLS,
  FEMA + the comps DB) with a demographics trend panel, and **goal-seek** on
  any numeric input.
- **4. Cash Flow** — the engine's period-level pro forma: annual table
  expandable to months, phase band, CSV export, per-lease drill-down, a
  hold-period sweep and a refi-vs-sale-at-stabilization comparison.
- **5. Sensitivity** — native-engine sweeps (any two inputs × any output
  metric, up to 25×25), or "Verify via Excel template". Runs save onto a
  scenario.
- **5b. Risk** — seeded **Monte Carlo** (≤6 correlated drivers via a
  Gaussian copula; P5–P95, tail probabilities, histogram), run as a
  background job and saved to a scenario / the memo's risk section.
- **6. Scenarios** — save / compare / load per-deal snapshots (diff-only
  comparison with direction-aware highlighting, tornado chart) and
  **Generate IC Memo** (.docx, or PDF via LibreOffice) with embedded charts.
- **7. Comps** — workspace-level sale / rent comps with market filtering,
  inline add, dedupe + staleness, a map, and a two-step Yardi-aware CSV
  importer. Comps feed the benchmark flags once ≥3 exist in a market.
- **Portfolio** — equity-weighted blended returns across active deals,
  exposure by market / asset class, concentration, CSV export.
- **Agent** — a per-deal chat assistant that answers only through the
  dashboard's own tools (compute, goal-seek, tornado, sensitivity, comps,
  market context), proposes input changes as reviewable cards instead of
  editing anything, and flags any number in its reply that no tool
  returned. Also available as a floating dock. See
  [Underwriting Agent](#underwriting-agent).
- **Settings** — **Appearance** (light / dark / system theme, applied before
  first paint), **Backups** (list daily / weekly snapshots, run now,
  restore, **download** the SQLite file) and **Integrations** (which optional
  API keys are configured — flags only, never values).

Global: **Cmd/Ctrl+K** search over deals / tenants / comps / notes,
Cmd/Ctrl+1..9 tab switching, an error boundary that posts to
`/api/client-errors`, and `X-Request-ID` on every response.

**Engine conventions are explicit inputs**: waterfall style (`european`
whole-fund IRR-hurdle or `american` deal-by-deal ledger), optional GP
catch-up %, IRR convention (`periodic_monthly` or date-based `xirr`,
Actual/365), development refi/takeout rate spread and costs. Defaults
reproduce the original behavior; the sidebar and memo footnote what was used.
Every engine input added since Run 4 (the Run-4 refinements themselves, then
the Run-5 renovation program, loss-to-lease, GP/AM fees, junior tranche,
floating-rate debt, reserves + escrows) defaults to reproducing the prior
run's outputs **byte-for-byte** (1e-9), pinned by the regression baseline
described under [Testing](#testing). `SUMMARY*.md` carry the per-feature
algebra.

The summary sidebar shows a strict provenance ladder: **server-recalc >
native engine > quick-screen "est."** — a lower tier never overwrites a
higher one.

## Dealflows

A deal's `inputs.dealType` (`acquisition` | `development`) picks its board and
its stage set. The registry lives in one place on each side of the wire —
`backend/app/data/input_schema.json` → `dealStages` and
`frontend/src/lib/dealStages.ts` — and a backend test plus a vitest pin both
to the same literals, so drift fails a suite.

| Dealflow | Stages (in order) | Terminal |
|---|---|---|
| Acquisition | `screening` → `underwriting` → `loi` → `under_contract` → `closed` / `dead` | `closed`, `dead` |
| Development | `screening` → `feasibility` → `site_control` → `entitlements` → `pre_construction` → `construction` → `lease_up` → `stabilized` / `dead` | `stabilized`, `dead` |

The stored `status` column accepts the **union** (`PUT /api/deals/{id}`
validates against it), so a deal that changes type never carries an invalid
status — its board shows a foreign stage as "(legacy)" until you move it.
Bulk status on a mixed selection offers only the shared stages (`screening`,
`dead`). Staleness thresholds relax for the long development stages
(entitlements / construction 45 / 90 days, pre-construction / lease-up
30 / 60) and never badge terminal stages.

## Underwriting Agent

A chat assistant scoped to the active deal — available as the **Agent**
workflow tab and as the floating **Agent** dock (bottom-right, stays open
across tabs; Escape closes it). Both show the same conversation: one thread
per deal.

**What it can do.** It answers questions about the deal by calling the
dashboard's own tools, never from memory:

| Tool | Kind | What it does |
| --- | --- | --- |
| `get_deal`, `list_scenarios`, `get_scenario` | read | The current deal's inputs/status and its saved scenarios (always scoped to the active deal). |
| `compute` | read | Runs the native pro-forma engine on a full input map. |
| `solve` | read | Goal-seek: which value of one numeric input hits a target output metric (backed by the same solver as the sidebar's ◎ Goal Seek). `values` defaults to the deal's inputs. |
| `run_tornado`, `run_sensitivity` | read | Perturbation / grid sensitivity. |
| `get_market_context`, `list_comps`, `get_schema` | read | Market data, saved comps, and the field registry. |
| `propose_input_changes`, `propose_scenario` | **write (proposal only)** | Produce a reviewable proposal with a computed preview. Never applied by the agent. |

Suggestion chips ("Screen this deal", "What's driving the levered IRR?",
"Stress-test this deal", "What exit cap gets me to a 15% IRR?") run canned
workflows with a restricted tool set.

**Proposals: approve / reject.** When the agent recommends a change it
creates a *proposal card* (before/after diff + preview metrics) instead of
editing anything. **Approve & apply** merges the change into the deal on the
server and records it in *Input history* as **Agent-applied** (restorable
like any other snapshot); every other pending proposal on that deal becomes
*stale* because its preview no longer matches the inputs. **Reject** takes an
optional note that is added to the thread.

**Grounding guarantee.** After every turn the server cross-checks each
number in the reply ($ amounts, percentages, multiples, "DSCR is 1.4"-style
figures) against the numbers returned by that turn's tool calls. Anything
that does not trace back to a tool result is shown under an amber
**Unverified** banner — it is flagged, not hidden. Each reply also lists its
tool calls (expand *N tool call(s)*).

**Providers and configuration** (all in `backend/.env`, see `.env.example`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `AGENT_PROVIDER` | `anthropic` | Provider for a NEW thread: `anthropic` or `openai`. |
| `ANTHROPIC_API_KEY` | — | Shared with document classification/extraction. |
| `ANTHROPIC_AGENT_MODEL` | `claude-sonnet-5` | Model for the Anthropic provider. |
| `OPENAI_API_KEY` | — | Only used by the agent. |
| `OPENAI_AGENT_MODEL` | `gpt-5.1` | Model for the OpenAI provider. |

Both are billed API usage. Without a key the provider reports itself
*unavailable* in the chat (nothing else in the app is affected). The
provider can be switched per thread from the picker at the top of the chat
— it applies to the next message, no restart; the picker greys out a
provider whose key is not configured.

**Cost / token view.** The Agent tab header shows the thread's cumulative
token count (hover for the input/output split and provider); the same
totals are logged per turn under the `app.agent` logger
(`tool_calls`, `proposals`, `unverified_claims`, token totals).

**Limits.** 25 tool calls and 15 compute-family calls per turn, 60 s wall
clock — a turn that hits a cap ends with an explicit "Stopped early" note.

**Limitations.**
- Non-streaming: a reply appears when the whole turn finishes.
- Single-user, per-deal threads; no thread reset/delete in the UI yet.
- The agent only sees what its tools return — it does not read uploaded
  documents directly (use the Documents extraction flow for that).
- The grounding check is numeric: it cannot verify qualitative claims.
- Scenario proposals (`propose_scenario`) are reviewable and approvable
  like input changes, but approval applies the changes to the deal's
  inputs rather than saving a separate named scenario.
- Provider switching only affects future turns; history is kept verbatim.

**Testing without a model.** The Playwright suite runs the backend with
`AGENT_PROVIDER=scripted`, a deterministic stub that exercises the real
tool loop, proposal approval and the unverified-claim gate with no network
access. It is not selectable from the UI.

## API surface

Every route is under `/api`; with `CRE_API_TOKEN` set, everything except
`/api/health` and `/api/auth/*` requires the token (Bearer / `X-API-Token`
header) or the session cookie.

| Area | Endpoints |
|---|---|
| Auth | `GET /api/auth/status`, `POST /api/auth/login` (sets the HttpOnly session cookie), `POST /api/auth/logout` |
| Deals | `GET /api/deals[?includeArchived=true]`, `POST /api/deals`, `GET/PUT/DELETE /api/deals/{id}` (`PUT` accepts `name`, `inputs`, `status`, template/mapping ids), `POST .../{id}/archive`, `POST .../{id}/unarchive`, `POST .../{id}/clone`, `POST /api/deals/from-extraction` (wizard finalize), `POST /api/deals/bulk-status`, `POST /api/deals/batch-deck` |
| Deal exports | `GET .../{id}/export` + `POST /api/deals/import` (versioned JSON bundle), `GET .../{id}/share.html`, `GET .../{id}/deck.pptx` (one page), `GET .../{id}/ic-deck.pptx` (8 slides) |
| Deal history | `GET .../{id}/history`, `GET .../{id}/history/{snapshotId}`, `POST .../{id}/history/{snapshotId}/restore` |
| File cabinet and notes | `GET/POST .../{id}/attachments`, `GET .../attachments/{docId}/download`, `GET .../attachments/{docId}/preview`, `DELETE .../attachments/{docId}`; `GET/POST .../{id}/notes`, `PUT/DELETE .../notes/{noteId}` |
| Compute | `POST /api/compute[?detail=true]` (outputs + debt + period statement; LRU-cached), `POST /api/compute/hold-sweep`, `POST /api/compute/tornado`, `POST /api/compute/goal-seek` + `GET /api/compute/goal-seek/inputs`, `POST /api/compute/monte-carlo` then `GET /api/compute/monte-carlo/{jobId}` (background job, poll) |
| Templates | `GET /api/templates`, `POST /api/templates/upload`, `GET /api/templates/{id}`, `GET /api/templates/{id}/sheets/{sheet}/grid`, `DELETE /api/templates/{id}` |
| Mappings | `GET/POST /api/mappings`, `GET /api/mappings/auto-match/{templateId}`, `GET/PUT/DELETE /api/mappings/{id}` |
| Generate | `POST /api/generate` (populated template xlsx, `X-Generation-*` headers), `POST /api/generate/model` (formula-live native Excel model; refuses unsupported shapes with a blocker list) |
| Sensitivity | `POST /api/sensitivity` (mode: `native` or `template`) |
| Documents and extraction | `GET /api/documents`, `POST /api/documents/upload`, `PUT /api/documents/{id}/type`, `DELETE /api/documents/{id}`; `POST /api/extraction`, `GET /api/extraction/{id}`, `POST /api/extraction/{id}/confirm` |
| Scenarios | `GET/POST /api/scenarios`, `GET/PUT/DELETE /api/scenarios/{id}`, `PUT .../{id}/sensitivity`, `PUT .../{id}/monte-carlo`, `POST .../{id}/memo[?format=pdf]` |
| Market | `GET /api/market/rates` (FRED, 24h cache), `POST /api/market/benchmarks` (public sources + comps DB), `GET /api/demographics`, legacy `GET /api/market-context` |
| Comps | `GET/POST /api/comps/{sale or rent}`, `PUT/DELETE /api/comps/{kind}/{id}`, `GET /api/comps/{kind}/map`, `POST /api/comps/import` (preview without mapping; insert with), `POST /api/comps/import/file` |
| Property tax | `GET /api/property-tax/counties`, `POST /api/property-tax/lookup` |
| Presets | `GET /api/presets/fields`, `GET/POST /api/presets`, `PUT/DELETE /api/presets/{id}` |
| Portfolio | `GET /api/portfolio`, `GET /api/portfolio/export.csv` |
| Search | `GET /api/search?q=` (deals / tenants / comps / notes; prefix ranks above substring) |
| Underwriting Agent | `GET /api/agent/threads/{dealId}`, `POST /api/agent/threads/{dealId}/messages` (one full turn; `content` or `playId`), `PUT /api/agent/threads/{dealId}/provider`, `GET /api/agent/plays`, `GET /api/agent/providers`, `POST /api/agent/proposals/{id}/approve`, `POST /api/agent/proposals/{id}/reject` |
| Admin | `GET /api/admin/integrations` (configured-key flags), `GET /api/admin/backups`, `POST /api/admin/backups/run`, `POST /api/admin/backups/restore`, `GET /api/admin/backups/{kind}/{name}/download` |
| Ops / schema | `GET /api/health`, `POST /api/client-errors` (error-boundary sink), `GET /api/schema` |

## Development setup

Toolchain pins: `.python-version` (3.12), `.nvmrc` (22; `frontend/package.json`
declares `engines.node >= 22`), `.editorconfig`.

```bash
# Backend (Python 3.12)
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt   # Windows; use bin/ on unix
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm ci
npm run dev        # http://localhost:5173, proxies /api to :8000 (VITE_API_PORT overrides)
```

Dependencies are split: `backend/requirements.txt` is the **runtime** set
(what the Docker image installs); `backend/requirements-dev.txt` adds pytest,
ruff, mypy and pip-audit (pinned) on top. `backend/pyproject.toml` holds the
ruff / mypy configuration (the lint and typecheck gates are not wired into CI
yet — the Makefile targets echo a placeholder until they are).

A root `Makefile` wraps the common loops: `make test` (backend suite),
`make parity`, `make baseline`, `make lint`, `make typecheck`, `make e2e`,
`make build`, `make docker`, `make seed`, `make install`. On Windows the
Python path is picked automatically (`backend/.venv/Scripts/python.exe`);
override with `make test PY=...` elsewhere.

Optional system tools — everything degrades gracefully without them:

- **LibreOffice** — server-side recalc of generated workbooks, memo PDF, and
  the Excel parity harness. Without it, generated files still open correctly
  in Excel (`fullCalcOnLoad` is set) and parity tests skip with a reason
  (CI makes it mandatory, see below).
- **Tesseract + Poppler** — OCR for scanned PDFs; otherwise scanned documents
  ask for manual classification.

### Demo data

`backend/scripts/seed_demo.py` fills a workspace with three acquisition deals
(value-add multifamily, two-tenant office, grocery-anchored retail) and two
development deals (garden multifamily, spec industrial) — realistic inputs
that all compute through the native engine — spread across both stage
registries, plus six sale comps, six rent comps and one note per deal.

```bash
cd backend
.venv/Scripts/python scripts/seed_demo.py --dry-run     # compute + print, write nothing
.venv/Scripts/python scripts/seed_demo.py               # seed the configured DB
CRE_DB_PATH=/tmp/demo.sqlite3 .venv/Scripts/python scripts/seed_demo.py   # a scratch DB
.venv/Scripts/python scripts/seed_demo.py --replace     # re-seed (drops the previous seed rows)
```

It targets whatever `app.config` resolves (`CRE_DB_PATH`, else
`<storage root>/db/app.sqlite3`), refuses to double-seed, and tags its comps
(`source = seed_demo`) so `--replace` only removes its own rows.

### Configuration

Set in `backend/.env` (see `.env.example`) or the environment; the Docker
compose file forwards the ones marked (c). All optional.

| Variable | Purpose | Default |
|---|---|---|
| `CRE_STORAGE_ROOT` (c) | Root for templates / generated files / uploads / DB / backups / cache | `backend/storage` (image: `/data`) |
| `CRE_DB_PATH` | SQLite file override (the Playwright smoke and the seed script use it for scratch DBs) | `<storage root>/db/app.sqlite3` |
| `CRE_FRONTEND_DIST` | Built SPA directory the backend serves at `/` | unset in dev (Vite serves it); image: `/app/frontend_dist` |
| `CRE_ENABLE_BACKUP_SCHEDULER` (c) | `1` starts the in-process daily backup loop | off (image: on) |
| `CRE_API_TOKEN` | Shared API token gate (see Auth above); generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"` | unset = no gate |
| `ANTHROPIC_API_KEY` (c) | LLM fallback for document classification and extraction (billed usage) | unset = heuristics only |
| `ANTHROPIC_CLASSIFIER_MODEL` | Model for document-type classification | `claude-haiku-4-5-20251001` |
| `ANTHROPIC_EXTRACTION_MODEL` | Model for structured extraction | `claude-sonnet-5` |
| `FRED_API_KEY` (c) | Index rates (SOFR seed, market rates) | unset = graceful nulls |
| `CENSUS_API_KEY` (c), `HUD_API_TOKEN` (c), `BEA_API_KEY` (c), `BLS_API_KEY` | Benchmark / demographics sources (BLS works unauthenticated at low volume) | unset = that source reports `unavailable` |
| `FIRM_NAME` (c), `MEMO_BRAND_COLOR` (c) | IC memo / deck branding (hex, no `#`) | `Acme Real Estate Partners`, `1F3B57` |
| `VITE_API_PORT` | Frontend dev-server proxy target port | `8000` |
| `UPDATE_BASELINE`, `UPDATE_GOLDEN` | Test-only regeneration switches (see Testing) | unset |

## Docker quickstart

One command builds the SPA, bakes in LibreOffice + Tesseract + Poppler, and
serves the whole app (UI + API) on `http://localhost:8000`:

```bash
docker compose up --build
```

The SQLite database, uploads, and rotating backups live on the named volume
`cre-data` (mounted at `/data`), so they survive rebuilds. Set optional API
keys in a `.env` beside `docker-compose.yml`. The image runs as an
unprivileged user (`app`, uid 1000), carries a `HEALTHCHECK` on
`/api/health`, and excludes the test tree. Upgrading a volume that an older
root-run image created? Fix ownership once:
`docker compose run --rm --user root app chown -R app:app /data`.

### Backups and restore

- **Automatic:** a daily SQLite snapshot (online-backup API, safe during
  writes) under `/data/backups/daily/`, promoted to a weekly snapshot on the
  first run of each ISO week. Rotation keeps the last **7 daily** and **4
  weekly**. Each snapshot is a timestamped directory with `app.sqlite3` plus a
  `manifest.json` listing uploads by name/hash (upload bytes are **not**
  copied — they already share the data volume; the manifest lets you confirm
  none went missing after a restore).
- **On demand:** `POST /api/admin/backups/run`; list with
  `GET /api/admin/backups`; download a snapshot's DB with
  `GET /api/admin/backups/{kind}/{name}/download` — all three are on the
  Settings page.
- **Restore:** `POST /api/admin/backups/restore` with `{"kind","name"}`
  overwrites the live DB from that snapshot, then **restart the backend** so
  SQLAlchemy reopens the file. The response returns the uploads manifest so
  you can verify every referenced file is still present on the volume.

## Testing

```bash
cd backend
.venv/Scripts/python -m pytest tests -q                         # full suite incl. parity + goldens
.venv/Scripts/python -m tests.parity.run                        # native-vs-Excel divergence table
.venv/Scripts/python -m tests.parity.run --require-libreoffice  # ...and fail instead of SKIPPED
UPDATE_GOLDEN=1 pytest tests/test_extraction_golden.py          # regenerate extraction goldens
UPDATE_BASELINE=1 pytest tests/regression                       # Run-4 payload baseline: EXPANSION only

cd frontend
npm test && npm run build && npm run lint
npm run e2e     # Playwright smoke: boots a scratch-DB backend + Vite, one happy path
```

`tests/conftest.py` redirects `CRE_STORAGE_ROOT` / `CRE_DB_PATH` to a
throwaway directory before `app.config` is imported, so the suite never
touches `backend/storage`, and provides the shared `session_factory` /
`client` fixtures (in-memory SQLite, migrations applied, `get_db` overridden).

The tiers, from fastest to slowest: pure engine / service unit tests; API
tests through `TestClient`; the **three-way parity harness** (native engine
vs the openpyxl+LibreOffice template path over synthetic templates, and vs
the formula-live Excel model export — tolerances currency ±$1, percent ±1bp,
multiples ±0.001, IRR ±2bp; drop real firm templates into
`backend/tests/parity/corpus/dropin/`, gitignored, to check them ad hoc);
extraction **goldens**; the **Run-4 regression baseline**
(`tests/regression/`: seven fixtures' full `/api/compute?detail=true`
payloads, floats to 1e-9 — six with every post-Run-4 input at its default,
plus `feature_on_value_add` with the value-add and capital-stack features
switched on). `UPDATE_BASELINE=1` only ever *expands* a baseline — a new
case or new keys are written; if any existing value differs the regeneration
is refused and nothing is written (`expansion_violations`, unit-tested in
`test_baseline_guard.py`). Frontend: vitest over `src/lib/*.test.ts` (pure
modules, including the stage-registry sync test) and the Playwright canary.

CI (`.github/workflows/ci.yml`, on pushes to `main` and every PR, one
in-progress run per ref) runs the backend suite with LibreOffice + Tesseract
installed and the parity CLI with `--require-libreoffice`, the frontend
build / lint / test gates, a Docker job (`compose config`, image build, then
boots the image and curls `/api/health`), and the Playwright e2e job.
`pip-audit` and `npm audit --audit-level=high` run as advisory,
non-blocking steps; Dependabot (`.github/dependabot.yml`) proposes weekly
pip / npm / actions bumps.

## Project documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — module map (backend routers →
  services → engine, extraction pipeline, data sources, storage layout;
  frontend state ownership and pure modules), test tiers, compatibility rules.
- `SUMMARY.md` … `SUMMARY5.md` — every financial formula in plain algebra per
  build run, plus decision/blocked deltas and manual QA checklists.
- [`SUMMARY6.md`](SUMMARY6.md) — the Run-6 audit: what was found, what
  changed, the two pending compatibility flips (`constructionFeeBasis`,
  detail-mode break-even recoveries) with their exact baseline deltas, the
  updated Excel-export refusal list and the QA checklist.
- `DECISIONS.md` — financial-convention decisions with rejected alternatives.
- [`docs/history/FINDINGS.md`](docs/history/FINDINGS.md) — the correctness
  audit (all C/H/M items resolved); code comments still cite it by item id.
- [`docs/history/BLOCKED.md`](docs/history/BLOCKED.md) — blocked-item log
  (everything cleared).
