# Decisions Log

Non-obvious choices made during the autonomous build runs, with the
alternatives rejected. Financial-convention decisions are marked **[FIN]**.

## H13 — Hardening pass (Run 3)

- **Request ids**: middleware assigns (or honors) X-Request-ID, logs
  method/path/status/duration per request, and echoes the id on the
  response; the React error boundary posts crashes to /api/client-errors
  (bounded fields) so frontend and backend failures share one log stream.
- **LRU compute cache** (128 entries) fronts POST /api/compute only — the
  engine is pure, keys are canonical sorted JSON (dict ordering never
  splits the cache), and HITS RETURN DEEP COPIES because downstream
  consumers mutate results; a poisoned cache would be a correctness bug.
  Rejected: caching inside engine.compute itself (sensitivity/tornado
  sweeps intentionally compute thousands of distinct inputs and would
  churn the cache for zero hits).
- **Virtualization without a dependency**: a ~40-line window hook
  (pure math unit-tested) applied to the comps table, active only above
  150 rows — windowing short lists adds scroll jank for nothing.
- Responsive/a11y: tab bar becomes a scrollable <nav> with aria-current;
  wide tables scroll inside their cards at 768px; destructive icon-ish
  buttons carry aria-labels.
- Smoke extended with a second journey: pipeline status change, HTML
  share fetch, comps inline add, presets bar, history drawer.

## H12 — One-page deck export (Run 3)

- One 16:9 slide, deliberately: title bar, six metric tiles, an
  assumptions column, and the memo's OWN matplotlib charts (annual
  levered cash flow, sources & uses) — no new chart code, no new numbers.
  Zero financial math in the renderer (memo/share rule); every value is a
  formatted pass-through from a fresh engine compute.
- An incomputable deal 422s with the missing-input list (unlike the HTML
  share, which renders an error page — a broken link is fine in a browser
  but a corrupt .pptx download is not).

## H11 — Native Excel model export (Run 3)

- **Refuse rather than degrade**: deal shapes whose math can't be mirrored
  formula-for-formula (development draws, lease-level rolls, opex detail
  lines, waterfall tiers, XIRR, reassessed taxes) 422 with the full blocker
  list. Rejected: exporting those as static values inside a formula
  workbook — a file that LOOKS live but silently isn't is worse than no
  file.
- **[FIN] Two deliberate value-not-formula cells**, both flagged on the
  Notes sheet: the loan amount (the engine's min-of-LTV/DSCR/debt-yield
  sizing, written as the sized value) and annual GPR/other income (unit-mix
  and per-SF sections collapse to the same annual dollars the engine
  uses). Everything downstream — growth clocks, vacancy/credit stack,
  SUMPRODUCT expense growth, IO→amortizing schedule with the engine's
  exact PMT/ROUND convention, forward-12 exit cap, (1+IRR)^12-1
  annualization, SUMIF equity multiple — is live formulas.
- **Three-way parity is a permanent harness case**: python -m
  tests.parity.run now also exports two native workbooks
  (analytic_acquisition = hand-algebra fixture; amortizing_growth =
  growth + credit loss + IO→amort + app-sized loan) and diffs the
  LibreOffice-recalced cells against the engine under the same
  tolerances as the template corpus. Zero deltas at introduction.

## H10 — Read-only HTML share (Run 3)

- **The share page is computed fresh from the deal's saved inputs at
  request time** — always current, no stale snapshot files to manage.
  Zero financial math in the renderer (same rule as the memo): key
  metrics pass through the engine outputs with schema formatting; the
  annual cash-flow table sums the engine's own monthly vectors (close
  month excluded — capital event, not an operating period).
- **Self-contained by construction**: inline CSS only, no scripts, no
  external URLs of any kind (tested), so the file can be emailed or
  dropped in a data room. Deal name and every value are HTML-escaped;
  the download filename is sanitized.
- An incomputable deal renders a readable error page (200), never a
  stack trace — a share link must not 500 in front of a counterparty.
  No auth/token: the endpoint shares whatever the local instance holds,
  matching the app's single-user posture.

## H9 — Input change history (Run 3)

- **A snapshot is the deal's inputs AFTER a save** — a restorable
  checkpoint, not a diff log. changedPaths (top-level field ids, dotted
  one level into dict values so quickScreen.rent reads naturally) exist
  for display only; restore replays the full stored inputs.
