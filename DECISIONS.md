# Decisions Log

Non-obvious choices made during the autonomous build runs, with the
alternatives rejected. Financial-convention decisions are marked **[FIN]**.

## G7 — Deal export/import (Run 2)

- **The bundle carries no documents or extraction results.** Documents and
  extraction results are global in the data model (not deal-scoped), so a
  deal bundle including them would either leak other deals' material or
  require a schema-level re-scoping out of proportion to the feature.
  Bundled instead: deal inputs (incl. quickScreen), every scenario with its
  outputs snapshot and saved sensitivity run, and NAMED template/mapping
  references. Rejected: bundling the template .xlsx (binary payloads in a
  JSON bundle, and templates are firm IP that shouldn't travel with every
  deal file by default).
- Import always creates a NEW deal (name suffixed "(imported)"), rewrites
  every id, clears template/mapping references to placeholders with
  explicit warnings, and validates exportKind + schemaVersion (=1) before
  touching the database.

## G6 — Hold sweep and refi-vs-sale (Run 2)

- **[FIN] The development perm takeout IS the stabilization refinance**, and
  it now prices explicitly: rate = construction rate + refiRateSpreadPct
  (default 0), costs = refiCostsPct × new loan (schema default 1%, the
  standard institutional refi cost load) deducted from equity cash flow at
  takeout. Sizing, the amortization schedule, DSCR metrics, and the stress
  grid all use the perm rate. Zero spread + zero costs reproduces Run-1
  numbers exactly (the parity corpus pins this). Rejected: a separate
  post-takeout second refi event (two refis inside one modeled hold is not
  the standard base case); a standalone permanent-rate input (a spread over
  the observable construction rate is how term sheets quote it).
- **[FIN] Hold sweep = whole exit years from stabilization+1** (year 1 for
  day-one-stabilized acquisitions) **through the modeled hold**, each row a
  full engine re-compute at that holdPeriodYears. The sale-at-stabilization
  leg of the refi-vs-sale fork computes with hold = stabilizationMonth/12
  (fractional years are legal — the timeline rounds to months). A deal that
  never stabilizes inside the hold returns warnings, never crashes.

## G1 — Waterfall styles and IRR conventions (Run 2)

- **[FIN] American waterfall = ledger + strict sequencing.** Pref accrues
  monthly on (unreturned capital + accrued unpaid pref) at (1+pref)^(1/12)-1
  — i.e. unpaid pref compounds monthly; capital contributions are pari
  passu. Distribution order per event: accrued pref (pro rata by accrued
  balances) → return of capital (pro rata by unreturned balances) → promote
  stack, where TIER 1's splits apply immediately (its schema hurdle is
  deemed satisfied by pref + full capital return — deal-by-deal promote
  crystallizes over the pref) and higher tier hurdles stay LP-IRR-measured.
  Rejected: annual pref compounding (mismatches the engine's monthly grid);
  simple (non-compounding) pref (less standard institutionally); measuring
  tier-1's hurdle by IRR in American too (then, with pari passu capital and
  a common pref rate, American and European are algebraically identical —
  the option would be a no-op).
- **[FIN] GP catch-up target counts the pref as profit.** The catch-up band
  (which replaces the pref→first-hurdle band) pays catchUpPct of each dollar
  to the GP until GP cumulative profit = promotePct × total cumulative
  profit, profits measured as nominal net positions (distributions −
  contributions). With 100% catch-up this lands the GP at exactly
  promotePct of ALL profit — the textbook outcome. Rejected: a target
  excluding the pref from the profit base (makes the target vacuously
  satisfied at zero and the band dead); time-valued profit bases (no
  standard reference convention).
- **[FIN] XIRR dates flows on a fixed calendar: closing = 2026-01-01,
  operating month m settles at the end of the calendar month at offset m-1**
  (month 12 = Dec 31 = exactly one year). Actual/365, Excel convention. The
  epoch is a documented deterministic default (the engine has no closing-
  date input); it affects results only through month-length/leap noise.
  Rejected: dating from today() (non-reproducible); adding an
  analysisStartDate input (a new date-typed field for bp-level noise isn't
  worth the form surface yet).
- Defaults preserve Run 1 exactly: waterfallStyle 'european', no catch-up,
  irrConvention 'periodic_monthly'; the parity templates pin these.

## F7 — IC memo

- **The memo route prefers a fresh engine compute of the scenario's inputs**
  (explicitly allowed by the spec), falling back to the scenario's stored
  outputs snapshot; 422 naming the missing fields when neither works. Saving
  a full scenario now snapshots the latest computed metrics + debt block
  into scenario.outputs ({"metrics", "debt", "sensitivity"} keys).
- **Sources & uses is produced by the ENGINE** (a new sourcesAndUses block on
  the compute result) so the memo service genuinely contains zero financial
  math — not even table totals.
- **The sensitivity-matrix section renders from scenario.outputs.sensitivity
  when present and is omitted otherwise.** No current flow persists a
  sensitivity run; the storage key is the documented hook for one. Rejected
  auto-running a sensitivity sweep at memo time (slow, and it would put
  numbers in the memo the user never reviewed).
