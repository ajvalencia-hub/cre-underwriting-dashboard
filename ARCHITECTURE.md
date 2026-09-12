# Architecture

A map of where things live and which rules keep them compatible. Read the
code for the formulas — `SUMMARY*.md` and `DECISIONS.md` carry the financial
algebra and the convention decisions; this document is about structure.

```
frontend/  React 19 + TypeScript + Vite + Tailwind SPA        (npm run dev → :5173, proxies /api)
backend/   FastAPI + SQLAlchemy 2 + SQLite + openpyxl API     (uvicorn app.main:app → :8000)
Dockerfile one image: Vite build → served by the backend at / (StaticFiles, html=True)
```

## Backend (`backend/app`)

### Boot (`main.py`)

`app.config` is imported first and resolves every path from the environment
**at import time** (`CRE_STORAGE_ROOT`, `CRE_DB_PATH`), creating the storage
directories. `main.py` then runs `Base.metadata.create_all`,
`database.run_migrations()` (hand-rolled, idempotent, check-and-patch
steps — there is no Alembic), sweeps stale generated files, seeds the
assumption presets, optionally starts the backup scheduler
(`CRE_ENABLE_BACKUP_SCHEDULER=1`), and mounts the routers. Two middlewares
wrap every request: request-id logging (`X-Request-ID` echoed) and the
optional `CRE_API_TOKEN` gate (`auth.py`: bearer / `X-API-Token` header or
the HMAC session cookie that `/api/auth/login` sets; `/api/health` and
`/api/auth/*` stay public).

### Layers

```
routers/   thin HTTP layer: pydantic models in (schemas.py), ORM via get_db, services out
services/  all behavior; pure where possible (dict in → dict out)
services/proforma/   the native engine — the only place a financial formula lives
models.py  SQLAlchemy tables; database.py  engine/session + migrations
data/input_schema.json   THE input/output schema: sections → fields, outputs, dealTypes,
                         dealStages, propertyTypes — drives the form, the engine's field
                         ids, mapping, presets, parity tolerances
```

| Router | Service(s) it fronts |
|---|---|
| `deals` | `deal_history` (snapshots), `deck_service` (pptx), `share_html`, `proforma.engine`; export/import bundle (`EXPORT_SCHEMA_VERSION`), archive / clone, bulk status, wizard finalize |
| `file_cabinet` | attachments (deal-scoped `Document` rows under `DOCUMENTS_DIR`) + `DealNote` |
| `compute` | `proforma.engine` via `compute_cache` (LRU on canonical-JSON inputs, deep-copied hits), `hold` sweep, `tornado_service`, `goal_seek`, `monte_carlo` (background thread jobs, polled) |
| `templates`, `mappings`, `generate` | `template_service` (sheet/named-range inventory), `mapping_service` (auto-match, flat field list), `excel_writer` (inject values through named ranges / sheet-scoped names / merge anchors, read outputs back), `recalc_service` + `soffice` (LibreOffice headless, per-invocation profile), `excel_model_export` (formula-live workbook; raises `UnsupportedModelFeatures` with a blocker list) |
| `sensitivity` | `sensitivity_service` (native sweep, or the template path) |
| `documents`, `extraction` | `document_classifier`, `extraction_service` (see pipeline below) |
| `scenarios` | scenario CRUD + saved sensitivity / Monte Carlo, `memo_service` + `memo_charts` (docx; PDF via LibreOffice), `benchmarks` for the memo's market flags |
| `market_rates`, `market_context`, `demographics` | `data_sources/*` through `benchmarks`, `market_context`, `demographics` |
| `comps` | `comps` (CRUD, CSV import mapping, normalization: unit-type weighted → $/SF → pooled) |
| `property_tax` | `property_tax/miami_dade` adapter (assessor lookup + reassessment model) |
| `presets` | `presets` (seeded + user assumption bundles, whitelisted field ids) |
| `portfolio` | `portfolio` (equity-weighted roll-up over active, non-archived deals) |
| `search` | `sql_like` (LIKE-escaped prefix/substring ranking over deals, tenants, comps, notes) |
| `admin` | `backup_service` (sqlite online-backup snapshots, 7 daily / 4 weekly rotation, restore, download), integration flags |
| `auth`, `client_errors`, `schema`, `/api/health` | `auth`, log sink, schema file |

