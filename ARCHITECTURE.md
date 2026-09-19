# Architecture

This is a map of where things live and the rules that keep the parts
compatible. It covers structure only. For the formulas, read the code. The
financial algebra and the convention decisions are in `SUMMARY*.md` and
`DECISIONS.md`, and the plan is in `docs/roadmap.md`.

```
frontend/  React 19 + TypeScript + Vite + Tailwind SPA        (npm run dev → :5173, proxies /api)
backend/   FastAPI + SQLAlchemy 2 + SQLite + openpyxl API     (uvicorn app.main:app → :8000)
desktop/   pywebview shell: runs the backend in-process and serves the built SPA in a native window (macOS)
Dockerfile one image: Vite build → served by the backend at / (StaticFiles, html=True)
```

## Backend (`backend/app`)

### Boot (`main.py`)

`app.config` loads `backend/.env` and resolves every path from the
environment **at import time** (`CRE_STORAGE_ROOT`, `CRE_DB_PATH`). It also
creates the storage folders. `main.py` then runs these steps in order:

1. `database.prepare_migrations()` refuses a database from a newer build
   (`DatabaseTooNewError`). If an existing database is about to be migrated,
   it backs it up first as a `pre_migration` backup.
2. `Base.metadata.create_all` creates any missing tables.
3. `database.run_migrations()` runs hand-rolled, idempotent check-and-patch
   steps. There is no Alembic. It then stamps `SCHEMA_VERSION` into SQLite
   `user_version`.
4. `storage_maintenance.sweep_generated_files()` clears old files from
   `generated/`.
5. `presets.seed_presets` seeds the assumption presets.
6. The backup scheduler starts only when `CRE_ENABLE_BACKUP_SCHEDULER=1`.
   The Docker image sets this flag.

Two middlewares wrap every request:

- The optional `CRE_API_TOKEN` gate (`auth.py`). It accepts a bearer token,
  an `X-API-Token` header, or the HMAC session cookie that `/api/auth/login`
  sets. `/api/health` and `/api/auth/*` stay public. It is a no-op when the
  token is unset, which covers the desktop app because its launcher has its
  own gate.
- Request-id logging. It echoes a sanitized `X-Request-ID` and sets
  `nosniff`.

The routers mount after that. When `CRE_FRONTEND_DIST` is set, the SPA
mounts last.

### Layers

```
routers/        thin HTTP layer: pydantic request models (schemas.py), ORM via get_db, services out
api_models.py   response models (ApiModel, extra="allow") for routes that build dicts — the API
                contract that becomes frontend/src/types/api.gen.ts
services/       all behavior; pure where possible (dict in → dict out)
services/proforma/   the native engine — the only place a financial formula lives
models.py       SQLAlchemy tables; database.py  engine/session, migrations, SCHEMA_VERSION
data/input_schema.json   THE input/output schema: sections → fields, outputs, dealTypes,
                         dealStages, propertyTypes — drives the form, the engine's field ids and
                         input validation, mapping, presets, parity tolerances
```

**API contract.** A JSON route that the UI reads declares
`response_model=` with an `ApiModel`. The model declares only the keys that
are always present. Conditional blocks, such as compute's `gpEconomics`,
stay undeclared, and `extra="allow"` passes them through unchanged.
`scripts/gen-api-types.sh` dumps the OpenAPI schema from a scratch-storage
import of `app.main` and regenerates `frontend/src/types/api.gen.ts`. You
can also run it as `npm run gen:api` or `make gen-api`. CI regenerates the
file and fails on any diff. `frontend/src/types/apiContract.ts` asserts at
compile time that each generated shape fits the type the UI reads it as.

