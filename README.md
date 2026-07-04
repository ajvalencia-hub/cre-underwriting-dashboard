# CRE Underwriting Dashboard

A commercial-real-estate underwriting workbench: screen a deal on a napkin,
extract documents into structured inputs, compute full return metrics with a
native pro-forma engine (or through your own Excel model), benchmark the
assumptions against public data, and render an IC memo.

**Stack:** React / TypeScript / Vite / Tailwind (`frontend/`), FastAPI /
SQLAlchemy / SQLite / openpyxl (`backend/`).

## Features

- **Deals** — every working session is a persistent deal (autosaved,
  switchable, multi-deal). Scenarios scope to the active deal. Deals
  export/import as versioned JSON bundles (scenarios and saved sensitivity
  runs included; templates travel as named placeholders).
- **0. Quick Screen** — back-of-napkin development feasibility: yield on
  cost vs exit cap with solve-for, an inline sensitivity grid, and a
  perm-takeout check sized by the full engine. Shareable via URL params.
- **1. Documents** — upload rent rolls / T-12s / OMs (xlsx, csv, pdf).
  Deterministic parsers with an LLM fallback (optional `ANTHROPIC_API_KEY`),
  OCR for scanned PDFs (optional Tesseract), classification, and a
  human-review gate: named cross-validation checks (pass/warn/fail) with
  failures requiring explicit acknowledgment — nothing is ever auto-applied.
- **2. Template & Mapping** — upload your firm's Excel model, map schema
  fields to cells/named ranges (sheet-scoped names and merged cells
  handled), generate populated workbooks, optionally recalculated
  server-side via LibreOffice.
- **3. Deal Inputs** — the schema-driven form. **Compute (native)** produces
  all 30 return metrics with the built-in pro-forma engine — no template
  required — including constraint-based debt sizing (LTV / DSCR / debt
  yield), the governing constraint, and a rate/NOI stress grid. Address
  benchmarks flag assumptions against Census ACS, HUD FMR, FHFA HPA, BLS
  employment, and FEMA flood zones, with per-input hover indicators.
- **4. Cash Flow** — the engine's period-level pro forma: annual table
  expandable to months, phase band, CSV export, plus a hold-period sweep
  (returns by exit year, modeled hold marked) and a refi-vs-sale-at-
  stabilization comparison.
- **5. Sensitivity** — native-engine sweeps by default (any two inputs, any
  output metric, up to 25×25), with the mapped-template path available as
  "Verify via Excel template". Runs can be saved onto a scenario.
- **6. Scenarios** — save/compare/load scenario snapshots per deal (no
  template required since the native engine): a comparison view shows only
  differing inputs plus outputs side-by-side with direction-aware
  best-value highlighting; a tornado chart ranks one-at-a-time driver
  perturbations by impact. **Generate IC Memo** renders a .docx — or PDF
  via LibreOffice — with executive summary, sources & uses, assumptions,
  returns, debt + stress, saved sensitivity, market flags, limitations, and
  embedded charts (S&U composition, annual levered cash flow, hold-sweep
  line, sensitivity heatmap).

**Engine conventions are explicit inputs**: waterfall style (`european`
whole-fund IRR-hurdle, or `american` deal-by-deal ledger), optional GP
catch-up %, IRR convention (`periodic_monthly` or date-based `xirr`,
Actual/365), development refi/takeout rate spread and costs. Defaults
reproduce the original behavior; the sidebar and memo footnote what was
used.

The summary sidebar shows a strict provenance ladder: **server-recalc >
native engine > quick-screen "est."** — a lower tier never overwrites a
higher one.

## API surface

| Area | Endpoints |
|---|---|
| Deals | `GET/POST /api/deals`, `GET/PUT/DELETE /api/deals/{id}`, `GET .../{id}/export`, `POST /api/deals/import` |
| Compute | `POST /api/compute[?detail=true]` (outputs + debt + period statement), `POST /api/compute/hold-sweep`, `POST /api/compute/tornado` |
| Templates & mapping | `/api/templates*`, `/api/mappings*` |
| Generate | `POST /api/generate` (xlsx download, X-Generation-* headers) |
| Sensitivity | `POST /api/sensitivity` (mode: native \| template) |
| Documents & extraction | `/api/documents*`, `/api/extraction*` (results carry a reviewable `unitMixProposal`) |
| Scenarios | `/api/scenarios*`, `PUT .../{id}/sensitivity`, `POST .../{id}/memo[?format=pdf]` |
| Market | `GET /api/market/rates` (FRED, 24h cache), `POST /api/market/benchmarks`, legacy `GET /api/market-context` |
| Schema | `GET /api/schema` |

## Development setup

```bash
# Backend (Python 3.12+)
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows; use bin/ on unix
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend
npm ci
npm run dev        # http://localhost:5173, proxies /api to :8000
```

Optional system tools — everything degrades gracefully without them:

- **LibreOffice** — server-side recalc of generated workbooks and the Excel
  parity harness. Without it, generated files still open correctly in Excel
  (`fullCalcOnLoad` is set) and parity tests skip with a reason.
- **Tesseract + Poppler** — OCR for scanned PDFs; otherwise scanned
  documents ask for manual classification.

Optional API keys (`backend/.env`, see `.env.example`): `ANTHROPIC_API_KEY`
(LLM extraction/classification fallback), `FRED_API_KEY` (index rates),
`CENSUS_API_KEY`, `HUD_API_TOKEN`, `BEA_API_KEY`, `BLS_API_KEY`
(benchmarks). Memo branding: `FIRM_NAME`, `MEMO_BRAND_COLOR`.

## Testing

```bash
cd backend
.venv/Scripts/python -m pytest tests -q          # full suite incl. parity + goldens
.venv/Scripts/python -m tests.parity.run         # native-vs-Excel divergence table
UPDATE_GOLDEN=1 pytest tests/test_extraction_golden.py   # regenerate goldens (prints diff otherwise)

cd frontend
npm test && npm run build && npm run lint
npm run e2e     # Playwright smoke: boots a scratch-DB backend + Vite, one happy path
```

The parity harness diffs the native engine against the openpyxl+LibreOffice
path over synthetic templates whose formulas mirror the engine exactly
(tolerances: currency ±$1, percent ±1bp, multiples ±0.001, IRR ±2bp). Drop
real firm templates into `backend/tests/parity/corpus/dropin/` (gitignored)
to check them ad hoc.

CI (`.github/workflows/ci.yml`) runs the full backend suite (with
LibreOffice + Tesseract installed), the parity CLI, and the frontend
build/lint/test gates on every push/PR.

## Project documentation

- `SUMMARY.md` — every financial formula in plain algebra, plus the decision
  and blocked logs from the autonomous build run.
- `DECISIONS.md` — financial-convention decisions with rejected alternatives.
- `FINDINGS.md` — the correctness audit (all items C/H/M/L resolved).