### The pro-forma engine (`services/proforma`)

`engine.compute(inputs) -> {outputs, debt, sourcesAndUses, statement, ...}`
is orchestration only; every formula lives in a sibling module and nothing
outside the package reimplements one:

| Module | Owns |
|---|---|
| `timeline` | month calendar, phases (construction / lease-up / operating / exit), month-end dates |
| `development` | cost budget, S-curve draws, capitalized interest, takeout |
| `operations` | rent / vacancy / other income / opex vectors, unit mix, renovation + loss-to-lease layers, opex detail, reassessment |
| `leases` | commercial rent roll: escalations, recoveries (NNN / base-year-stop / fixed), free rent, probability-weighted rollover, TI/LC, WALT |
| `debt` | sizing (LTV / DSCR / debt yield / manual), amortization, IO, fixed vs floating (SOFR curve, floor, cap), junior tranche, stress grid |
| `equity` | LP/GP waterfall (european / american, catch-up), GP fees |
| `returns` | IRR (periodic monthly / xirr), multiples, NPV, payback, cash-on-cash |
| `hold` | hold-period sweep and refi-vs-sale comparison (re-runs `compute`) |

`compute` assembles the blocks in this order (the comments in `engine.py`
mark each one): timeline → operating vectors (reserves folded above NOI only
under the `above_noi_underwritten` convention) → leasing capital below NOI →
component-level exit value (mixed-use) → floating-rate vector → cost basis,
financing and the two cash-flow vectors (index 0 = close, index `total` =
final month + exit; the period statement is built from the *same* vectors,
never recomputed) → rate-cap premium → reserves below NOI → tax/insurance
escrows (pure cash timing) → renovation program cash flows → junior tranche →
asset-management fee (partnership expense, levered only) → metrics under the
selected IRR convention → per-component yield on cost → debt metrics →
waterfall → GP compensation (conditional block) → debt-sizing detail + stress
grid → period-level statement (identities: `egi = gpr − vacancy − credit +
other`, `noi = egi − opex`, `levered = noi − debtService + draws − costs −
loanFees − leasingCapital + saleProceedsNet`) → per-year operating
break-evens → insurance stress (opex-detail mode only).

### Extraction pipeline (`services/extraction_service.py` + `extraction/`)

```
upload → Document row (hash-deduped under DOCUMENTS_DIR)
       → document_classifier: keyword heuristics, LLM fallback for ambiguous, manual override
       → raw extraction: excel_extractor (xlsx/csv grid) | pdf_extractor (pdfplumber tables,
         same-shape tables merged across pages; scanned → extraction/ocr via Tesseract)
       → deterministic parse: rent_roll_parser (multifamily unit-mix proposal / commercial
         lease proposal) or t12_parser (line items → categories, unmatched surfaced)
       → llm_extraction when deterministic finds too little, and directly for OMs / "other"
       → aggregation into input-schema field proposals with provenance + confidence
       → cross_validation: named checks (pass / warn / fail)
       → ExtractionResult row; POST .../confirm applies only user-confirmed values
```

Nothing is auto-applied: failures need explicit acknowledgment and the
review screen (frontend `ExtractionReview`) is the only path into deal
inputs. `deals/from-extraction` turns a confirmed result into a deal with
provenance rows (the OM wizard).

### Data sources (`services/data_sources`)

One module per free public source — `census_acs`, `hud` (FMR), `fhfa`
(HPA), `bls` (employment), `bea` (income), `fema` (flood zone), `fred`
(index rates), `geocode` (Nominatim + Census) — each returning
`dataSource: "unavailable"` instead of raising when its key is missing or the
call fails. `source_cache` keeps successful payloads on disk (24h TTL under
`<storage>/cache/benchmarks`); failures are never cached. `benchmarks`
composes them with the comps DB into per-input flags (`ok / caution /
warning`).