| Router | Service(s) it fronts |
|---|---|
| `deals` | `deal_history` (input snapshots: `baseline` / `autosave` / `restore` / `agent`), `deck_service` (pptx), `share_html`, `proforma.engine`, bundle export/import (`EXPORT_SCHEMA_VERSION`), archive / clone, tags, bulk status, from-extraction wizard |
| `ic` | `ic_workflow`: the investment-committee event log and the input lock (see below) |
| `file_cabinet` | deal attachments (`Document` rows through `document_storage`) + `DealNote` |
| `compute` | `proforma.engine` via `compute_cache` (LRU on canonical-JSON inputs, deep-copied hits), `hold` sweep / refi-vs-sale, `tornado_service`, `goal_seek`, `monte_carlo` (background jobs: poll, cancel) |
| `templates`, `mappings`, `generate` | `template_service` (sheet/named-range inventory), `mapping_service` (auto-match, flat field list), `mapping_preview`, `excel_writer` (inject values through named ranges, sheet-scoped names and merge anchors, then read outputs back), `recalc_service` + `soffice` (LibreOffice headless), `recalc_agreement` (does LibreOffice compute this template the way Excel did?), `excel_model_export` (formula-live workbook that refuses any feature it can't mirror) |
| `sensitivity` | `sensitivity_service` (native sweep, or the template path) |
| `documents`, `extraction` | `document_storage`, `document_classifier`, `extraction_service` (see the pipeline below); uploads capped by `upload_limit` |
| `scenarios` | scenario CRUD, saved sensitivity / Monte Carlo, `memo_service` + `memo_charts` (docx; PDF via LibreOffice), `benchmarks` for the memo's market flags |
| `market_rates`, `market_context`, `demographics` | `data_sources/*` through `benchmarks`, `market_context`, `demographics` (external calls rate-limited per route) |
| `comps` | `comps` (CRUD, CSV import mapping, normalization, bidirectional `market_matches`) |
| `property_tax` | `property_tax/miami_dade` (assessor lookup + reassessment model) |
| `presets` | `presets` (seeded + user assumption bundles, whitelisted field ids) |
| `portfolio` | `portfolio` (roll-up over active deals) |
| `search` | `sql_like` (LIKE-escaped ranking over deals, tenants, comps, notes) |
| `agent` | `services/agent` (the Underwriting Agent; see below) |
| `admin` | `backup_service` (SQLite online-backup snapshots; kinds `daily` / `weekly` / `pre_restore` / `pre_migration`), restore, download, integration flags |
| `auth`, `client_errors`, `schema`, `/api/health` | `auth`, the client error log sink, the schema file |

### Investment-committee lock (`services/ic_workflow.py`)

A deal's IC state is derived from its `IcEvent` rows:
`draft → submitted → approved | rejected`, with `return` / `reopen` going
back to `draft`. While a deal is submitted, approved or rejected, its
underwriting inputs are locked. `UNLOCKED_KEYS` (the Quick Screen napkins,
critical dates, `_provenance`) stay editable. Every server path that writes
`Deal.inputs` calls `ic_workflow.check_input_change(db, deal, new_inputs)`
before it records a snapshot. On a lock the route returns 409
`{"detail": ...}`. The paths include `PUT /api/deals/{id}`, history
restore and agent proposal approval. The frontend's `lib/icWorkflow.ts`
(`isLockedField`) and `App.tsx`'s `blockedByIcLock` refuse locked edits
before they're made, because an autosave the server refused would keep
retrying.

### The pro-forma engine (`services/proforma`)

`engine.compute(inputs) -> {outputs, debt, sourcesAndUses, statement, warnings, ...}`
first runs `input_validation.validate_inputs`, which checks input types and
ranges against `input_schema.json`:

- Numeric text is read as a number, with a warning.
- A non-number in a numeric field raises `InsufficientInputsError` naming the
  field. Routes return 422 `{"detail", "missing"}`.
- An out-of-range value is computed as entered, with a warning.

After validation, `compute` sets the analysis calendar and orchestrates the
sibling modules, where most of the formulas live:

| Module | Owns |
|---|---|
| `input_validation` | schema type/range checks (above) |
| `timeline` | month calendar, phases (construction / lease-up / operating / exit), analysis start date |
| `development` | cost budget, S-curve draws, capitalized interest, takeout |
| `for_sale` | build-to-sell homes (single-family / townhouse development with a sale price per home): its own cash flow with no NOI, hold or exit cap |
| `operations` | rent / vacancy / other income / opex vectors, unit mix, renovation + loss-to-lease, opex detail, reassessment, hotel operations (USALI summary) |
| `leases` | commercial rent roll: escalations, recoveries, free rent, probability-weighted rollover, TI/LC, WALT |
| `debt` | sizing (LTV / DSCR / debt yield / manual), amortization, IO, fixed vs floating (curve, floor, cap), junior tranche, stress grid |
| `equity` | LP/GP waterfall (european / american, catch-up), GP fees |
| `returns` | IRR (periodic monthly / xirr, multi-root warning), multiples, NPV, payback, cash-on-cash |
| `hold` | hold-period sweep and refi-vs-sale comparison (re-runs `compute`) |

Some deal-level assembly stays in `engine.py` itself: the maturity refinance
when the loan term ends before exit, the prepayment cost at sale, the
construction-loan block, the waterfall hand-off and the period statement.
Outputs are additive and listed in `input_schema.json → outputs`. Examples
are `goingInDebtYield`, `prepaymentCost` and the annual `minDscr`. The
period statement is built from the same cash-flow vectors as the metrics
and is never recomputed separately.

### The Underwriting Agent (`services/agent`, `routers/agent.py`)

There is one chat thread per deal (`AgentThread`), and each POST is one
non-streaming turn. Each turn works as follows:

1. `runner.run_turn` calls the thread's provider through the vendor-neutral
   `providers/` layer (`anthropic`, `openai`, `scripted`).
2. It executes read tools inline.
3. It stores write-tool results as `AgentProposal` rows.
4. It stops at the tool, compute or wall-clock caps.

Tools are registered in `tools/registry.py`:

- **Read tools** (`read_tools.py`) wrap existing services: `compute`,
  `solve` (goal-seek), `run_tornado`, `run_sensitivity`, comps, market
  context and schema. Invalid inputs come back as tool errors.
- **Write tools** (`write_tools.py`) take no database session, so they can
  only return a proposal. A structural test enforces this.

Approving a proposal re-validates the changes (422) and runs the IC lock
(409), in that order. Only then does it apply the changes as a
`deal_history` snapshot of kind `agent` and mark the other pending
proposals stale. `provenance.py` flags any number in the reply that no tool
produced this turn. Tool results reach the model wrapped as labeled data, to
guard against prompt injection. Configuration is environment-only
(`AGENT_PROVIDER`, `ANTHROPIC_AGENT_MODEL`, `OPENAI_AGENT_MODEL` and the API
keys). The UI switches a thread's provider per deal.

### Extraction pipeline (`services/extraction_service.py` + `extraction/`)

```
upload → Document row; bytes stored once per content hash (document_storage — shared by the
         Documents tab and any number of deal attachments; removed with the last row)
       → document_classifier: keyword heuristics, LLM fallback for ambiguous, manual override
       → raw extraction: excel_extractor (xlsx/csv grid) | pdf_extractor (pdfplumber tables;
         scanned → extraction/ocr via Tesseract)
       → deterministic parse: rent_roll_parser (unit-mix / commercial-lease proposals),
         t12_parser, operating_statement_parser (combined rent roll + income statement)
       → llm_extraction when deterministic finds too little, and directly for OMs / "other"
       → aggregation into input-schema field proposals with provenance + confidence
       → cross_validation: named checks (pass / warn / fail)
       → ExtractionResult row; POST .../confirm applies only user-confirmed values
```

Nothing is applied automatically. The review screen (`ExtractionReview`) is
the only path from a document into deal inputs.

### Data sources (`services/data_sources`)

There is one module per free public source: `census_acs`, `hud`, `fhfa`,
`bls`, `bea`, `fema`, `fred` and `geocode`. When a key is missing or a call
fails, a module returns `dataSource: "unavailable"` instead of raising.
`source_cache` keeps successful payloads on disk with a 24-hour TTL.
Failures are never cached.

### Storage layout (`CRE_STORAGE_ROOT`: default `backend/storage`, image `/data`, desktop Application Support)

```
templates/        uploaded Excel models
documents/        uploads + deal attachments, one file per content hash
generated/        transient: populated workbooks, recalc scratch dirs (swept at startup)
db/app.sqlite3    the database (CRE_DB_PATH overrides the file)
backups/<kind>/<ts>/   app.sqlite3 + manifest.json (daily, weekly, pre_restore, pre_migration)
```

## Desktop app (`desktop/`)

`launcher.py` runs as a single process:

1. `cre_desktop/paths.py` picks the macOS app-data locations and sets
   `CRE_STORAGE_ROOT`.
2. `keys.py` copies the optional API keys from the Keychain into the
   environment. The keys are listed in `KNOWN_KEYS`, which mirrors
   `/api/admin/integrations`.
3. Only then is the backend imported.
4. `server.py` runs uvicorn on a thread, on an OS-picked `127.0.0.1` port.
   The ASGI app is wrapped in a per-launch cookie gate.
5. pywebview opens the window.

Other desktop modules:

- `bridge.py` exposes a small, origin-checked `window.pywebview.api`: native
  file dialogs, key storage and settings. On the frontend, `lib/platform.ts`
  (`isDesktop`) routes file handling through the bridge.
- `updates.py` checks GitHub Releases at most once a day. It only notifies;
  nothing is downloaded.
- `selftest.py` backs `--self-test`, which runs against the frozen build.
- `cre_underwriting.spec`, `build_mac.sh` and `sign_mac.sh` produce the
  `.app`.

## Frontend (`frontend/src`)

`main.tsx` applies the stored theme before first paint (`lib/uiPrefs`). It
then renders `App` inside `ErrorBoundary`, which posts errors to
`/api/client-errors`. There is no router:

- `app/navigation.ts` owns the `TABS` list, the grouped left rail
  (`NAV_GROUPS`, rendered by `ModuleNav`), `MULTI_DEAL_TABS` (views without
  the one-deal sidebar) and the remembered last tab.
- `App.tsx` holds `tab` state and renders every page, hidden with CSS
  `display` rather than unmounted.
- `app/useQuickScreens.ts` holds the Quick Screen napkin state, and
  `app/paletteCommands.ts` builds the command palette (Cmd/Ctrl+K) entries.

### State ownership (`App.tsx`)

`App` is the single owner of cross-tab state:

- the schema
- the deals list and `activeDealId`, persisted by `lib/dealPersistence`
- the autosaver (debounced `PUT /api/deals/{id}`; locked edits are refused
  before they're made, by `blockedByIcLock`)
- `formValues`, the Deal Inputs blob, with the napkin inputs serialized into
  it
- the IC summary
- the active template and mapping profile
- the modals: goal-seek, OM wizard, critical dates, palette, history drawer

`lib/useComputeResults.ts` owns the computed results: built-in engine and
Excel read-back. Each result is stamped with the deal and inputs it came
from (`lib/resultFreshness`), so a slow response can never paint another
deal's numbers. `MetricsSidebar` and `ResultsStatus` show the freshest
result and its provenance.

### `lib/`, `pages/`, `components/`, `types/`

- **`lib/`**: framework-free modules, most with a `*.test.ts` (vitest).
  Examples are `dealStages`, `staleness`, `pipelineViews`, `quickScreenMath`,
  `acquisitionQuickScreen`, `sensitivityMath`, `cashflowStatement`,
  `icWorkflow`, `inputChanges`, `snapshotDiff`, `provenance`, `money`,
  `numericInput` and `validateField`.
  - `api.ts` is the typed fetch layer: one function per endpoint, with
    `ApiError` carrying the status and `detail`.
  - `toast.ts` + `Toaster` provide notifications.
  - `platform.ts` handles desktop and browser differences.
- **`pages/`**: one page per tab. They are `PipelinePage`, `QuickScreen`,
  `Documents`, `TemplateUpload`, `CashFlowTab`, `SensitivityPanel`,
  `RiskPanel`, `ScenariosPanel`, `IcApprovalPage`, `CompsPage`,
  `PortfolioPage` and `SettingsPage`. `SettingsPage` includes
  `DesktopSettings` when running in the desktop app.
- **`components/`**: Deal Inputs is `DealInputForm`, built from the schema
  with the `fields/` primitives (`ScalarInput`, `TableField`,
  `KeyValueField`, `FieldRow`). The cross-cutting components are `Layout`,
  `ModuleNav`, `DealHeaderBar`, `CommandPalette`, `HistoryDrawer` +
  `SnapshotDiffView`, `FileCabinet`, `OmWizard`, `ExtractionReview`,
  `GoalSeekModal`, `UpdateBanner` and others.
- **`types/`**: hand-written payload types (`deal`, `scenario`, `schema`,
  …), the generated `api.gen.ts`, and `apiContract.ts`, which ties them
  together.

## Test tiers

| Tier | Where | What it pins | Regenerate |
|---|---|---|---|
| Unit | `backend/tests/test_*.py` | engine formulas against hand-derived analytic fixtures (`tests/fixtures/analytic_*.json`), parsers, services, migrations (`test_schema_version.py`) | — |
| API | same files, via the shared `client` / `session_factory` fixtures (`tests/conftest.py`: in-memory SQLite + migrations, `get_db` overridden, storage redirected to a temp dir before `app.config` loads) | routes, response models, IC 409s, validation 422s | — |
| Agent | `tests/test_agent_*.py` | tool privilege split, runner caps, provenance checker, providers (mocked SDKs), prompt-injection fencing, approve gates | — |
| Extraction goldens | `test_extraction_golden.py` + `tests/extraction_corpus/` | full structured result per synthetic document | `UPDATE_GOLDEN=1` |
| Parity | `tests/parity/` (`harness.py`, `cases.py`, `export_case.py`, `run.py`) | the injection layer, then native engine vs the LibreOffice-recalculated template and vs the native Excel export, under per-type tolerances | `python -m tests.parity.run [--require-libreoffice]` |
| Regression baseline | `tests/regression/test_run4_baseline.py` + `run4_baseline/*.json` | full `/api/compute?detail=true` payloads, floats to 1e-9 | `UPDATE_BASELINE=1`. Refused unless the diff only adds keys (`test_baseline_guard.py`); an owner-approved value move needs `BASELINE_ALLOW_VALUE_CHANGES` |
| Desktop | `desktop/tests/` | access gate, dialogs, PATH, quit cleanup, update check (two tests need macOS) | — |
| vitest | `frontend/src/**/*.test.ts` | the pure modules | — |
| e2e | `frontend/e2e/` (Playwright, chromium) | the real stack on a scratch DB (`CRE_DB_PATH`), backend :8123 / Vite :5273 | — |

`make test`, `make parity`, `make lint`, `make typecheck` and the other
targets wrap these (see the `Makefile` header). CI (`.github/workflows/ci.yml`)
runs the following jobs:

| Job | What it runs |
|---|---|
| `backend` | pytest, the parity CLI with `--require-libreoffice`, advisory `pip-audit` |
| `backend-lint` | `ruff check app tests`, `mypy --python-version 3.12` with a shrink-only ratchet list in `pyproject.toml` |
| `frontend` | build, lint, vitest, advisory `npm audit` |
| `api-contract` | regenerates `api.gen.ts` and fails on any diff |
| `docker` | builds the image, then a `/api/health` smoke |
| `frontend-e2e` | the Playwright suite |
| `desktop-shell`, `desktop-app` | desktop tests and the `.app` build, on macOS |

## Compatibility rules

1. **Defaults reproduce the previous run.** Every engine input added after a
   baseline was recorded must default to byte-identical outputs. Baseline
   regeneration only adds keys. A value can move only with the owner's
   approval, and every `[FIN]` convention change is recorded in
   `DECISIONS.md`.
2. **One formula, one place.** Financial math lives only in
   `services/proforma/*`. The Excel export mirrors it as formulas and
   refuses shapes it can't mirror. Parity checks keep the two consistent.
3. **Inputs are validated where they're computed.** `input_validation` is
   the one type and range check. The routes, the agent tools and
   `scripts/seed_demo.py` all rely on it.
4. **Every input write passes the IC lock.** `ic_workflow.check_input_change`
   runs before `deal_history.record_snapshot` on every path that writes.
5. **Stage registry in lockstep.** `input_schema.json → dealStages`,
   `schemas.py → DEAL_STAGES_BY_TYPE` and `lib/dealStages.ts` must agree.
   Tests on both sides pin the literals.
6. **Schema-driven surfaces.** Adding an input means editing
   `input_schema.json`. The form, validation, mapping, presets whitelist and
   parity tolerances all follow from it. Outputs are additive.
7. **Migrations are additive and idempotent.** Each step in `database.py`
   probes before it patches, and each new step bumps `SCHEMA_VERSION`. An
   older build refuses a newer database, and a database is backed up before
   it is migrated.
8. **The API contract is generated, not hand-kept.** A new or changed route
   response goes through `api_models.py`, then `gen-api`, then
   `apiContract.ts`.
9. **Deal bundles are versioned.** `EXPORT_SCHEMA_VERSION` guards import.
10. **Nothing is applied automatically.** Extraction results and agent
    proposals are proposals. Only values a person confirms or approves
    reach a deal.
11. **Graceful degradation.** A missing LibreOffice, Tesseract or API key
    turns the feature off and says why, never crashes. Parity *tests* skip
    without LibreOffice. CI runs the parity CLI with
    `--require-libreoffice`.
