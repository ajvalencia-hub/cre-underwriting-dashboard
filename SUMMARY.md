# Autonomous Build Run — Summary

Eight features (F1–F8) landed on top of the completed correctness audit:
deal persistence, a native pro-forma engine, constraint-based debt sizing
with stress, an Excel parity harness + CI, an extraction golden corpus with
named cross-validation rules, address-driven market benchmarks, IC memo
generation, and this wrap-up. Final state: **166 backend tests + 44 frontend
tests green, tsc and oxlint clean, and the native engine matches the
LibreOffice-recalculated Excel path on every mapped output with zero
deltas** (`python -m tests.parity.run`).

One commit per feature; every financial convention is logged in
DECISIONS.md (inlined below, with rejected alternatives).

## Every financial formula added, in plain algebra

Conventions: monthly periods; monthly rate r = annual/12 (30/360-style);
month 0 = closing; exit settles at the end of month N = 12 * holdYears.

### Development budget (`proforma/development.py`)
- Contingency = (Hard + Soft) * contingencyPct
- DeveloperFee = (Hard + Soft + Contingency) * developerFeePct
- BudgetExFinancing = Land + Hard + Soft + Contingency + DeveloperFee
- Hard-cost S-curve: cumulative spend share s(t) = (1 - cos(pi*t/T)) / 2
  over T construction months (per-month weight = s(t+1) - s(t)); land at
  month 0; soft costs and fee straight-line; contingency follows the
  hard-cost curve.

### Operations (`proforma/operations.py`)
- Growth step-up for operating month m: g(m) = (1 + g)^floor((m-1)/12),
  clock starting at operations start (post-construction), not at close.
- Lease-up occupancy ramp: occ(m) = occStab * min(1,
  monthsSinceConstruction / rampMonths), occStab = 1 - vacancyPct;
  stabilized thereafter.
- EGI_m = (GPR/12)*g(m)*occ(m)*(1 - creditLossPct)
  + (Other/12)*g(m)*(occ(m)/occStab)
- Opex_m = (FixedExpenses/12)*gExp(m) + managementFeePct * EGI_m
- NOI_m = EGI_m - Opex_m  (replacement reserves are inside FixedExpenses —
  NOI is net of reserves, the lender convention)