### Storage layout (`CRE_STORAGE_ROOT`, default `backend/storage`, image `/data`)

```
templates/        uploaded Excel models (hash-named)
documents/        extraction uploads + deal attachments
generated/        transient: populated workbooks, recalc scratch dirs (swept after 24h)
db/app.sqlite3    the database (CRE_DB_PATH overrides the file)
backups/daily/<ts>/ , backups/weekly/<ts>/   app.sqlite3 + manifest.json
cache/benchmarks/ data-source cache
```

## Frontend (`frontend/src`)

`main.tsx` applies the stored theme before first paint (`lib/uiPrefs`) and
renders `App` inside `ErrorBoundary` (which posts to `/api/client-errors`).
There is no router: `App.tsx` owns a `tab` state over the ordered `TABS`
list (`Deals`, `0. Quick Screen` … `7. Comps`, `Portfolio`, `Settings`) and
renders the matching page inside `Layout` (nav / main / summary sidebar).

### State ownership (`App.tsx`)

`App` is the single owner of cross-tab state; pages receive it as props:

- **schema + health** (`LoadState`) — `GET /api/schema` drives the form and
  the metric list; API reachability gates the provenance ladder.
- **deals** — the list, `activeDealId` (persisted in `localStorage`,
  `lib/dealPersistence`), rename / import preview, and the **autosaver**
  (`createAutosaver`: debounced `PUT /api/deals/{id}` with
  `idle / pending / saving / saved / error` states shown in the header).
- **formValues** — the Deal Inputs blob; `quickScreen` inputs (development
  napkin), `acquisitionQuickScreen` inputs and the active napkin `mode` are
  serialized into the same blob (`serializeDealInputs` / `hydrateDealState`).
- **outputs by provenance** — `serverOutputs` (template recalc),
  `nativeOutputs` + `nativeDebt` + `nativeStatement` + IRR convention
  (engine), and the quick-screen estimates computed client-side
  (`lib/quickScreenMath`, `lib/acquisitionQuickScreen`). The sidebar picks
  the highest tier available and never lets a lower one overwrite it.
- **active template / mapping profile** — for the Excel path.
- **modals / overlays** — goal-seek metric, OM wizard, critical-dates
  editor, command palette (Cmd/Ctrl+K), new-deal menu, history drawer.

### `lib/` — pure modules (every one has a `*.test.ts`)

Framework-free functions that vitest covers directly: `dealStages` (stage
registry, staleness thresholds, per-deal / bulk options), `staleness`,
`pipelineViews` (saved views, CSV), `dealPersistence`, `uiPrefs` (theme),
`quickScreenMath` / `acquisitionQuickScreen` (napkin math), `sensitivityMath`,
`cashflowStatement` (annual ⇄ monthly rollups), `leaseSlice`, `chartGeometry`,
`criticalDates`, `snapshotDiff`, `presetDiff`, `scenarioComparison`,
`benchmarkSubject`, `unitMixMerge`, `searchNav`, `useVirtualRows`. `api.ts`
is the typed fetch layer (one function per endpoint, `API_BASE = /api`);
`schemaFields`, `visibility`, `validateField`, `formatValue`,
`quickScreenFormat`, `mappingFormat` are schema/format helpers.

### `pages/` and `components/`

Pages are one-per-tab (`PipelinePage` with its two boards + untyped strip,
`QuickScreen`, `Documents`, `TemplateUpload`, `CashFlowTab`,
`SensitivityPanel`, `RiskPanel`, `ScenariosPanel`, `CompsPage`,
`PortfolioPage`, `SettingsPage`); Deal Inputs is the `DealInputForm`
component (schema-driven, `fields/` primitives: `ScalarInput`, `TableField`,
`KeyValueField`, `FieldRow`) with `GeneratePanel`, `PresetsPanel`,
`MarketContextPanel` + `DemographicsPanel`, `PropertyTaxLookup`,
`LeaseDrilldown`, `GoalSeekModal` alongside. Cross-cutting components:
`Layout`, `CommandPalette`, `ErrorBoundary`, `HistoryDrawer` +
`SnapshotDiffView`, `FileCabinet`, `CriticalDatesEditor`, `OmWizard`,
`ExtractionReview`, `AcquisitionQuickScreen`, `QuickScreenSensitivityGrid`.
`types/` mirrors the API payloads (`deal`, `scenario`, `schema`, `mapping`,
`template`, `document`, `extraction`, `sensitivity`, `marketContext`).

