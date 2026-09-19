# CRE Underwriting Dashboard

A commercial-real-estate underwriting workbench: screen a deal on a napkin,
extract documents into structured inputs, compute full return metrics with a
native pro-forma engine (or through your own Excel model), benchmark the
assumptions against public data, and render an IC memo.

**Stack:** React / TypeScript / Vite / Tailwind (`frontend/`), FastAPI /
SQLAlchemy / SQLite / openpyxl (`backend/`).

## Desktop app (macOS)

**CRE Underwriting.app** runs the whole dashboard as a normal Mac app. You
don't need a terminal or a browser tab.

### Before you start: two things to know

1. **The first launch needs one extra click.** The app isn't signed by Apple
   yet, so macOS blocks the first double-click.
   - **macOS 15 (Sequoia) and later:** double-click the app and choose
     **Done** on the warning. Open **System Settings → Privacy & Security**,
     scroll down to *"CRE Underwriting" was blocked…*, click **Open Anyway**,
     and confirm.
   - **macOS 14 and earlier:** right-click (or Control-click) the app,
     choose **Open**, then click **Open** again.

   From then on, a normal double-click works.
2. **Install LibreOffice (free) if you use your own Excel template.**
   [Download LibreOffice](https://www.libreoffice.org/download/download-libreoffice/),
   drag it to Applications, then restart CRE Underwriting. **It's the only
   way the app can recalculate your workbook and show *your template's*
   results.** It's also needed for template-verified sensitivity runs and
   for the IC memo as PDF. Without it:
   - generated workbooks are still correct when you open them in Excel,
     because Excel recalculates on open;
   - the built-in engine (Compute), the Excel model export, the .docx memo
     and the decks all work normally;
   - **Settings → External tools** shows whether LibreOffice was found.

   OCR for scanned, image-only PDFs likewise needs Tesseract and Poppler
   (`brew install tesseract poppler`). It's optional; text PDFs, Excel and
   CSV work without it.

### Install and run

Unzip `CRE-Underwriting-mac.zip` and drag **CRE Underwriting** into
Applications. Double-click it to start; quit it with ⌘Q or by closing the
window.

- **Your data** (deals, templates, documents, daily backups) is stored in
  `~/Library/Application Support/CRE Underwriting/`. Logs are in
  `~/Library/Logs/CRE Underwriting/`. Replacing the app with a newer build
  keeps your data.
- **Optional API keys** (FRED, Census, HUD, BEA, BLS, Anthropic): enter them
  in **Settings → Integrations**. They're stored in your macOS Keychain.
- **Files** open and save through the standard Mac dialogs.
- The app runs its own private server on a random local port that only its
  window can use. Quitting the app stops the server.

### Building the app

```bash
brew install node python@3.12
/opt/homebrew/bin/python3.12 -m venv desktop/.venv
desktop/.venv/bin/pip install -r backend/requirements.txt -r desktop/requirements.txt
desktop/build_mac.sh
```

This produces `desktop/dist/CRE Underwriting.app` and
`desktop/dist/CRE-Underwriting-mac.zip` (about 62 MB) for the architecture
you build on. The build runs `--self-test` inside the finished app before
zipping. The self-test checks compute, the Excel export, the decks, the
memo with charts, PDF reading and the Keychain, so a bad freeze fails the
build instead of reaching a colleague.

The shell's own tests (access gate, dialogs, PATH, quit cleanup) run with
`desktop/.venv/bin/python -m pytest desktop/tests -q`, and first in every build.

### Signing and notarizing

Unsigned, the zip opens on other Macs only via right-click → Open. To
distribute it properly you need an Apple Developer account ($99/year) and
a **Developer ID Application** certificate in your login keychain. Then,
once, store notarization credentials (an app-specific password from
appleid.apple.com):

```bash
xcrun notarytool store-credentials cre-notary --apple-id you@example.com --team-id TEAMID --password xxxx-xxxx-xxxx-xxxx
```

and build with:

```bash
SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" NOTARY_PROFILE=cre-notary desktop/build_mac.sh
```

`desktop/sign_mac.sh` signs every binary with the hardened runtime
(`desktop/entitlements.plist`), verifies the signature, reruns the
self-test on the signed app, then notarizes and staples. `SIGN_IDENTITY=-`
makes a local ad-hoc signature to test the hardened runtime without an
account (not distributable).

### Publishing an update

The app checks GitHub Releases for this repository at launch (at most once
a day; Settings → Updates turns it off or checks now) and offers a newer
version's download. It sends nothing but its version in the User-Agent and
never installs anything itself. To publish one:

1. Bump `VERSION` in `desktop/cre_desktop/version.py` (e.g. `1.1.0`).
2. Build (signed, ideally) with `desktop/build_mac.sh`.
3. Publish a release tagged with the same version and the zip attached:

```bash
gh release create v1.1.0 desktop/dist/CRE-Underwriting-mac.zip --title "CRE Underwriting 1.1.0" --notes "What changed"
```

Earlier versions then show a banner with Download, What's new and Not now.

To run the desktop shell from source without building, first run
`npm run build` in `frontend/`, then run
`desktop/.venv/bin/python desktop/launcher.py`.

The browser workflow below (uvicorn + `npm run dev`) is unchanged.

## Features

- **Deals (pipeline home)** — every working session is a persistent deal
  (autosaved, switchable, multi-deal). The Deals tab is a pipeline view:
  stage chips (screening → underwriting → LOI → under contract → closed |
  dead), inline status changes, staleness badges (amber 14d / red 30d
  untouched), and per-deal **Share** (self-contained read-only HTML) and
  **Deck** (one-page .pptx) exports. Scenarios scope to the active deal.
  Deals export/import as versioned JSON bundles (scenarios and saved
  sensitivity runs included; templates travel as named placeholders). Every
  input change is snapshotted (10-minute coalescing, 200/deal) with a
  history drawer and undoable restore.
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
  server-side via LibreOffice. A coverage table shows, for the active deal,
  each field's value, the resolved target cell, what that cell holds now,
  and whether Generate will write it — flagging blanks that leave the
  template's placeholder in place, formula cells, missing targets, two
  fields in one cell, and likely unit mismatches. Generate runs the same
  check first and reports what was written afterwards.
- **Results you can trust at a glance** — every result is stamped with the
  inputs it came from; editing any input marks it out of date (struck
  through, with Recompute / ⌘↩), and each value is tagged with its source
  ("engine" or "Excel"). Key metrics lead the summary.
- **3. Deal Inputs** — the schema-driven form. **Compute (native)** produces
  all 30+ return metrics with the built-in pro-forma engine — no template
  required — including constraint-based debt sizing (LTV / DSCR / debt
  yield), the governing constraint, a rate/NOI stress grid, and an
  insurance +25%/+50% stress when opex detail is on. Income models:
  multifamily unit mix, **commercial lease-level rent rolls** (escalations,
  NNN / base-year-stop / fixed recoveries, free rent, probability-weighted
  rollover with TI/LC below NOI, WALT and expiration schedule), or **both
  (mixed-use)** with component NOI splits, a component statement filter,
  and optional per-component exit caps. Opex can be a flat set of fields or
  per-line detail (basis: annual / per-unit / PSF / % of EGI, per-line
  growth, recoverable flags feeding the lease recoveries). A property-tax
  assessor lookup (Miami-Dade adapter) shows current vs reassessed-at-sale
  taxes with an opt-in reassessment model. **Assumption presets** capture/
  apply rate-and-term bundles through a preview diff. Address benchmarks
  flag assumptions against Census ACS, HUD FMR, FHFA HPA, BLS employment,
  FEMA flood zones — plus the comps database (rent and exit-cap flags) —
  with per-input hover indicators and an expandable demographics trend
  panel (population, income, employment, HPI charts).
- **7. Comps** — a workspace-level sale/rent comps database with market
  filtering, inline add, and a two-step Yardi-Matrix-aware CSV importer
  (header auto-mapping, sample preview, per-row skip warnings). Comps feed
  the benchmark flags once ≥3 exist in the deal's market.
- **Export Excel model** — a formula-live workbook generated straight from
  the deal (no template): growth chains, NOI build, amortization schedule,
  IRR/multiple formulas. Unsupported shapes refuse with a blocker list
  rather than exporting wrong formulas; parity with the engine is enforced
  three-way in CI.
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

**Run-4 engine refinements — every one defaults to exact Run-3 behavior**
(pinned by a byte-level regression baseline in `tests/regression/`):
`adminFeePct` (CAM admin markup on NNN/base-year recoveries, default 0),
`mgmtFeeRecoverable` + `mgmtRecoveryCapPct` (management fee joins the
recovery pool on pre-recovery EGI, default off), `renewalRentPsfDiscountPct`
(renewal rent × market, default 1.0), `reletCapitalAtCommencement` (split
TI/LC timing, default off = single entry at expiry+1), `grossUpToPct`
(base-year occupancy gross-up, default off; needs opex detail + its
`variableWithOccupancy` column), `opexAllocationBasis` (mixed-use split:
`revenue_share_y1` default | `sf` | `revenue_share_annual`),
`nonAdValoremTaxes` + growth + recoverable flag (separate line, never reset
by reassessment, default 0). Comp benchmark flags now normalize (unit-type
weighted → $/SF → pooled tiers); the per-lease drill-down, history diff/
restore preview, pipeline bulk actions + saved views + CSV, comps dedupe/
staleness/map, batch screening decks, and the widened Excel export
(developments + opex detail, still three-way parity-gated) ride on top.

**Run-5 additions — every engine input defaults to exact Run-4 behavior**
(pinned by the same byte-level regression baseline, now including a
value-add multifamily fixture):

- **Value-add inputs.** A **renovation program** (per-unit-type cohort
  sequencing: cost, rent premium, downtime, pace, start month; funded by
  equity-at-close or operating cash) and **loss-to-lease burn-off** (per-unit
  turnover blend toward market at capture rate). Both are display/​behavior
  layers over scheduled rent; absent inputs leave the engine byte-identical.
- **Capital stack.** **GP fee economics** (acquisition / developer / asset-
  management fees + promote split-out), a **mezzanine / preferred-equity
  tranche** (fixed or fill-to-LTC sizing, current or accrued/PIK pay, ranked
  after senior and before equity, combined-leverage outputs), **floating-rate
  senior debt** (SOFR forward curve as a step function, floor, rate cap with
  strike-DSCR stress and premium; seed the index from FRED), and
  **replacement reserves + tax/insurance escrows** (below-NOI or
  above-NOI-underwritten convention; escrows as pure close/exit cash timing).
- **Analytics tools.** **Goal-seek** (solve any numeric input for a target
  metric; bracket-scan + bisection, no monotonicity assumption), **Monte
  Carlo** (≤6 correlated drivers via a Gaussian copula, seeded/reproducible,
  P5–P95 + tail probabilities, histogram, saved to a scenario and into the
  memo's risk section), and **per-year operating break-evens** (occupancy and
  rent level at zero levered cash flow, analytic).
- **Workflow.** An **OM-to-deal wizard** (upload → confirm types → extract →
  the existing review gate → a new deal with provenance rows; resumable
  draft), **critical dates** (deadline strip + header chips + share),
  a **build-to-sell model** for single-family and townhome developments
  (site work, per-home construction, closings at the absorption pace, a
  revolving loan repaid from closings; margin, peak equity, sellout), a
  **hotel operating model** (keys × ADR × occupancy, F&B and other
  revenue, departmental / undistributed / franchise / management / FF&E
  costs, GOP and NOI after FF&E), an **investment-committee sign-off** (submit with the computed version,
  approvals by name, reasons to reject / return / reopen, locked inputs while
  under review), a **file cabinet + notes** timeline per deal, a **command palette** (Cmd+K:
  run Compute and other actions, jump to any tab or Deal Inputs field, and
  search deals / tenants / comps / notes), a **full 8-slide IC deck**, a
  **portfolio roll-up** (equity-weighted blended returns, exposure and
  concentration, CSV), and **Docker packaging with automated SQLite backups**
  (see the Docker quickstart below).

The summary sidebar shows a strict provenance ladder: **server-recalc >
native engine > quick-screen "est."** — a lower tier never overwrites a
higher one.

### Added by the Run 6 port

- **Compare tab (Portfolio group):** pick 2–4 deals (archived ones are excluded) and see their outputs side by side.
  - Each deal is computed from its saved inputs, and recomputed automatically after it's edited.
  - Rows are filtered by dealflow: "n/a" means the metric doesn't apply to that deal type. Untyped or incomplete deals show "not computable" with the reason.
  - The best value is highlighted where "better" is unambiguous.
  - Export CSV works in the browser and uses the native Save dialog in the desktop app. The selection is remembered.
- **Underwriting Agent tab (This deal group) + floating Agent dock:** chat about the open deal with a provider picker, one-click plays ("Screen this deal", …) and a list of tool calls per answer.
  - Figures that no tool call backs up are flagged "Unverified".
  - The agent only *proposes* input changes. Each proposal is a card with a before/after diff and an engine preview, plus Approve & apply or Reject.
  - Approving respects the IC lock (it's disabled, with the reason, while locked), saves pending edits first, records a history entry ("Agent-applied") and marks the fields as agent-filled.
  - The dock stays open across tabs and closes with Escape. It shares the conversation with the tab.
- **Tags:** add or remove tags from the deal header's chip row.
  - The pipeline shows tag chips per deal and has an AND tag filter.
  - Bulk "Add tag" / "Remove tag" work on the selection. Tags also appear in the pipeline CSV.
- **Archive / duplicate:** "More ▾ → Duplicate… / Archive" in the deal header.
  - Archived deals leave the working list.
  - The pipeline's "Show archived" lists them dimmed, each with Unarchive.
- **Pipeline sort and filter:** every column header is sortable (Deal, Market, Stage, Last touched, Staleness and the metric columns such as IRR, equity and yield), with ascending/descending shown by `aria-sort`.
  - Filters by stage, staleness (fresh / stale / critical) and tag.
  - Saved views capture the sort, direction, filters and visible columns; older saved views load unchanged.
- **Settings:**
  - Each backup snapshot now has a **Download** of its database file.
  - **Workflow:** default type for New Deal (ask / acquisition / development).
  - **Security:** Sign out, shown only when the server requires an access token (`CRE_API_TOKEN`, browser/Docker mode; never in the desktop app).
- **Token prompt:** when the server sets `CRE_API_TOKEN`, the browser app asks for the token before loading (and again after a 401 or Sign out). The desktop app never shows it, because its launcher already protects the API.
- **Tests:** `npm run e2e` now also runs `e2e/agent.spec.ts` (scripted, network-free agent provider) and `e2e/features.spec.ts`. Spec files run serially (`workers: 1`) against one scratch database and a scratch storage root.

## Underwriting Agent

The Underwriting Agent is a chat assistant for the active deal. It has
two entry points, the **Agent** tab (under *This deal* in the left rail)
and the floating **Agent** dock at the bottom right. The dock stays open
across tabs, and Escape closes it. Both show the same conversation, with
one thread per deal.

### What it can do

It answers questions about the deal by calling the dashboard's own tools,
never from memory:

| Tool | Kind | What it does |
| --- | --- | --- |
| `get_deal`, `list_scenarios`, `get_scenario` | read | Reads the current deal's inputs, status and saved scenarios. Always scoped to the active deal. |
| `compute` | read | Runs the built-in pro-forma engine on a full input map. |
| `solve` | read | Goal-seek: finds the value of one numeric input that hits a target output metric. It uses the same solver as the sidebar's Goal Seek. `values` defaults to the deal's inputs. |
| `run_tornado`, `run_sensitivity` | read | Perturbation (tornado) and grid sensitivity. |
| `get_market_context`, `list_comps`, `get_schema` | read | Market data, saved comps, and the field registry. |
| `propose_input_changes`, `propose_scenario` | **write (proposal only)** | Produces a proposal to review, with a computed preview. The agent never applies it. |

Inputs are checked the same way everywhere. If a value fails the engine's
input validation, for example text in a numeric field, the tool returns an
error naming the field instead of a result. The agent sees that error and
can correct the value.

The suggestion chips run canned workflows with a restricted set of tools:

- "Screen this deal"
- "What's driving the levered IRR?"
- "Stress-test this deal"
- "What exit cap gets me to a 15% IRR?"

### Proposals: approve or reject

When the agent recommends a change, it creates a *proposal card* showing a
before/after diff and preview metrics. It doesn't edit anything itself.

**Approve & apply** merges the change into the deal on the server and
records it in *Input history* as **Agent-applied**, restorable like any
other snapshot. Every other pending proposal on that deal is then marked
*stale*, because its preview no longer matches the inputs. The same rules
apply as to any other edit:

- **IC lock:** while the deal is submitted to, approved or rejected by the
  investment committee, approval is refused and nothing is written. The
  proposal stays pending. Reopen the deal on the IC Approval tab first.
- **Validation:** a value that fails the engine's input validation is
  refused with the field named.

**Reject** takes an optional note, which is added to the thread.

### Grounding guarantee

After every turn, the server cross-checks each number in the reply against
the numbers returned by that turn's tool calls. That covers dollar
amounts, percentages, multiples and figures like "DSCR is 1.4". Any number
that doesn't trace back to a tool result appears under an amber
**Unverified** banner. It is flagged, not hidden. Each reply also lists its
tool calls; expand *N tool call(s)* to see them.

### Providers and configuration

Set these in `backend/.env` (see `.env.example`). In the desktop app, paste the
keys into the OpenAI and Anthropic rows under **Settings → Integrations**.
They're stored in the Keychain and take effect after a restart.

| Variable | Default | Purpose |
| --- | --- | --- |
| `AGENT_PROVIDER` | `anthropic` | Provider for a new thread: `anthropic` or `openai`. |
| `ANTHROPIC_API_KEY` | — | Shared with document classification and extraction. |
| `ANTHROPIC_AGENT_MODEL` | `claude-sonnet-5` | Model for the Anthropic provider. |
| `OPENAI_API_KEY` | — | Used only by the agent. |
| `OPENAI_AGENT_MODEL` | `gpt-5.1` | Model for the OpenAI provider. |

Both providers are billed API usage. Without a key, the provider reports
itself as *unavailable* in the chat; nothing else in the app is affected.

You can switch the provider per thread from the picker at the top of the
chat. The change applies to the next message, with no restart. The picker
greys out a provider whose key isn't configured.

### Cost and tokens

The Agent tab header shows the thread's cumulative token count. Hover over
it for the input/output split and the provider. The same totals are logged
for each turn under the `app.agent` logger, along with tool calls,
proposals and unverified claims.

### Limits

Each turn is capped at 25 tool calls, 15 compute-family calls and 60
seconds. A turn that hits a cap ends with an explicit "Stopped early" note.

### Limitations

- Replies aren't streamed. A reply appears when the whole turn finishes.
- Threads are single-user and per deal. There's no way to reset or delete
  a thread in the UI yet.
- The agent only sees what its tools return. It doesn't read uploaded
  documents directly; use the Documents extraction flow for those.
- The grounding check is numeric. It can't verify qualitative claims.
- Scenario proposals (`propose_scenario`) can be reviewed and approved like
  input changes. However, approving one applies the changes to the deal's
  inputs; it doesn't save a separate named scenario.
- Switching providers only affects future turns. The history is kept as
  it was.

### Testing without a model

The Playwright suite runs the backend with `AGENT_PROVIDER=scripted`. This
deterministic stub exercises the real tool loop, proposal approval and the
unverified-claim check without network access. It isn't selectable in the
UI. The backend tests (`backend/tests/test_agent_*.py`) mock the provider
at the runner boundary.

## API surface

| Area | Endpoints |
|---|---|
| Deals | `GET /api/deals[?includeArchived=true&tag=<t>&fields=summary]` (archived hidden by default; `fields=summary` = slim rows with a `summary` block, no inputs), `POST /api/deals`, `GET/PUT/DELETE /api/deals/{id}` (incl. `status`, `tags`; every single-deal response carries `ETag`; PUT honors optional `If-Match` -> 412 `{detail, current}`), `POST .../{id}/archive`, `POST .../{id}/unarchive`, `POST .../{id}/clone` (optional `{name}`), `POST /api/deals/bulk-tags` (`{dealIds, add, remove}`), `GET .../{id}/export` (bundle carries `deal.tags`; schemaVersion stays 1), `POST /api/deals/import`, `GET .../{id}/share.html`, `GET .../{id}/deck.pptx`, `GET .../{id}/ic-deck.pptx[?scenario_id=]` (scenario must belong to the deal), `GET .../{id}/history`, `POST .../{id}/history/{snapshotId}/restore` |
| Compute | `POST /api/compute[?detail=true]` (outputs + debt + period statement; LRU-cached; `irrDiagnostics` when the multi-root IRR warning fires), `POST /api/compute/hold-sweep`, `POST /api/compute/tornado`, `POST /api/compute/monte-carlo` (bounded pool: 429 + `Retry-After` when saturated; seed 0..2^32-1), `GET/DELETE /api/compute/monte-carlo/{jobId}` (poll / cancel -> `cancelling`, then `cancelled`) |
| Templates & mapping | `/api/templates*`, `/api/mappings*` |
| Generate | `POST /api/generate` (xlsx download, X-Generation-* headers), `POST /api/generate/model` (formula-live native Excel model) |
| Sensitivity | `POST /api/sensitivity` (mode: native \| template) |
| Documents & extraction | `/api/documents*` (upload: .pdf, .xlsx, .csv; legacy .xls refused with guidance), `/api/extraction*` (results carry reviewable `unitMixProposal` / `commercialLeaseProposal`) |
| Scenarios | `/api/scenarios*`, `PUT .../{id}/sensitivity`, `POST .../{id}/memo[?format=pdf]` |
| Market | `GET /api/market/rates` (FRED, 24h cache), `POST /api/market/benchmarks` (public sources + comps DB), `GET /api/demographics`, legacy `GET /api/market-context` — all rate-limited per route (`CRE_EXTERNAL_RATE_LIMIT_PER_MIN`, default 60, 0 = off; 429 + `Retry-After`) |
| Comps | `GET/POST /api/comps/{sale\|rent}[?market=]` (literal, two-way market match), `PUT/DELETE .../{id}`, `POST /api/comps/import` (preview without mapping; insert with), `POST /api/comps/import/file` (5 MB, chunked), `GET /api/comps/{kind}/map` (rate-limited) |
| Property tax | `POST /api/property-tax/lookup`, `GET /api/property-tax/counties` |
| Presets | `GET/POST /api/presets`, `PUT/DELETE .../{id}`, `GET /api/presets/fields` |
| File cabinet | `GET/POST /api/deals/{id}/attachments`, `GET .../attachments/{docId}/download[?inline=true]` (images/PDF only inline, sandbox CSP; SVG always a download), `GET .../attachments/{docId}/preview`, `DELETE .../attachments/{docId}` (the deal's own attachments only), `/api/deals/{id}/notes*` |
| Admin | `GET /api/admin/integrations` (flags only, incl. `OPENAI_API_KEY`), `GET /api/admin/tools`, `GET /api/admin/backups`, `POST /api/admin/backups/run`, `POST /api/admin/backups/restore`, `GET /api/admin/backups/{kind}/{name}/download` (SQLite snapshot; any kind) |
| Search | `GET /api/search?q=` (facets `acq:` / `dev:` / `tag:<t>`, composable; archived deals excluded) |
| Underwriting Agent | `GET /api/agent/threads/{dealId}`, `POST /api/agent/threads/{dealId}/messages` (one full turn; `content` or `playId`), `PUT /api/agent/threads/{dealId}/provider`, `GET /api/agent/plays`, `GET /api/agent/providers`, `POST /api/agent/proposals/{id}/approve` (input validation 422, IC lock 409), `POST /api/agent/proposals/{id}/reject` |
| Auth (optional) | `GET /api/auth/status`, `POST /api/auth/login` (sets the HttpOnly session cookie), `POST /api/auth/logout` — active only when `CRE_API_TOKEN` is set |
| Ops | `GET /api/health`, `POST /api/client-errors` (error-boundary sink); every response carries `X-Request-ID` |
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

## Docker quickstart

One command builds the SPA, bakes in LibreOffice + Tesseract + Poppler, and
serves the whole app (UI + API) on `http://localhost:8000`:

```bash
docker compose up --build
```

The port is published on **this machine only** (`127.0.0.1:8000`): the app
has no login, so anyone who can reach it can read and change every deal. To
share it on a trusted network deliberately, change the `ports` entry in
`docker-compose.yml` to `"8000:8000"`.

The SQLite database, uploads, and rotating backups live on the named volume
`cre-data` (mounted at `/data` in the container), so they survive rebuilds.
Set optional API keys in a `.env` beside `docker-compose.yml` (compose reads
`FRED_API_KEY`, `CENSUS_API_KEY`, `ANTHROPIC_API_KEY`, `FIRM_NAME`, etc.).

Environment variables of note:

- `CRE_STORAGE_ROOT` — where the DB, uploads, and backups live (the image
  sets `/data`; local dev defaults to `backend/storage`).
- `CRE_FRONTEND_DIST` — directory of the built SPA the backend serves (set in
  the image; unset in dev, where Vite serves the frontend).
- `CRE_ENABLE_BACKUP_SCHEDULER=1` — turns on the in-process daily backup loop
  (on in the image; off in dev/tests).

### Backups & restore

- **Automatic:** a daily SQLite snapshot (online-backup API, safe during
  writes) under `/data/backups/daily/`, promoted to a weekly snapshot on the
  first run of each ISO week. It skips a run when the newest daily snapshot
  is under 20 hours old (the desktop app backs up at launch). Rotation keeps
  **one snapshot per day for 7 days**, **4 weekly**, and the last **5
  "before restore"** snapshots. A failed automatic backup is logged and
  shown in Settings. Each snapshot is a timestamped directory with `app.sqlite3` plus a
  `manifest.json` listing uploads by name/hash (upload bytes are **not**
  copied — they already share the data volume; the manifest lets you confirm
  none went missing after a restore).
- **On demand:** `POST /api/admin/backups/run`; list with
  `GET /api/admin/backups`.
- **Restore:** `POST /api/admin/backups/restore` with `{"kind","name"}`
  first snapshots the live DB as `pre_restore` (returned as
  `preRestoreSnapshot`, so a wrong restore can be undone), then overwrites
  the live DB from that snapshot. **Restart the backend** afterwards so
  SQLAlchemy reopens the file. The response returns the uploads manifest so
  you can verify every referenced file is still present on the volume. (To
  restore into a fresh volume, copy the snapshot dir into `/data/backups/…`
  first, then call restore.)

## API types

The frontend's API types are generated from the backend's OpenAPI schema
into `frontend/src/types/api.gen.ts` (dev dependency `openapi-typescript`).
After changing what a route returns, regenerate and commit the file:

```bash
cd frontend && npm run gen:api
```

`frontend/src/types/apiContract.ts` checks at compile time that each
declared response fits the frontend type that reads it, so drift on either
side fails `tsc`. CI regenerates the file and fails if the committed copy
is stale. Response models for routes that build plain dicts live in
`backend/app/api_models.py`; they keep undeclared keys, so declaring a
model never drops a field from a response.

## Testing

```bash
cd backend
.venv/Scripts/python -m pytest tests -q          # full suite incl. parity + goldens
.venv/Scripts/python -m tests.parity.run         # native-vs-Excel divergence table
UPDATE_GOLDEN=1 pytest tests/test_extraction_golden.py   # regenerate goldens (prints diff otherwise)
UPDATE_BASELINE=1 pytest tests/regression        # Run-3 payload baseline (EXPANSION only, never to absorb behavior changes)

# Lint and type checks (dev tools: pip install -r requirements-dev.txt)
.venv/Scripts/ruff check app tests                # config in backend/pyproject.toml
.venv/Scripts/mypy                                # modules on the ratchet list are skipped until cleaned

cd frontend
npm test && npm run build && npm run lint
npm run e2e     # Playwright smoke: boots a scratch-DB backend + Vite, one happy path
```

The parity harness is now **three-way**: it diffs the native engine against
(a) the openpyxl+LibreOffice template path over synthetic templates whose
formulas mirror the engine exactly, and (b) the native formula-live Excel
model export, recalculated by LibreOffice (tolerances: currency ±$1,
percent ±1bp, multiples ±0.001, IRR ±2bp). Drop real firm templates into
`backend/tests/parity/corpus/dropin/` (gitignored) to check them ad hoc.

CI (`.github/workflows/ci.yml`) runs the full backend suite (with
LibreOffice + Tesseract installed), the parity CLI, ruff and mypy, the
frontend build/lint/test gates, the API-types check, a Playwright e2e job,
and a Docker job (`docker compose config` + image build) on every push/PR.
Pull requests and main also build the desktop `.app` on macOS, run its
self-test, and keep the zip as a build artifact for a week.

## Run 5 defaults-compatibility statement

Every engine input added in Run 5 (J1–J6: renovation program, loss-to-lease,
GP/AM fees, junior tranche, floating-rate debt, reserves + escrows) defaults
to reproducing Run-4 outputs **byte-for-byte** (1e-9), enforced by the
`backend/tests/regression/` baseline across six fixtures. Turn a feature on
only by supplying its inputs; leave them at defaults and the pro forma is
identical to before. See `SUMMARY5.md` for the per-feature before/after
algebra and the complete Excel-export refusal list.

## Project documentation

- `SUMMARY.md` / `SUMMARY2.md` / `SUMMARY3.md` / `SUMMARY4.md` /
  `SUMMARY5.md` — every financial formula in plain algebra per build run,
  plus decision/blocked deltas and manual QA checklists (SUMMARY5 shows
  BEFORE/AFTER algebra for the Run-5 value-add + capital-stack features and
  the complete Excel-export refusal list).
- `DECISIONS.md` — financial-convention decisions with rejected alternatives.
- [`ARCHITECTURE.md`](ARCHITECTURE.md) — module map, engine block order, test tiers and compatibility rules.
- `FINDINGS.md` — the correctness audit (all items C/H/M/L resolved).