- StabilizedNOI = GPR*occStab*(1-cl) + Other - Fixed - mgmtPct*EGI (at
  today's rents, no growth)
- GPR source precedence: unit mix (sum of units * rent * 12, less
  loss-to-lease and concessions) > per-SF (SF * rentPSF) > flat GPR input.

### Debt (`proforma/debt.py`)
- Level payment: PMT = P*r / (1 - (1+r)^-n), n = 12 * amortYears
- IO months: payment = interest = B*r; then amortizing on the full curve.
- Construction financing (equity-first): each month, equity funds costs
  until exhausted, then the loan draws; B(t+1) = B(t) + draw(t) + B*r
  (interest capitalized; origination fee drawn at first draw). LTC applies
  to the budget ex-financing; financing costs are loan-funded on top.
- Carry to takeout: B(t+1) = max(0, B(t) + B(t)*r - NOI(t)) (NOI swept).
- Annual loan constant: K = 12 * PMT(1, rate, amortYears); K = rate when
  amortYears = 0 (fully IO).
- Permanent sizing = min( LTV * Value, NOI / (minDSCR * K), NOI /
  minDebtYield ); governing constraint = the argmin. Development Value =
  StabilizedNOI / exitCap; acquisition Value = purchase price.
- Takeout delta = SizedLoan - ConstructionBalance -> cash-out (+) to equity
  or a warned paydown (-).
- Stress cell (Dbps, h): DSCR' = NOI*(1-h) / (Loan * K(rate+D));
  RefiProceeds' = sizing at (NOI*(1-h), Value*(1-h), rate+D);
  Shortfall = max(0, Loan - RefiProceeds').

### Exit
- TerminalValue = (sum of NOI months N+1..N+12) / exitCap  (forward
  12-month NOI)
- NetSaleProceeds = TerminalValue * (1 - costOfSalePct) - DebtPayoff

### Returns (`proforma/returns.py`)
- Monthly IRR i solves sum_t CF_t/(1+i)^t = 0 (Newton + bisection
  fallback); annualized IRR = (1+i)^12 - 1.
- XIRR (dated flows, Excel convention): r solves
  sum_k CF_k/(1+r)^(days_k/365) = 0 — verified against Excel's documented
  reference example (0.373362535).
- NPV = sum_t CF_t/(1+r_m)^t with r_m = (1+annual)^(1/12) - 1, on levered
  flows.
- EquityMultiple = distributions / contributions; MOIC = same measure.
- AnnualizedReturn = EM^(1/holdYears) - 1.
- Payback = first t with cumulative CF >= 0, linearly interpolated, /12.
- ProfitabilityIndex = PV(positive flows) / |PV(negative flows)|.

### Metric outputs (`proforma/engine.py`)
- CashOnCash (year-1 / avg / stabilized) = annualized operating levered CF
  window / total equity in (exit proceeds excluded from operating CF).
- DSCR_m = NOI_m / DebtService_m; min and average over paying months.
- DebtYield = StabilizedNOI / Loan;  LoanConstant = K;
  ICR = StabilizedNOI / year-1 interest.
- LTV = Loan / Value; LTC = Loan / TotalCostBasis (basis includes
  capitalized interest and fees).
- BreakEvenRatio = (StabilizedOpex + AnnualDebtService) / (GPR + Other)
- BreakEvenOccupancy = (StabilizedOpex + AnnualDebtService - Other) /
  (GPR * (1 - creditLossPct))
- GoingInCap: acquisition = (inPlaceNOI or year-1 NOI) / purchase price;
  development = YieldOnCost (no separate acquisition price exists).
- YieldOnCost = StabilizedNOI / TotalCostBasis;
  DevelopmentSpread = YieldOnCost - exitCap.

### Waterfall (`proforma/equity.py`) — European, IRR-hurdle
- Contributions pari passu at lpSplit/gpSplit. Distribution bands:
  pro-rata to the pref; pro-rata to the first tier hurdle; then each tier's
  above-hurdle splits; the last tier's splits are uncapped.
- Band fill (closed form): with monthly hurdle h_m = (1+h)^(1/12) - 1, the
  LP amount that completes a band at month m is
  y = -NPV_at_h(LP flows) * (1+h_m)^m; the band's total = y / lpSplit_band.

### Benchmarks (`services/benchmarks.py`)
- Rent percentile: HUD FMR is the 40th percentile of market rents and the
  ACS median is the 50th; log-normal fit: mu = ln(median),
  sigma = (ln(median) - ln(FMR)) / 0.2533;
  percentile = Phi((ln(rent) - mu)/sigma). Warn above the 85th, caution
  above the 70th. Single-anchor fallback uses sigma = 0.35 in log space.
- Rent-growth check: assumption vs FHFA metro HPA YoY (+200bps caution,
  +400bps warning). Employment trend: LAUS employment level YoY.

The Quick Screen's napkin math (`frontend/src/lib/quickScreenMath.ts`) is
unchanged and deliberately self-contained — it never shares formulas with
the engine.

---

# DECISIONS.md (inlined)

# Decisions Log

Non-obvious choices made during the autonomous build run, with the
alternatives rejected. Financial-convention decisions are marked **[FIN]**.

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

---

# BLOCKED.md (inlined)

# Blocked Items

## ~~F4 — local Excel-recalc parity verification~~ (CLEARED)

The LibreOffice winget install eventually completed (it was slow, not
blocked). `python -m tests.parity.run` now passes locally: **all 31 mapped
outputs match between the native engine and the LibreOffice-recalculated
Excel path with zero deltas** (IRRs to 6dp), after adding an explicit
convergence guess to the templates' IRR() formulas — LibreOffice's default
10%-per-period guess fails to converge on low monthly-IRR vectors.

## Pre-existing (not introduced by this run)

- `ANTHROPIC_API_KEY` is unset in backend/.env — LLM extraction fallback and
  ambiguous-document classification degrade to heuristics (by design).
- `FRED_API_KEY` is unset — /api/market/rates returns graceful nulls and the
  rates helper text stays hidden (by design).