Dark mode is a `.dark` class on `<html>` (`index.css` overrides the slate
utilities actually used; `color-scheme: dark` flips native controls).

## Test tiers

| Tier | Where | What it pins | Regenerate |
|---|---|---|---|
| Unit | `backend/tests/test_*.py` (engine, services, parsers) | formulas against hand-derived analytic fixtures (`tests/fixtures/analytic_*.json`), parser behavior, migrations | — |
| API | same files, via the shared `client` fixture (`tests/conftest.py`: in-memory SQLite + migrations, `get_db` overridden; storage redirected to a temp dir before `app.config` loads) | routes, validation, contracts (e.g. stage registry, deal bundle) | — |
| Extraction goldens | `test_extraction_golden.py` + `tests/extraction_corpus/` | full structured result per synthetic document | `UPDATE_GOLDEN=1` |
| Parity (three-way) | `tests/parity/` (`harness.py`, `cases.py`, `export_case.py`, `run.py`) | injection layer always; native engine vs LibreOffice-recalculated template and vs the native Excel export under per-type tolerances | `python -m tests.parity.run [--require-libreoffice]` |
| Regression baseline | `tests/regression/test_run4_baseline.py` + `run4_baseline/*.json` | the full `/api/compute?detail=true` payload of six fixtures, floats to 1e-9, with every post-Run-4 input at its default | `UPDATE_BASELINE=1` — refused unless the diff is pure key addition (`expansion_violations`, `test_baseline_guard.py`) |
| vitest | `frontend/src/lib/*.test.ts` | the pure modules; `dealStages.test.ts` pins the registry literals the backend test also pins | — |
| e2e | `frontend/e2e/smoke.spec.ts` (Playwright, chromium) | one happy path through the real stack on a scratch DB (`CRE_DB_PATH`), ports 8123 / 5273 | — |

## Compatibility rules

1. **Defaults reproduce the previous run.** Every engine input added after a
   baseline was recorded must default to byte-identical outputs; the
   regression baseline is never loosened to fit a feature (the feature stops
   instead). Regeneration is expansion-only.
2. **One formula, one place.** Financial math lives only in
   `services/proforma/*`; the Excel export mirrors it as formulas and refuses
   shapes it cannot mirror; parity keeps the two honest.
3. **Stage registry in lockstep.** `input_schema.json → dealStages`,
   `schemas.py → DEAL_STAGES_BY_TYPE` (loaded from that file) and
   `dealStages.ts` must agree; `test_deal_stages.py::test_registry_shape`
   and `dealStages.test.ts` pin the literals. The `status` column accepts
   the union so type changes never invalidate a row.
4. **Schema-driven surfaces.** Adding an input means editing
   `input_schema.json` (form, mapping, presets whitelist, parity tolerances
   all follow); outputs are additive.
5. **Migrations are additive and idempotent.** Each `_migrate_*` step in
   `database.py` probes before patching and is safe on every startup and on
   a scratch engine (tests call `run_migrations(engine)` directly).
6. **Deal bundles are versioned.** `EXPORT_SCHEMA_VERSION` guards import;
   templates travel as named placeholders, never bytes.
7. **Provenance ladder.** server recalc > native engine > quick-screen
   estimate; the sidebar and memo footnote the source and conventions used.
8. **Nothing is auto-applied from documents.** Extraction produces
   proposals; only confirmed values reach a deal.
9. **Graceful degradation.** Missing LibreOffice / Tesseract / API keys turn
   features off with a reason, never a crash; parity *tests* skip without
   LibreOffice, but CI runs the parity CLI with `--require-libreoffice`.