- **The first edit writes a BASELINE snapshot of the pre-edit state**, so
  "before I touched anything" is always restorable. No-op saves record
  nothing.
- **Coalescing: autosaves merge into the newest snapshot while it is
  younger than 10 minutes**, anchored on created_at (continuous editing
  still checkpoints every 10 min, rather than one ever-sliding blob).
  changedPaths accumulate as the union of per-save diffs — an A→B→A edit
  inside one window still lists the field (acceptable noise). Restores
  never coalesce.
- Retention 200/deal, oldest dropped — including eventually the baseline
  (it's history, not a pin). Snapshots cascade-delete with the deal.
- **Restore records itself as a snapshot first**, so any restore can be
  undone from the same drawer. The UI gates restore behind an explicit
  confirm click.

## H8 — Assumption presets (Run 3)

- **Presets carry RATE/TERM assumptions only** — a server-side whitelist
  (PRESET_FIELD_IDS, served at /api/presets/fields so client and server
  can't drift) drops anything else at create/update time. Deal-specific
  dollars (purchase price, GPR, taxes) and property facts (unit mix,
  leases) are excluded by design so presets stay portable across deals.
- **Apply is user-confirmed, row-by-row**: preview diff (current vs preset,
  unchanged rows greyed and unselectable), checkboxes defaulting to the
  changed rows, one explicit Apply click. Number equality tolerates float
  noise (1e-12) so re-applying a preset shows "nothing to apply".
- Seeds (Conservative / Base Case / Aggressive Growth) insert only when
  the table is EMPTY, so user edits and deletions stick within a session;
  deleting every preset lets the next startup reseed. Editing a seed
  flips its source to "user". Seed numbers are generic screening
  defaults, labeled as such — not market data.

## H7 — Pipeline view (Run 3)

- Pipeline stages: screening → underwriting → loi → under_contract →
  closed | dead (the standard acquisition funnel). Existing deals migrate
  to "screening" via the check-and-migrate pattern; status rides the same
  partial-update PUT as autosave, so a status change never clobbers inputs
  and vice versa.
- **Staleness = days since the deal was last touched** (updated_at, which
  autosave already maintains): amber at 14 days, red at 30. Terminal
  stages (closed/dead) are never flagged — those deals are supposed to sit
  still — and they're hidden from the pipeline by default behind a toggle.
- The Deals tab is a table sorted by stage then recency (not a kanban —
  drag-and-drop adds a dependency for a 6-value select). Opening a deal
  flushes the autosaver, switches the active deal, and jumps to Deal
  Inputs.

## H6 — Demographics panel (Run 3)

- Trends come from the SAME four sources the benchmarks already use (ACS,
  BLS LAUS, FHFA HPI, BEA CAINC1) — no new keys, no new vendors; series
  variants added beside the existing point lookups. Series convention:
  `[{period, value}]` ascending; rates as fractions; BLS M13 annual-average
  rows dropped; a failed ACS vintage skips silently (>= 2 points required).
- **Charts load lazily** — the panel fires four upstream APIs only when the
  user expands it, not on every form keystroke. Same 24h source cache and
  graceful-unavailable contract as benchmarks. Context only: nothing ever
  writes to inputs.
- Charts are dependency-free inline SVG; the path/bar geometry lives in a
  pure lib (chartGeometry.ts) so scaling and degenerate cases (flat series,
  single point, empty) are unit-tested.

## H5 — Comps database (Run 3)

- **Comps are global, not deal-scoped** — a sale comp is evidence about a
  market, not about one deal; deals see them through the market filter.
  Rejected: per-deal comp lists (forces re-entering the same comps on every
  deal in a market).
- **CSV import is two-phase with a human gate** (same philosophy as the
  extraction review): no mapping submitted → preview only (detected
  columns, suggested Yardi-Matrix-style header mapping, sample rows),
  nothing written; rows insert only when the user submits a mapping.
  Unparseable rows are skipped with a warning, never guessed.
- Import coercion: $/commas stripped; cap rate and occupancy values > 1 are
  treated as percents and divided by 100; dates normalized to ISO from
  mm/dd/yyyy, yyyy-mm-dd, or mm/yyyy. A sale row needs a name plus price or
  cap rate; a rent row needs a name plus rent.
- **[FIN] Comps benchmark flags need >= 3 comps in the deal's market** —
  two comps are an anecdote, not a benchmark. Thresholds: subject rent
  above the rent-comps median by >10% caution / >20% warning; exit cap
  BELOW the sale-comps median (assumed compression) by >50bps caution /
  >100bps warning. Exit cap above the comps median is conservative and
  never flagged. Property type filters softly (untyped comps always
  count). Flags ride the existing benchmarks panel; context only, never
  applied to inputs.

## H4 — Property tax module (Run 3)

- **[FIN] Reassessment projection: taxes = price x assessmentRatio x
  millage.** Price = purchase price (acquisitions) or land + hard + soft
  costs (developments). assessmentRatio defaults to 0.85 (FL sales commonly
  assess below the transfer price; Save-Our-Homes caps don't apply to a new
  owner). Rejected: modeling the 10% non-homestead cap phase-in — the cap
  applies to increases AFTER the reset year, and underwriting the full
  reset is the conservative norm.
- **useReassessedTaxes defaults OFF** — every deal reproduces its current
  outputs exactly until the user opts in. When ON it REPLACES the modeled
  taxes in both expense modes (legacy flat field and every detail tax
  line); in detail mode the recoverable flag survives if any replaced tax
  line was recoverable, so NNN recoveries track the reassessed amount.
- **[FIN] Reassessed taxes grow at reassessedTaxGrowthPct** (blank = the
  deal's expense growth) while other categories keep the deal growth —
  assessed values move on their own cycle, not with opex inflation.
- Missing millage/price with the toggle on → warning + unchanged taxes,
  never a silent zero. The projection formula lives once in operations.py;
  the lookup router and the UI are pure consumers of it.
- **Adapter contract** (services/property_tax): lookup(address-or-folio) →
  normalized dict, dataSource="unavailable" + note on any failure, 24h
  source_cache, never raises. Miami-Dade uses the PA public proxy; millage
  is derived as currentTaxes / taxableValue when not stated. A new county
  is one module + one registry line.
- **Lookup UI writes nothing without a click** — same human-gate as
  extraction review; the only input write is the explicit "Apply millage
  rate" button. The caution note (modeled taxes below the reassessed
  projection, 5% grace) is display-only.

## H3 — Expense-line detail (Run 3)

- **When any opexLineItems row exists, detail mode replaces the flat expense
  fields entirely** (mixing modes silently would double count). One expense
  model serves both income paths: per-line basis resolution (annual_total |
  per_unit x unit count | psf x known SF | pct_of_egi), per-line growth
  falling back to the deal's expense growth, and detail categories mapped
  onto the statement's legacy category keys so the Cash Flow view stays
  consistent.
- **[FIN] pct_of_egi lines are never recoverable** (would be circular — the
  recovery feeds the EGI the line is computed on; also matches the
  management-fee norm). Recoverable flags on dollar lines feed the NNN /
  base-year-stop recovery pool exactly; the H1 default recoverable set
  applies only in legacy mode.
- per_unit/psf bases with no known unit count/SF fall back to annual_total
  WITH a warning, never silently.
- **Insurance stress = full engine re-computes** with the insurance line(s)
  bumped +25%/+50% (an internal flag stops recursion), so recovery and
  management-fee knock-ons are exact rather than approximated deltas.
  Categorical stress exists only in detail mode; the panel degrades
  gracefully otherwise. Rejected: analytic delta shortcuts (wrong for NNN
  deals where insurance is partly recovered).

## H2 — Mixed-use composition (Run 3)

- **[FIN] Composition, not a third engine:** the residential (unit-mix) and
  commercial (lease) paths run side by side and SUM. Fixed opex exists
  exactly once; the management fee is EGI-based and therefore splits
  linearly across components. Blended NOI = residential NOI + commercial
  NOI by construction (tested per month).
- **[FIN] Commercial recoveries in mixed deals** recover only the
  commercial SHARE of the property's recoverable opex, pro-rated by year-1
  scheduled revenue (commercial rent / (commercial rent + residential
  GPR)). Rejected: SF-based sharing (residential SF is unreliable —
  unitMix.avgSf is optional); full-property recovery (overstates income);
  EGI-based sharing (circular — EGI depends on recoveries).
- **[FIN] Component reporting allocation:** shared fixed opex is allocated
  to components pro-rata to monthly component EGI — reporting only, the
  blend is exact regardless. Blended occupancy displays as the EGI-weighted
  average of component occupancies (unit-based and SF-based occupancies
  aren't otherwise commensurable).
- **[FIN] Component-level exit:** when BOTH residentialExitCapPct and
  commercialExitCapPct are set, terminal value = sum of component forward
  12-month NOIs at their own caps; otherwise single-cap behavior is
  unchanged. Debt SIZING keeps the blended single-cap value either way
  (lenders size on blended NOI). Per-component yield on cost allocates the
  cost basis pro-rata to component value at the component caps (blended cap
  when unset) — the component YoCs bracket the blended YoC by construction.
  Rejected: NOI-share basis allocation (degenerates to the blended YoC for
  every component).
- The otherIncome input counts once, on the residential side, in mixed
  deals.

## H1 — Commercial lease engine (Run 3)

- **[FIN] Calendar anchoring:** lease dates map onto the analysis calendar
  at timeline.ANALYSIS_EPOCH (operating month m = the calendar month at
  offset m-1). Leases straddling the start are in place at month 1 with
  escalations counted from their TRUE start date. Rejected: a per-deal
  analysis-start input (the epoch is already the XIRR convention; one
  calendar everywhere).
- **[FIN] Escalation timing:** step-ups apply on lease-start anniversaries
  every escalationMonths months (default 12); fixed_pct compounds, fixed_step
  adds $psf. Rejected: calendar-January escalations (less common in
  commercial leases than anniversary escalations).
- **[FIN] Free rent abates base rent only** — NNN recoveries are still
  collected during abatement (tenants customarily pay expenses during free
  rent). Rejected: gross abatement.
- **[FIN] Recoverable opex (pre-H3 default):** every fixed category except
  replacement reserves (capital-natured) and the management fee (%-based,
  contested). NNN = pro-rata SF share; base-year stop = share of the excess
  over the base CALENDAR year (lease-start year), floored at zero, with
  pre-epoch base years extrapolated backward at the expense growth rate;
  fixed_psf recoveries stay flat (stated $psf). Modified-gross lease types
  from extraction map to base_year_stop (nearest standard structure);
  unknown types map to gross — the income-conservative reading.
- **[FIN] Rollover = expected-value single timeline** (the ARGUS-style
  simplification): at expiry, with p = renewalProbability, the downtime
  window collects p x market rent (renewal has no downtime; re-let is
  vacant), then full market rent; TI [p x renewal + (1-p) x new] x SF and
  LC [blended pct] x (starting annual rent x newTermYears) are charged in
  the month AFTER expiry, below NOI. Speculative terms run newTermYears,
  escalate annually at marketRentGrowthPct, inherit the expiring lease's
  recovery structure (base years reset), carry no free rent, and roll again
  through the horizon. Rejected: probability trees (path explosion, no
  added decision value); deferring re-let TI past downtime (immaterial
  timing inside an expected-value blend).
- **[FIN] Market rent** grows in annual steps from the analysis start;
  when marketRentPsf is unset, each lease's own escalated in-place rent at
  expiry is its market rent (avoids silent zero-rent rollovers). LC base
  approximates term rent as starting rent x term years (standard shortcut;
  ignores intra-term escalations).
- **[FIN] The general vacancyPct/occupancy machinery never applies to
  lease-modeled income** — downtime IS the vacancy; credit loss applies to
  collected revenue (base + recoveries). The otherIncome input rides along
  grown at the rent-growth clock, un-scaled by occupancy. Break-even
  occupancy in the engine treats lease deals at occupancy 1.0 for
  consistency.
- **[FIN] Stabilized NOI for lease deals** = the first 12 months of the
  lease-driven NOI (in-place, before rollover) — feeds sizing/YoC/dev exit
  value. WALT is SF-weighted remaining term (consistent with the extraction
  module's convention). The expiration schedule counts ORIGINAL contract
  expiries only (speculative re-expiries are assumptions, not lease facts).
- **Statement mapping keeps every Run-2 identity:** gpr := scheduled base
  rent, vacancyLoss := downtime + free rent, otherIncome := recoveries +
  the otherIncome input; leasing capital is a NEW below-NOI row and the
  levered identity gains "- leasingCapital". Renewal probability default
  0.70 (institutional norm 65-75%), downtime 6 months, term 5 years; TI/LC
  default to ZERO so costs are explicit opt-ins, never silent.
- Development deals with leases zero lease income during construction with
  a warning (lease-up phasing for commercial development is out of scope
  this run).

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