- Memo generation is blocked for quickscreen scenarios (400) — napkin inputs
  aren't schema-shaped and can't honestly fill an IC memo.
- Branding: FIRM_NAME / MEMO_BRAND_COLOR env-configurable in config.py;
  formats $#,##0 / 0.00% / 0.00x from the schema output types.

## F6 — Market context by address

- **Data-source inventory (read before building):** geocode (Nominatim +
  Census coordinate lookup, keyless), FEMA NFHL (keyless), FHFA HPI metro CSV
  (keyless), BLS LAUS (keyless at low volume) are fully wired; Census ACS,
  HUD FMR, BEA, FRED require free keys and degrade to labeled
  "unavailable" results. Comps/pricing in the legacy panel remain the
  clearly-labeled deterministic placeholder (no free source exists).
- **[FIN] Rent percentile from two quantile anchors:** HUD defines FMR as the
  40th percentile of market rents and ACS gives the median (50th); a
  log-normal fit through those two points estimates the subject rent's
  percentile (warn >85th, caution >70th). With one anchor, a typical
  log-space spread (sigma = 0.35) is assumed. Rejected a linear
  interpolation — rents are right-skewed, and the log-normal keeps the
  estimate defined above the median.
- **Benchmarks run at county level** (tract is resolved and reported for
  provenance, but tract-level ACS rent is noisy/suppressed too often to
  benchmark against). **BLS employment trend uses the LAUS employment-level
  series YoY** — rejected QCEW average weekly wages: its series-id
  construction is fragile and adds nothing LAUS + BEA income don't cover.
- **Rent-growth benchmark = FHFA metro HPA** (caution when the assumption
  exceeds it by 200bps, warning at 400bps) — home-price appreciation is the
  best free metro-level price signal; no free market-rent-growth series
  exists.
- Geocode results and each source are cached on disk for 24h per key;
  "unavailable" results are never cached (retried next request). One failed
  source contributes a note, never blocks the panel. Flags are context only
  — nothing writes back into inputs.

## F5 — Extraction golden corpus + cross-validation rules

- **Cross-validation statuses:** pass / warn / fail with fail requiring an
  explicit acknowledgment checkbox before Apply — still never a hard block,
  preserving the human-review gate. Thresholds: GPR mismatch warns >10%,
  fails >25%; occupancy-vs-vacancy warns >5pts; expense ratio (30–55% of
  EGI) and cap-rate gap (>50bps) only ever warn ("flag, never block").
- **Rules that can't be evaluated emit nothing** rather than a "skipped"
  entry — the review screen only shows checks that actually ran.
- **Building the corpus surfaced three real parser bugs, fixed here:** a
  merged title banner fills through as N identical text cells and out-scored
  the real header row (header scoring now counts DISTINCT text values);
  Yardi's literal "VACANT" resident parsed as an occupied tenant; mid-table
  subtotal rows ("Total 1BR/1BA") became phantom units.
- **Goldens capture rounded (6dp) full parser output**, regenerated only via
  UPDATE_GOLDEN=1, with independent targeted assertions on the hostile
  details so a bad regeneration can't silently bless a regression.

## F4 — Excel parity harness

- **Synthetic templates constrain their deal shapes so formula mirroring is
  exact**: the acquisition case is full-term IO with flat growth (constant
  monthly vectors); the development case sets constructionMonths = 0 and
  zero origination fee (no capitalized interest) with DSCR/debt-yield
  sizing constraints zeroed so LTV provably governs. Rejected mirroring the
  S-curve/capitalized-interest machinery in spreadsheet formulas — a
  transcription of the engine into Excel wouldn't be an independent check,
  just the same code twice.
- **IRR parity annualizes LibreOffice's monthly IRR() as (1+i)^12 − 1 inside
  the template**, matching the engine's convention, tolerance ±2bp. Other
  tolerances: currency ±$1, percent ±1bp, multiples ±0.001.
- Drop-in corpus dir is gitignored (real firm templates stay local); the
  recalc diff skips with a reason when LibreOffice is absent, but the
  injection-layer assertions (cells, sheet-scoped names, merge anchors,
  fullCalcOnLoad) always run.

## F3 — Debt module

- **[FIN] DSCR sizing uses the amortizing loan constant even when the loan
  has an IO period** — the standard lender convention; the IO payment is
  only the sizing basis for a fully interest-only loan (amort = 0). Rejected
  sizing on the IO payment (overstates proceeds a lender would commit).
- **[FIN] Sizing-basis semantics:** `in_place` = the inPlaceNoi input
  (fallback: computed year-1 NOI); `stabilized` = the stabilizedNoi input
  (fallback: engine's computed stabilized NOI); `underwritten` = the
  engine's computed stabilized NOI regardless of inputs (the model's own
  underwriting). Development sizing values the asset at stabilized NOI /
  exit cap.
- **[FIN] An explicit loanAmount input overrides sizing** (user intent wins)
  with a warning when it exceeds sized proceeds. **ltvOrLtc = 0 means
  all-equity** — DSCR/debt-yield constraints are caps on proceeds, never a
  source of them.
- **[FIN] Development takeout: perm = constraint-sized amount; the delta vs
  the construction balance is a cash-out distribution (+) or an equity
  paydown (−, warned).** Replaces F2's par refi. Rejected capping at the
  construction balance — cash-out refis at stabilization are routine.
- **[FIN] Stress DSCR reprices the existing loan at the stressed rate on the
  amortizing constant** (the refi-risk question), with refi proceeds re-sized
  under stressed NOI and value (value scales with NOI at the same cap).
  The `stressedDscr` schema output is the worst cell (+200bps, NOI −10%).
- FRED series: SOFR, DGS5, DGS10, MORTGAGE30US; 24h on-disk cache under
  storage/cache; per-series failure isolation. Rates render as helper text
  next to the financing rate input — context only, never auto-filled.

## F2 — Native pro-forma engine

- **[FIN] Day count / periods: monthly, rate = annual/12 (30/360-style).**
  The standard for CRE amortization schedules. Rejected actual/365 accrual —
  it buys nothing at underwriting granularity and makes hand verification
  noisy.
- **[FIN] IRR annualization: periodic monthly IRR, annualized as
  (1+i)^12 − 1.** Rejected date-based XIRR for engine outputs: calendar month
  lengths add day-count noise that breaks exact hand verification. A separate
  `xirr()` (Excel actual/365 convention) exists for dated flows and is tested
  against Excel's documented reference example.
- **[FIN] Exit value = forward 12-month NOI ÷ exit cap** (institutional
  convention), less cost of sale. Rejected trailing NOI — it understates exit
  value for growing deals and isn't how sale comps are priced.
- **[FIN] Developer fee base = hard + soft + contingency (excludes land and
  financing).** Rejected % of TDC-including-fee (circular) and % of hard only
  (understates the market convention).
- **[FIN] Contingency base = hard + soft.** Matches the quick screen.
- **[FIN] Construction funding is equity-first**; loan draws begin when
  equity is exhausted. Interest accrues monthly on the drawn balance and is
  capitalized (interest-reserve convention), as is the origination fee. LTC
  applies to the budget ex-financing; financing costs are loan-funded on top.
  Rejected pro-rata equity/debt funding per draw — lenders require equity in
  first.
- **[FIN] Between construction end and permanent takeout, NOI is swept
  against the construction balance and interest keeps accruing; levered cash
  flow to equity is zero until takeout.** Rejected distributing lease-up NOI
  — construction lenders don't allow it.
- **[FIN] Permanent takeout (development) refinances the construction balance
  at par at stabilization.** Constraint-based sizing (LTV/DSCR/debt-yield)
  lands in F3 and will replace the par-refi amount.
- **[FIN] Waterfall: European (whole-fund), IRR-hurdle based.** LP and GP
  contribute pari passu; distributions fill bands — pro-rata to the pref,
  pro-rata to the first tier hurdle (promote starts at the first hurdle, the
  standard structure), then each tier's above-hurdle splits. Band fills use
  the closed form "amount that zeroes LP NPV at the hurdle rate". Rejected:
  American (deal-by-deal) waterfalls — no multi-deal context here; and a
  compounding pref ledger — the IRR-hurdle form is what the waterfallTiers
  schema (irrHurdle per tier) already implies.
- **[FIN] Growth: annual step-ups on operating anniversaries** — month m of
  operations gets (1+g)^((m−1)//12); the clock starts when operations start,
  not at close, so construction doesn't bank phantom rent growth. Rejected
  continuous monthly compounding (non-standard in underwriting).
- **[FIN] Replacement reserves are an above-the-line deduction (NOI is net of
  reserves)** — the lender underwriting convention, consistent with DSCR and
  debt-yield tests. Rejected below-the-line treatment.
- **[FIN] GPR source precedence: unit mix > per-SF rents > flat GPR input**,
  never summed. Ancillary income scales with occupancy during lease-up.
- **[FIN] NPV discounts monthly flows at (1+annual)^(1/12) − 1** (effective
  de-annualization, consistent with the IRR annualization), on the levered
  equity flows, at the new `discountRatePct` input (added to
  exit_assumptions, default 10%).
- **Development going-in cap rate = yield on cost** (no separate acquisition
  price exists), matching the quick screen's documented convention.

## F1 — Deal persistence

- **Deleting a deal cascades its scenarios.** Alternative rejected: orphaning
  them (deal_id = NULL) would silently re-attach them to the Default Deal on
  the next backfill run, resurrecting deleted work under the wrong deal.
  Cascade matches the existing template-deletion behavior.
- **URL quick-screen params override the stored deal only on first page load,
  then autosave syncs them into the deal.** Alternative rejected: applying the
  URL on every deal switch would clobber every deal a user flips through with
  the same shared-link values.
- **Deal.inputs is one JSON blob (form values + a `quickScreen` key) rather
  than normalized columns.** The input schema is data-driven and changes
  shape by property type; a blob keeps the autosave a single PUT and needs no
  migration per schema change. No schema field id can collide with the
  `quickScreen` key today; the hydration helper strips it defensively.
