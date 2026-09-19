# Decisions Log

Non-obvious choices made during the autonomous build runs, with the
alternatives rejected. Financial-convention decisions are marked **[FIN]**.

## Engine audit fixes (post-Run 5, owner-approved)

An external analyst/engineer audit found calculation defects; the owner
approved engine changes to fix them. Each fix has a test that fails before
it. Where a fix moves the regression baseline, the entry lists which cases
and metrics moved and why — the baseline is regenerated only for that
stated reason.

- **IRR solver never raises**: NPV at the solver's rate bounds over/under-
  flowed on long holds (a 25-yr hold at 30% vacancy and 10% debt failed the
  compute with a 500, and one such cell failed a whole sensitivity sweep,
  tornado, goal seek and the exports). The NPV now returns its signed
  limit (latest flow dominates near -100%, earliest at very high rates),
  and Newton hands over to bisection on a non-finite value. Baseline
  unchanged. Rejected: catching the error in each service (hides the root
  cause, still no IRR for valid deals).
- **[FIN] Several IRRs are reported, not hidden**: flows that change sign
  more than once can have several IRRs; the solver returns one. When a flow
  vector changes sign twice or more, the engine scans the NPV for every
  root and warns with all of them, pointing to NPV and equity multiple.
  One sign change (the usual deal) skips the scan (Descartes' rule), so
  compute and Monte Carlo cost is unchanged. Baseline unchanged.
- **[FIN] Construction LTC is measured on total cost including capitalized
  interest and loan fees; the origination fee is charged on the loan
  commitment** (supersedes the F2 "LTC ex-financing, financing loan-funded
  on top" rule and the first-draw fee simplification). Lenders size LTC on
  a budget that includes the interest reserve and fees; the old rule let a
  stated 60% LTC carry ~61.4% of total cost as debt, understating equity
  and overstating levered IRR, and the fee came to ~1% of one draw.
  Circular, so the engine iterates to a fixed point (equity = (1 - LTC) x
  total cost, commitment = LTC x total cost); the construction balance
  ends at the commitment. The Excel export writes the solved equity and
  commitment as values (a spreadsheet would need iterative calculation)
  and adds an "Implied LTC" check cell computed from its formulas. New
  result block `constructionLoan` {commitment, equity, totalCost, ltc}.
  **Baseline moved: analytic_development only** (LTC 0.6, 1% fee): levered
  IRR 27.36% -> 26.88%, equity multiple 3.58 -> 3.48, yield on cost 8.77%
  -> 8.73%, loan fee ~$2.7k -> $107k; 89 values in that case. The other
  five cases have no construction loan and are unchanged.
- **[FIN] Development permanent takeout can have its own max LTV**
  (`permanentLtvPct`, development only, blank = the shared ltvOrLtc). One
  input used to set both the construction LTC and the perm LTV, so a 60%
  LTC build couldn't refi into a 70% LTV perm. Acquisitions (one loan)
  ignore it. Baseline unchanged (blank everywhere).
- **[FIN] Value-add yield on cost uses post-renovation, untrended NOI.**
  The basis already carried the full renovation budget (J1) but the
  numerator was in-place NOI, so a program that raises rents LOWERED yield
  on cost (hand case: 12.00% -> 11.43% with a $100 premium; now 12.57%).
  The numerator is the 12 months after the program completes, with every
  growth rate zeroed (today's rents + delivered premiums), less the same
  reserves deduction as the in-place figure. Debt sizing stays in-place
  (J1: lenders size on in-place). Deals without a program are unchanged;
  a program that doesn't finish within 20 years falls back to in-place
  with a warning. Baseline unchanged (no baseline case has a program);
  test_renovation's hand expectation updated from 180,000 to 216,000 NOI.
- **[FIN] Min DSCR is the worst LOAN YEAR** (12 months of NOI over 12
  months of debt service, from the first debt-service month; a trailing
  partial year is dropped when a full one exists). The minimum of monthly
  DSCRs let one rollover-downtime month set the headline — lenders test
  annual (trailing/forward 12) coverage. `minMonthlyDscr` keeps the old
  number; `underwrittenDscr` (NOI − reserves) and the insurance-stress
  minDscr follow the same annual rule; `avgDscr` is unchanged. The Excel
  export's minDscr is the same windows as SUM/SUM terms. **Baseline moved:
  commercial_rollover only** — minDscr 0.83x -> 1.12x (stress variants
  0.81 -> 1.12, 0.80 -> 1.11); every case gains the `minMonthlyDscr` key.
  Baseline files are merged value-by-value (only real changes) so
  float noise from regenerating on another machine doesn't churn them.
- **[FIN] Per-deal analysis start (closing) date** — `analysisStartDate`,
  blank = the fixed 2026-01-01 epoch (so every existing deal and the
  baseline are unchanged). Supersedes the H1/F2 rejections: they held when
  the epoch only moved XIRR by leap-day noise, but lease start/expiry
  dates, rollover downtime, free rent and base years all map through it,
  so any deal closing after Jan 2026 was mis-timed — and increasingly so
  every month. Implemented as a context variable set around each compute
  (thread-safe for the Monte Carlo worker) rather than a parameter on
  every lease function; operations' revenue-share-by-year uses it too.
  Test: moving the start date and every lease date by two years leaves
  every output identical; a bad date warns and falls back.
- **Engine inputs are type- and range-checked against the schema**
  (proforma/input_validation.py, run first in engine.compute so every path
  — compute, sweeps, Monte Carlo, imports, exports — is covered). The
  engine's lenient number reader treated any non-number as the default, so
  a vacancy imported as the text "0.1" read as 0 (levered IRR 11.57% ->
  15.39%, silently). Now: numeric text ("0.1", "$1,250,000") is read as
  the number with a warning; any other value in a numeric field or table
  cell raises InsufficientInputsError naming it (the API's existing 422,
  and the UI already links each entry to its field); values outside the
  schema range compute AS ENTERED with a warning — never silently clamped.
  Rejected: rejecting out-of-range values (the UI lets users commit them
  deliberately) and clamping (the number on screen must be the number
  used). New schema flag `zeroDisables` for sizing constraints where 0
  means "off" (dscrConstraint's min of 1 contradicted the engine's
  0 = no constraint); the frontend range check honours it too. ~0.05 ms per
  compute. Baseline unchanged.
- **Inputs the engine ignores are labelled, not hidden**: 25 schema fields
  (hotel, for-sale homes, retail rent roll, loan term, total equity, draw
  schedule, TI/LC PSF, …) looked modeled but Compute never reads them.
  They carry `"templateOnly": true`; the form says "Not used by Compute —
  only written to an Excel template that maps it", or one banner for a
  section that is entirely template-only. Rejected: removing them (they
  legitimately feed mapped Excel templates) and silently implementing
  them piecemeal. test_template_only_fields keeps the flag honest both
  ways (flagged-but-read and read-nowhere-but-unflagged both fail).
- **Going-in debt yield** (`goingInDebtYield`, acquisitions with debt) =
  in-place / year-1 NOI over the loan; the existing debtYield (stabilized
  NOI, the sizing view) is relabelled "(stabilized NOI)". Lenders quote the
  going-in figure; a deal sized on stabilized NOI showed only the
  flattering one. Baseline: key-only additions.
- **American waterfall says when tier 1's hurdle isn't applied**: the G1
  deal-by-deal convention (tier-1 promote starts once pref + capital are
  returned) is kept, but a tier-1 hurdle above the pref now produces a
  warning pointing to the european style. Baseline unchanged.
- **Backups: rotation per day, restore is undoable, failures are
  visible.** Keeping the last 7 SNAPSHOTS let 7 launches in one day (the
  desktop app backs up at launch, and "Restart to apply" relaunches) wipe
  every older day. Now: one snapshot per day for 7 days; the automatic run
  skips when the newest daily is under 20 h old; a restore first snapshots
  the live DB as `pre_restore` (keep 5) so it can be undone; kind/name are
  validated (a name like `../../x` used to be joined into a path); the
  scheduler logs failures and Settings shows the last automatic outcome
  (it used to `except: pass`).
- **Documents: a shared file is removed only with its last record.** Uploads
  are stored once per content hash, so one file can back a Documents upload
  and several deals' attachments; deleting any one record deleted the file
  for all of them, and re-uploading then 500'd (a one-row-per-hash lookup).
  Reuse is limited to general documents and restores a file missing from
  disk.
- **[FIN] Lease-roll deals: general vacancy and speculative-lease free
  rent** (roadmap #10). `leaseGeneralVacancyPct` tops each month's loss up
  to that share of potential revenue (scheduled base rent + recoveries)
  where rollover downtime falls short — ARGUS's "reduce by absorption &
  turnover vacancy" method; rejected: stacking it on top of downtime
  (double-counts vacancy in rollover months). Credit loss then applies to
  what's left. `freeRentMonthsNew` abates the re-let path's base rent for
  that many months after downtime; `freeRentMonthsRenewal` the renewal
  path's from the renewal start; both probability-weighted like the rest
  of the rollover blend, base rent only (existing free-rent convention).
  All default 0: baseline unchanged. The Excel export already refuses
  lease deals.
- **[FIN] Loan maturity inside the hold is refinanced** (roadmap #11).
  `loanTermYears` was ignored, so a 10-year hold on a 5-year loan never
  met its balloon. When the term (from close for acquisitions, from the
  permanent takeout for developments) ends before the exit month, the
  balloon is refinanced: a new loan sized by the same LTV/DSCR/debt-yield
  constraints on FORWARD 12-month NOI and value (NOI / exit cap) at that
  month, priced at the loan rate + refiRateSpreadPct (acquisitions; the
  development perm rate already carries it), fully amortizing from the
  next month, refiCostsPct paid by equity; the net cash-out (+) or paydown
  (−) goes to equity, with a warning describing it. Rejected: paying the
  balloon from equity (not the base case) and an extension option (a
  separate feature). Blank term = no maturity, as before; a term that ends
  AT the exit is simply repaid by the sale. Result block
  `maturityRefinance`; the Excel export refuses such deals (it mirrors one
  loan). refiRateSpreadPct / refiCostsPct are now shown for acquisitions
  too. Baseline unchanged.
- **[FIN] User construction draw schedule shapes spending** (roadmap
  #12). The table was ignored (S-curve only). Its monthly amounts are used
  as WEIGHTS for the non-land budget over months 1..N (land stays at
  close): the schedule always spends exactly the budget, so a table that
  doesn't add up is scaled with a warning rather than silently changing
  total cost; out-of-range months fold into the nearest build month.
  Equity-first funding and the LTC solve run on the result. Rejected:
  treating the amounts as literal dollars (a typo would change the
  budget) and as loan draws (the engine's funding order decides those).
  The Excel export refuses a custom schedule (its Draws sheet mirrors the
  S-curve). Blank = S-curve; baseline unchanged.
- **[FIN] Trended vs untrended yield on cost; optional growth during
  construction** (roadmap #23). yieldOnCost stays untrended (today's rents,
  the sizing view) and is now labelled so; `trendedYieldOnCost` is the
  first 12 stabilized months of the modeled NOI (with growth, after
  reserves) over the same basis. Development rents/expenses still start
  growing at delivery by default (flat through the build — conservative);
  `growDuringConstruction` (development only) trends them from close,
  implemented as an offset on the single growth-clock helper, set per
  compute like the analysis calendar. Baseline: key-only additions.
- **[FIN] Exit mechanics** (roadmap #24). `exitNoiBasis = trailing` caps
  the last 12 months of the hold instead of the forward 12 (forward stays
  the default, F2). `prepaymentPenaltyPct` charges that share of the loan
  balance repaid at sale — a step-down, or a flat approximation of
  defeasance / yield maintenance — as a financing cost (levered only;
  reported as `prepaymentCost`). Rejected: a full yield-maintenance
  calculator (needs a Treasury curve the app doesn't have). Exit on NOI
  after reserves already exists (reservesConvention =
  above_noi_underwritten). The Excel export refuses trailing exits,
  prepayment costs and growth during construction. Baseline unchanged.
- **Template results are labelled LibreOffice, and the Template tab can
  check LibreOffice against Excel** (roadmap #13). Read-back results come
  from a LibreOffice recalculation but were labelled "Excel"; LibreOffice's
  IRR/XIRR root-finders and some financial functions differ. Labels now
  say "recalculated by LibreOffice". The check recalculates the UNMODIFIED
  template (a copy, prepared exactly as Generate prepares its output:
  openpyxl round-trip + fullCalcOnLoad — without the flag LibreOffice
  keeps the cached values and the comparison is vacuous, found while
  testing) and compares each mapped output with the value Excel saved in
  the file (rel/abs 1e-6). On demand, not on upload: it costs a
  LibreOffice cold start and needs the output mapping. Recalc behavior and
  the downloaded workbook are unchanged.
- **Database schema version** (roadmap #21). SQLite `user_version` holds
  SCHEMA_VERSION (1 = the current set of hand-rolled migrations; bump it
  with each new step). Startup: `prepare_migrations()` BEFORE create_all
  refuses a database written by a newer build (DatabaseTooNewError, shown
  on the desktop app's error page) and backs up an existing database
  about to move to a newer version ("pre_migration", keep 3, listed in
  Settings as "Before app update"); a brand-new database needs neither.
  `run_migrations()` then runs the steps and stamps the version. The
  pre-migration backup is also the safety net for the old scenarios
  table rebuild, whose RENAME/CREATE aren't transactional under the
  sqlite3 driver. Rejected: adopting Alembic now (a new dependency the
  current migrations don't need).
- **Typed API contract** (roadmap #22). `openapi-typescript` (dev-only;
  an npm `overrides` entry lets it use the project's TypeScript 6 — its
  peer range says ^5, generation verified on 6) turns the backend's
  OpenAPI schema into `src/types/api.gen.ts`, regenerated by
  `npm run gen:api` against scratch storage; a CI job fails on a stale
  file. Rather than rewrite every frontend type, `apiContract.ts` asserts
  per pair that the API's declared response fits the UI's type — 32 pairs;
  a deliberately broken field was confirmed to fail `tsc`. Response models
  added for 30+ dict-returning routes (`app/api_models.py`) keep extra
  keys (`extra="allow"`) and mark defaults as always present in the
  schema, and declare only fields the UI treats as always present —
  conditional blocks (compute's gpEconomics/statement) stay undeclared so
  no response gains a null; responses are unchanged (regression baseline
  passes). Deal status and a few enums are documented in the schema but
  not enforced on output (stored legacy values must still load). Property
  tax, benchmarks and demographics stay undeclared: provider-dependent
  shapes. Found and fixed on the way: a stale backup-listing test fake,
  and untyped extraction results (now fully modeled).
- **Engineering hygiene** (roadmap #32).
  - ruff + mypy (dev-only, `backend/requirements-dev.txt`, config in
    `backend/pyproject.toml`), run by a `backend-lint` CI job. mypy passes
    with the pydantic plugin; the 20 modules that still had errors (the
    engine, memo/deck/extraction services…) sit on a ratchet override —
    entries come off as they're cleaned, never go on. Target stays Python
    3.10: the local backend venv runs it (ruff's 3.11-only `UTC` rewrite
    broke the suite before the target was lowered).
  - SQLite runs in WAL with a 15 s busy timeout; backup snapshots switch
    back to a rollback journal so each stays one file. Rejected:
    `synchronous=NORMAL` (faster, but can drop the last commit on power
    loss).
  - Hypothesis perturbs the analytic deals within the schema's ranges
    (money in cents, percentages to a millionth — subnormal values produced
    only meaningless infinities) and found four inputs the form accepts
    that crashed Compute: min DSCR over a loan year with no debt service,
    100% credit loss in break-even occupancy, and fixed/floating payments
    at a rate where 1 + r rounds to 1. All fixed with regression tests.
    Negative exit NOI still gives a negative terminal value — left as is
    and raised with the owner.
  - Quick Screen and engine share cases: the vitest file writes napkin
    results and the Send to Deal Inputs payload to
    `backend/tests/fixtures/quick_screen_cases.json`; the backend computes
    the same payload. Costs, loans and acquisition cap rate agree; the
    development yield on cost does not, because the payload omits
    operating expenses by design — a strict xfail until the owner decides.
  - App.tsx split into navigation, a Quick Screen hook and header
    components (1,321 → 968 lines). The deal lifecycle stays in App.
  - The `.app` is built, self-tested and uploaded by a `desktop-app` CI job
    on pull requests and main (not every push: several macOS minutes).
- **Signing and notarization** (roadmap #31, part 1). `desktop/sign_mac.sh`
  signs inside-out (every Mach-O file, then the bundle; Apple advises
  against `--deep`) with the hardened runtime and a secure timestamp,
  verifies, reruns the frozen self-test on the signed app, and notarizes +
  staples when a notarytool keychain profile is given; `build_mac.sh` calls
  it only when SIGN_IDENTITY is set. The only entitlement is
  allow-unsigned-executable-memory (libffi closures for pyobjc/pywebview).
  Verified with an ad-hoc signature: self-test passes and the window loads
  and talks to the backend under the hardened runtime (ad-hoc needs
  disable-library-validation too, since it has no Team ID; a Developer ID
  build doesn't). Not verifiable here: notarization itself (needs the
  owner's Apple account).
- **Update check** (roadmap #31, part 2; owner chose it over Sparkle). The
  desktop shell asks api.github.com for this repo's latest release
  (User-Agent with the version, nothing else) at launch at most once a day,
  caches the answer in desktop-settings.json, and the UI shows a
  dismissible banner (per release tag) with Download (the zip asset, else
  the release page) and What's new, opened in the browser. Settings →
  Updates shows the version, a "Check now" and an off switch (off = no
  request at all). Tags compare as vMAJOR.MINOR.PATCH against
  cre_desktop/version.py, which the build also writes into Info.plist.
  Network errors are reported in Settings, never in the way at launch.
  Rejected: Sparkle (native framework, appcast hosting, update signing
  keys) and in-app installation.
- **[FIN] Build-to-sell homes** (roadmap #26): its own cash flow
  (services/proforma/for_sale.py) for single-family / townhouse
  developments with "Model as For-Sale" on and a sale price entered —
  without a price the deal keeps computing as a rental, so no existing deal
  changes silently. Land at close; site work (hard on the S-curve, soft
  straight-line, contingency) over the construction months; homes close at
  the absorption pace from month S + homeBuildMonths, each home's
  construction (plus contingency) spent evenly over the build months ending
  at its closing; prices grow annually from the first closing; selling
  costs = cost of sale %. Developer fee = % of each month's non-land spend.
  Financing: LTC on total cost including interest and the origination fee
  (fixed point, as for the development loan); equity first up to its
  share, then a revolving loan; a month's closings pay that month's costs,
  then repay the loan, then go to equity (lenders sweep proceeds; builders
  fund starts from closings). Outputs: IRRs, multiples, profit, gross
  margin (profit before financing / net revenue), peak equity (the deepest
  cumulative equity position) and sellout period; no NOI, exit cap or hold,
  so the hold sweep and Excel export decline these deals. The statement
  identity (levered = noi − debt service + draws − costs − fees + sale
  proceeds) still holds, with debt service = interest + loan repaid from
  closings. Single-family / townhouse rentals (for-sale off) now compute
  GPR from homes × monthly rent when both are entered. Rejected:
  presale deposits and release-price schedules (inputs don't exist yet),
  and a separate horizontal-development loan.
- **[FIN] Hotel operations** (roadmap #25), USALI summary level, for
  deals whose property type is Hotel (a lease rent roll, if entered, still
  takes precedence; a hotel component of a mixed-use deal warns that it's
  ignored). Rooms revenue = keys × ADR × occupancy × 365/12 a month (a flat
  month length, like the rest of the engine's monthly math); F&B and other
  revenue are annual at stabilized occupancy and scale with occupancy in a
  ramp; ADR and ancillary revenue grow at the rent growth rate from
  opening. Departmental and undistributed expenses, the management fee and
  the FF&E reserve are shares of total revenue; the franchise fee is a
  share of rooms revenue (how brands charge); fixed charges are the usual
  expense inputs, with a warning if operating lines (payroll, utilities…)
  are entered on top of the ratios, or reserves on top of FF&E. NOI is
  after FF&E (the lender/appraiser convention), so value and sizing use it.
  Statement identities hold: GPR = rooms revenue at 100% occupancy, vacancy
  = unsold room-nights, other income = F&B + other, EGI = total revenue.
  Credit loss isn't applied and the general management fee is ignored
  (warned). Break-evens treat revenue-linked costs as variable (the
  fixed-opex formula would put a hotel's break-even far too high); revenue
  is linear in occupancy, so the stabilized break-even is exact:
  o* = (fixed + debt service) / ((revenue − revenue-linked costs) / o).
  The Excel export refuses hotels. Rejected: day-count-exact months (would
  make hotel months differ from every other asset's), and departmental
  ratios per department (the inputs are one ratio each).
- **[FIN] Market leasing profiles** (roadmap #27). ARGUS-style market
  leasing assumptions per space type: a `marketLeasingProfiles` table whose
  rows may override any deal-level rollover input (market rent and growth,
  renewal probability, downtime, new term, free rent, TI, LC, renewal
  spread); a blank cell keeps the deal's value, so a profile can differ in
  one assumption only. A lease opts in through its Leasing Profile column
  (matched case- and space-insensitively; an unknown name warns and uses
  the deal assumptions). Everything downstream of the rollover — the
  probability-weighted timeline, leasing capital, and the gross-up
  occupancy projection — reads the lease's own assumptions. Deals without
  profiles are byte-identical (regression baseline; the per-lease drill-down
  gains a `leasingProfile` key only when one is set). The Excel export
  already refuses lease-level deals. Rejected: a select column of profile
  names (schema options are static) and per-profile general vacancy (it's
  a property-level haircut, as in ARGUS).
- **Investment-committee sign-off** (roadmap #28; owner chose local
  sign-off over accounts and logins). An append-only IcEvent log per deal
  (submit, approve, reject, return, reopen, comment: who, when, why); the
  state is derived from it. A submit computes the deal and stores those
  inputs and outputs, so an approval signs a specific version; a deal that
  can't compute can't be submitted. N distinct approvers (case- and
  space-insensitive names) approve a submission. While submitted, approved
  or rejected, the server refuses underwriting-input changes (409), and the
  UI makes none (a disabled fieldset, and guards on presets, goal seek,
  scenario loads, extraction and Quick Screen sends) so autosave never
  loops on a refusal; each IC step saves pending edits first. The Quick
  Screen napkins, critical dates and provenance stay editable. The log is
  exported/imported with the deal. Rejected: a lock that also froze the
  napkin (it shares the inputs blob, but isn't underwriting); making
  "rejected" editable without a reopen (the reason trail would have gaps).
- **Owner decisions, 2026-09-19** (raised by the #32 tests):
  - Quick Screen → Send to Deal Inputs now carries the napkin's operating
    expenses as one Opex Detail row (category other, annual dollars, note
    "Operating expenses (Quick Screen estimate)") and credit loss 0. It
    carried none, so Compute ran with no opex. Annual dollars rather than
    % of EGI: the engine reports every % of EGI row as the management fee.
  - **[FIN]** A negative capitalized sale price floors at $0 with a warning
    (engine and export).
  - **[FIN]** Amortization of 0 years = interest-only everywhere (the payment
    function used to repay the loan in month 1).
- **Export: a development with no construction period** carried only land
  at month 0 on the Draws sheet (the engine spends the whole budget at
  close), so its exported IRR was nonsense. Fixed, with a new parity case
  `export_development_no_build_period`.

## Opex Detail — pct_of_egi lines report under their own category (post-Run 5)

- **[FIN] Only `management_fee` pct_of_egi rows (plus legacy
  `managementFeePct`) are the statement's `managementFee`.** A pct_of_egi
  row of any other category reports under that category's
  `fixedOpexByCategory` key (`_DETAIL_CATEGORY_KEYS`; unknown → `otherOpex`),
  computed monthly as EGI × pct and summed with any dollar lines of the same
  category. Previously every pct_of_egi row was summed into `egiPctTotal` and
  shown as management fee, so e.g. "other at 2% of EGI" was mislabeled.
- **Reporting-only; no number moves.** The builders still charge the
  combined `egiPctTotal` × EGI in opex/NOI (so NOI is bit-identical), and
  expose that total internally as `ops["egiBasedOpex"]`. Consequences kept
  deliberately unchanged:
  - Break-evens (J9) scale ALL EGI-based opex with EGI — they now read
    `egiBasedOpex` instead of the statement's `managementFee` row.
  - The EGI-based lines merge into `fixedOpexByCategory` only when the
    statement is packaged (`engine._merge_egi_opex`), not in `ops`: T&I
    escrow sizing and the mixed-use component allocation keep reading
    dollar lines only, so a "taxes at % of EGI" row does not start funding
    escrow.
  - Mixed-use: the residential run still carries the combined pct as one
    legacy `managementFeePct` (and component opex uses the full EGI-based
    amount); only its reporting is split by re-applying the line split to
    residential EGI.
  - Open question, NOT changed: with `mgmtFeeRecoverable` on, the recovery
    pool contribution still uses the combined pct (all pct_of_egi lines),
    as before. Restricting it to management_fee rows is arguably more
    correct but would change recoveries/NOI, so it needs its own decision.
- **Excel model export keeps parity rather than refusing.** "Mgmt fee % of
  EGI" now holds only management_fee rows; each other category gets its own
  "<label> % of EGI" input (written only when present, so existing exports
  are byte-identical in layout), folded into the Model opex column (header
  becomes "Opex ex mgmt fee (fixed + other % of EGI)") and the Outputs
  stabilized-NOI helper. New parity case `export_opex_detail_egi_pct`.
- Rejected: moving the pct lines into the byCategory vectors inside
  `_fixed_expense_vectors` — every consumer of that dict (escrow, mixed-use
  fixed_total, gross-up pools) would silently start treating EGI-based
  dollars as fixed.

## Settings v1 — scaffold, dark mode, backups panel, integrations (post-Run 5)

- **Two-tier settings architecture**: per-browser UI preferences live in
  localStorage (lib/uiPrefs.ts — same pattern as pipeline saved views);
  server-affecting settings stay server-side. This slice needed NO new
  server storage — the backups panel and integration status are pure
  surfacing of existing endpoints/config.
- **Dark mode is a contained `.dark`-scoped CSS override layer** in
  index.css remapping the finite utility palette the app actually uses
  (structural neutrals invert, tinted status chips become translucent
  accents, primary slate-900 buttons flip to light-on-dark,
  `color-scheme: dark` flips native controls). Rejected: adding `dark:`
  variants to hundreds of call sites — a mechanical diff touching every
  component for the same visual result, and a merge hazard for every
  future component. The override file IS the registry of the app's
  palette; new components using the same utilities inherit dark for
  free. Documented light-only surfaces: generated documents (memo
  matplotlib PNGs, decks, Excel) stay light by design.
- Theme pref: light | dark | **system (default)** — system follows
  `prefers-color-scheme` live via a media-query listener; the class is
  applied in main.tsx BEFORE first paint (no light flash).
- **The Backups panel is the J16 endpoints' first UI** — list, back up
  now, and restore behind a confirm dialog that states the overwrite +
  restart consequence; the response's uploads-manifest count is shown
  so the operator can verify files survived.
- **Integration status returns FLAGS ONLY** (`configured: bool` per env
  var) — key values never leave the server, asserted by test. BLS is
  labeled as working unauthenticated; every source's graceful
  degradation is the existing contract, the panel just makes it
  visible.

## Dealflow segregation, part 3 — follow-up items (post-Run 5)

- **[FIN] Development pro-forma rents are benchmarked net of a 15%
  new-construction premium** (`NEW_CONSTRUCTION_RENT_PREMIUM`): ACS
  medians and HUD FMRs describe the EXISTING stock, which new
  construction legitimately out-rents — so the percentile test divides
  the claimed rent by 1.15 before the unchanged warning/caution
  thresholds, and the flag's wording switches to pro-forma framing with
  a "verify against recent deliveries" nudge. Acquisitions get no
  allowance (their in-place rents ARE existing stock); the flag's
  subjectValue always reports the CLAIMED rent, never the netted one.
  Rejected: separate softer thresholds for developments — a premium on
  the rent is the actual economic claim being made; moving thresholds
  hides it.
- **Export bundles carry pipeline status** (validated against the stage
  registry on import; junk falls back to Screening WITH a warning,
  missing stays silent — additive field, same bundle schemaVersion).
- **Acquisition quick screen reaches parity**: acq_-prefixed URL params
  + a `screen` param (existing shared development links keep their
  meaning), sidebar estimates follow the ACTIVE napkin, and solve-for
  hints solve BOTH verdict legs (CoC and DSCR) in closed form — a
  price hitting the CoC target that still fails DSCR wouldn't flip the
  tier, so the binding constraint decides.
- **Search gains a dealflow facet**: deal-scoped results carry an
  ACQ/DEV badge, and `acq:` / `dev:` query prefixes restrict deals/
  tenants/notes to one flow. Global comps drop out under a facet — a
  faceted query is explicitly a dealflow search.

## Dealflow segregation, part 2 — type-aware tools (post-Run 5)

- **Analysis tools only offer fields the engine reads for THIS deal.**
  Sensitivity drivers, the goal-seek picker, and the Risk panel's
  "other input" list now filter through `visibleFields(schema, values)`
  (section + field visibleWhen) — sweeping/solving over the other
  dealflow's inputs (landCost on an acquisition) produced a silent flat
  grid. The backend goal-seek API stays permissive (deals can change
  type mid-solve); the UI is where the constraint belongs.
- **Risk suggestions are per dealflow**: developments sample hardCosts
  where acquisitions sample purchasePrice — the old hardcoded
  purchasePrice suggestion seeded a nonsense ±10% band around $1 on a
  development.
- **The tornado's cost driver label names the field actually
  perturbed** ("Purchase price" / "Hard costs") instead of the merged
  "Hard costs / purchase price".
- **The Excel export refuses a missing dealType** instead of silently
  producing an acquisition-shaped workbook; the one-page deck now
  states the deal type (it never did).
- **The Quick Screen has BOTH napkins**: a Development/Acquisition
  toggle; the acquisition side tests cash-on-cash AND DSCR (strong ≥
  6% + 1.25x, marginal ≥ 4% + 1.15x; all-cash deals satisfy the DSCR
  leg vacuously so unlevered yield decides) with amortizing debt
  service via the standard mortgage constant — deliberately NOT the
  development yield-on-cost spread test, which answers a construction
  question. Its "Send to Deal Inputs" maps dealType=acquisition,
  price/closing/NOI/financing (nothing guessed; same principle as the
  development mapping). v1 scope: no URL persistence, solve-fors, or
  sidebar estimates for the acquisition side yet (documented deferral).
- **Bug fix**: the development mapping wrote its per-UNIT hard cost
  into `hardCostsPsf` when sized by units — a $/unit figure in a PSF
  field. It now maps only in SF mode; the total in `hardCosts` is what
  the engine reads either way.

## Dealflow segregation — acquisitions vs developments (post-Run 5)

- **Stage registry is a single source of truth** in
  input_schema.json `dealStages`, consumed by backend validation
  (schemas.DEAL_STAGES_BY_TYPE / DEAL_STATUSES) and mirrored in
  frontend lib/dealStages.ts — replacing FOUR hand-copies of the status
  enum. Cross-language sync is pinned by twin tests asserting the same
  literals on both sides (a node-fs read from vitest was rejected: the
  app tsconfig has no node types and a types-only dep wasn't worth it).
- **Acquisitions keep the original six transaction stages** (screening →
  underwriting → loi → under_contract → closed | dead) — ZERO migration
  for existing deals. **Developments get project-lifecycle stages**
  (screening → feasibility → site_control → entitlements →
  pre_construction → construction → lease_up → stabilized | dead), per
  the user's choice of lifecycle over transaction framing.
- **The stored status column accepts the UNION** of both sets; each
  board's dropdown constrains to its type's stages plus the deal's
  current value marked "(legacy)" when out-of-set. Rejected: a forced
  one-time migration mapping e.g. loi→site_control — silently
  reinterpreting the user's pipeline data is worse than showing a
  labeled legacy value they move themselves. Terminal set is now
  {closed, stabilized, dead}.
- **Deals are TYPED FROM BIRTH**: New Deal is a two-choice menu, each
  pipeline board has its own typed create button, and the OM wizard's
  create step carries a dealflow select (seeded acquisition — OMs are
  overwhelmingly existing assets — flipped to development when the
  reviewed values carry budget fields). This kills the old split where
  a fresh deal was "missing dealType" on share/deck/portfolio but a
  silent acquisition on hold-sweep/Excel export. Untyped legacy deals
  are NEVER auto-assigned: the pipeline shows an "assign a dealflow"
  strip and the user picks.
- **Bulk stage changes across a mixed selection offer only the shared
  stages** (screening, dead) — applying "construction" to an
  acquisition via bulk is unrepresentable in the UI (the API validates
  against the union, since deals can change type).
- **Staleness thresholds are per-stage**: entitlements/construction
  45/90 days, pre-construction/lease-up 30/60, everything else the
  original 14/30 — a development in a year-long entitlement review no
  longer badges red forever.
- Critical-date quick-add presets are per dealflow (acquisition keeps
  LOI/DD/financing/closing; development gets feasibility deadline, land
  closing, permit approval, groundbreaking, C/O, stabilization).
  Pipeline CSV and the portfolio roll-up gain a deal-type dimension
  (byDealType buckets; untyped is its own labeled bucket, never
  guessed).

## J16 — Docker + backup (Run 5)

- **One image serves the whole app.** A multi-stage Dockerfile builds the
  SPA (node stage) and copies the dist into the Python runtime, which
  serves it via StaticFiles mounted LAST (every /api route wins;
  html=True gives SPA fallback). LibreOffice, Tesseract, and Poppler are
  baked in so every server-side path (parity recalc, memo PDF, OCR, PDF
  rasterize) works in the container. Rejected: a separate nginx frontend
  container — a second service and a proxy hop for a single-user tool.
- **Storage is volume-relocatable via `CRE_STORAGE_ROOT`** (image sets
  `/data`; dev defaults to `backend/storage`), so the DB, uploads, and
  backups all live on one named volume that survives rebuilds.
- **[safety] Backups use SQLite's online-backup API, never a file copy**
  — a copy taken mid-write can be torn. Each snapshot is a timestamped
  dir with `app.sqlite3` + a `manifest.json`; rotation keeps 7 daily / 4
  weekly. Upload BYTES are not copied (they share the volume and would
  multiply its size every snapshot) — the manifest records name/hash so
  a restore can flag a missing file. Documented in the README.
- **The scheduler is opt-in** (`CRE_ENABLE_BACKUP_SCHEDULER=1`, set only
  in the image) so dev and the test suite never spawn a background
  backup thread; the daily loop promotes the first run of each ISO week
  to a weekly snapshot.
- **Restore overwrites the live DB and requires a restart** (SQLAlchemy
  holds the old handle) — the endpoint says so and returns the uploads
  manifest so the operator can verify the volume still has every file.
- CI gains a `docker` job: `docker compose config` + `docker build`
  (build only — the container isn't run in CI) to catch Dockerfile rot.
- The pure `prune_names` rotation helper is unit-tested; the backup/
  restore round-trip runs against a scratch SQLite DB.

## J15 — Portfolio roll-up (Run 5)

- **Roll-up computes each non-dead deal live through the pure LRU-cached
  engine**, not a persisted-outputs store. "Stale-compute" is
  operationalized as "can't produce returns" — a deal whose
  engine.compute raises InsufficientInputsError is EXCLUDED from every
  total and blend and listed with the missing fields. Rejected: a
  separate stored-outputs table with a dirty flag — a second source of
  truth to keep synced, when the engine is cheap and pure.
- **Blends are equity-weighted on committed equity** (−levered[0], the
  cash in at close); a deal only weights a blend for a metric it
  actually has. Straight averaging was rejected — a $400k screening
  deal shouldn't move the book IRR as much as a $40M closing.
- **Dead deals are dropped entirely** (not part of the live book);
  every other status rolls up. Totals by status, exposure by market and
  asset class, and a concentration table (top markets by equity share)
  all sum the same committed-equity figure.
- **CSV lists every computed deal + a PORTFOLIO footer + the excluded
  set** so the export is honest about what the blend omitted.
- Pure `build_portfolio(deals)` core (thin router over it) so the
  aggregation, weighting, and exclusion are unit-tested without HTTP.

## J14 — Full IC deck (Run 5)

- **Extends the H12 renderer's absolute rule**: zero financial math in
  the deck — every slide is a formatted pass-through of a fresh engine
  compute plus saved-analysis payloads. New `build_ic_deck` returns
  (bytes, skipped[]); the eight slide keys are title, summary, market,
  returns, sensitivity, debt, waterfall, risk.
- **Slides skip cleanly and report what they dropped** (X-Deck-Skipped
  header): market skips without benchmark flags OR demographics;
  sensitivity needs a saved 2-driver run; debt needs a sized loan;
  waterfall needs an equity split or GP economics. Title/summary/
  returns/risk always render. A sparse all-equity deal with no saved
  runs produces a 4-slide deck, not a broken 8.
- **Investment thesis is a new `investmentThesis` textarea** on the deal
  (engine-inert input key — baseline untouched; needed the frontend
  `textarea` field type, added to the schema union + ScalarInput).
- **Risk slide prefers a saved Monte Carlo run, else the tornado
  top-5** (computed live in the endpoint) — so the slide is useful even
  before the user opens the Risk tab; only a deal where the tornado
  can't move the metric shows the empty-state note.
- **Market context / demographics are gathered best-effort** in the
  endpoint (external sources wrapped in try/except → None), so an
  offline run degrades to a skipped market slide rather than a 500.
  Saved sensitivity + Monte Carlo come from an optional `scenario_id`
  query param.
- Two new memo_charts renderers (demographics_bars, tornado_bars)
  follow the existing bytes-or-None contract.

## J13 — Global search (Run 5)

- **SQLite LIKE over indexed columns, no FTS.** /api/search hits
  deals.name, sale_comps.name/address/market, and deal-blob
  address/market via json_extract; migration adds ix_deals_name,
  ix_sale_comps_name, ix_sale_comps_address. Full-text search (FTS5) was
  rejected — a local single-user tool's tables are small, and LIKE keeps
  the query dependency-free and the migration trivial.
- **Tenants are a Python scan over deal lease rolls**, not an indexed
  column — tenant names live inside JSON arrays where no useful index
  exists; documented as an accepted trade-off at this table size.
  Tenant hits deep-link to their DEAL (there is no per-tenant page).
- **Ranking: prefix > substring, then alphabetical**, per group, each
  group capped at 8. Grouping order is fixed (deals, tenants, comps,
  notes) so the palette layout is stable across queries.
- **Keyboard navigation is a pure ring helper** (`nextIndex`,
  `flattenGroups` in searchNav.ts) so arrow-key wrap and Enter-to-open
  are unit-tested without a DOM; the palette component is a thin shell
  over it. Cmd/Ctrl+K toggles from a single window keydown listener.
- Minimum query length is 2 chars (a 1-char LIKE would match nearly
  everything) — the endpoint returns empty groups below that.

## J12 — Deal file cabinet + notes (Run 5)

- **Attachments generalize the Document model** (nullable deal_id +
  index via check-and-migrate) rather than adding a parallel table —
  one storage location, one dedupe-by-hash rule, one size cap
  (MAX_UPLOAD_BYTES, already env-configurable from M9). Attachments
  accept ANY extension — the cabinet is storage, not a parser input
  (extraction uploads keep their allow-list).
- **Extraction documents surface in the cabinet by provenance match**
  (the deal's `_provenance` sourceRefs name their files) with an
  "extraction source" badge — global documents are never duplicated
  into the deal.
- **PDF preview is first-page TEXT via pdfplumber**; a thumbnail image
  would require a rasterizer dependency for a cosmetic feature —
  rejected. Images preview inline via the download route.
- **Export bundles list attachments by name/hash but never embed
  them**: bundles stay small, diffable JSON, and the hash lets the
  receiver verify a manually-transferred file. Import surfaces the
  listing as a warning. Notes DO travel in the bundle (plain text).
- **Notes are markdown-lite plain text** rendered client-side
  (**bold**, *italic*, line breaks) — no frontend markdown dependency.
- Deal deletion cascades notes and attachments; files unlink only when
  no other document row shares the hash (uploads dedupe by content).

## J11 — Critical dates (Run 5)

- **Dates live in the deal's inputs blob** (`inputs.criticalDates`:
  [{id, label, date YYYY-MM-DD, notes}]) — CRUD is the ordinary deal
  PUT, and autosave, history snapshots, export/import bundles, and the
  HTML share all carry them with zero new plumbing. The engine ignores
  unknown input keys, so the baseline is untouched. Rejected: a
  critical_dates table + router — a second store and four endpoints
  for data that is deal state.
- **Date math is calendar-day, local time** (deadlines are days, not
  instants); "upcoming" = within 14 days INCLUSIVE of today and day 14;
  the pipeline strip orders overdue first (most overdue first), then
  ascending. Unparsable dates classify as 'later' — junk never alarms.
- Preset labels (LOI expiry, DD end, Financing contingency, Closing)
  are UI seeds only; the stored label is free text.

## J10 — OM-to-deal wizard (Run 5)

- **The wizard is a CHAIN of the existing gates, not a new pipeline**:
  upload → per-document type confirmation (the existing PUT /type) →
  the existing extraction endpoint → the EXISTING ExtractionReview
  component (field acceptance, unit-mix/lease proposals, blocking
  acknowledgment) → a new finalize endpoint. Nothing auto-applies.
- **The acknowledgment gate is enforced SERVER-SIDE too**:
  POST /api/deals/from-extraction returns 409 with the failure list
  when blocking cross-validation failures are unacknowledged — the gate
  cannot be bypassed by calling the API directly. Rejected: trusting
  the frontend checkbox alone.
- **Provenance lives in the deal's inputs blob** (`_provenance`:
  {fieldId → {sourceRef, confidence, source}}), written by the finalize
  endpoint from the extraction's own sourceRefs; proposal-shaped values
  (unit mix, lease roll) trace as `reviewed_proposal`. The underscore
  key is engine-inert (like _skipCategoricalStress) and rides deal
  export/import and snapshots for free. Rejected: a separate provenance
  table — a second store to keep consistent for display-only data.
- **Wizard state parks on a DRAFT DEAL** (`inputs._omWizard`: {step,
  documentIds, extractionResultId}) — resumable from the wizard's start
  screen, deletable via ordinary deal deletion, and finalize clears it
  in place (same deal id, history snapshot recorded). Rejected: a new
  wizard table/column — drafts already behave like deals everywhere
  (pipeline, autosave, delete).
- **Type confirmations are NOT restored on resume** — re-confirming is
  one click per document, and silently trusting a stale confirmation
  after documents may have changed is the wrong default.

## J9 — Operating break-evens (Run 5)

- **[FIN] Solved ANALYTICALLY on the statement's own annual sums** —
  both questions are linear given the conventions below, so no engine
  recomputes and no bisection. Operating flows only: close, sale
  proceeds, debt draws, loan fees, and escrow timing are excluded.
- **[FIN] Response model**: the management fee scales with EGI at the
  year's modeled effective rate; other income scales with occupancy
  (mirroring the engine's occupancy-share rule); every other below-NOI
  cash cost (debt service, TI/LC, operating-cash reno draws, AM fee,
  junior interest, below-NOI reserves) is held at MODELED levels.
  Variable-with-occupancy opex is NOT re-flexed — that biases the
  break-evens conservative (high), which is the right direction for a
  lender-style question. Rejected: full engine re-solves per candidate
  occupancy (accurate to the flex rules but 100+ computes per deal for
  a footer row).
- **Impossible years return null + a note carrying the out-of-range
  number** ("needs 108% of scheduled") — never a bare out-of-range
  value. Construction years return null with a construction note.
- **Baseline**: J9 adds always-present keys (statement.breakEvens,
  year-1 outputs) — the regression diff was verified KEY-ONLY (zero
  value drift across all 6 fixtures) before the sanctioned
  UPDATE_BASELINE=1 regeneration.
- Consistency pin: on a flat stabilized deal the year-1 break-even
  occupancy equals the existing quick-screen breakEvenOccupancy formula
  exactly (tested).

## J8 — Monte Carlo (Run 5)

- **numpy IS used for correlations (Cholesky)** — the run rules permit it
  because numpy is already a TRANSITIVE dependency (matplotlib, from the
  G8 memo charts, pulls it in; verified via pip freeze; it is NOT added
  to requirements.txt). The stdlib Iman–Conover fallback was therefore
  not needed.
- **Correlations via a Gaussian copula**: correlated standard normals
  from the Cholesky factor, mapped through the normal CDF to uniforms,
  then through each marginal's inverse CDF (normal marginals use the
  correlated normals directly — exact). A non-positive-definite
  correlation matrix is a typed 400 — never silently repaired to the
  nearest PSD matrix (the user's assumptions are jointly inconsistent;
  say so).
- **Deterministic given a seed** (numpy default_rng); a missing seed is
  generated and RETURNED so every run is reproducible after the fact.
- **[FIN] Peak negative cash flow = the most negative levered month
  AFTER close** (0 when no month goes negative) — the capital-call
  question. The close-month equity check is known, not risk. Rejected:
  including month 0 (dominates every distribution with a known number).
- **Each trial sets `_skipCategoricalStress`** — the H3 insurance-stress
  recomputes would triple per-trial cost for numbers nobody reads inside
  a simulation.
- Failed trials (driver values pushing inputs out of domain) are counted
  and reported (`failedRuns`), excluded from statistics; ALL trials
  failing is a typed error naming the likely cause.
- Progress via a polling job store (validation is synchronous so bad
  requests fail the POST, not the poll); n ≤ 2000, drivers ≤ 6, both
  typed errors not silent clamps. Saved runs live in a new
  scenarios.monte_carlo JSON column (check-and-migrate) and feed an
  optional memo risk section — omitted when absent, never fabricated.
- UI driver suggestions mirror the tornado's driver set expressed as
  concrete numeric fields (the tornado's composite "rent" driver has no
  single input path to sample).

## J7 — Generalized goal-seek (Run 5)

- **Bracket scan (12 points) + bisection; monotonicity is NEVER assumed.**
  Every adjacent pair of valid scan points with a sign change of
  (metric − target) is a candidate bracket; the one nearest the CURRENT
  input value is bisected and the midpoints of the others are reported.
  Rejected: Newton/secant methods — engine metrics have kinks (IO
  cliffs, cap strikes, sizing-constraint switches) where derivative
  methods diverge; bisection inside a verified bracket cannot.
- **Bounds: explicit request bounds > schema min AND max (both defined)
  > ±80% of the current value.** A zero current value with no schema
  bounds is a typed error asking for bounds, not a guessed range.
- **Metric-typed tolerances**: percent outputs 1e-5 (0.1bp), currency
  $100, ratios/multiples 1e-4; iteration cap 60 including the scan.
- **A no-solution is a 200, not an error**: {solvedValue: null, reason,
  scanned points, range} — the scan detail IS the answer ("the metric
  ranges X..Y here"); only malformed requests 400. A metric that is
  None at a scan point (e.g. DSCR with no debt) breaks brackets rather
  than being treated as zero.
- **Every evaluation goes through the H13 compute cache** (the engine is
  pure and the eval sequence deterministic, so re-running a goal-seek is
  answered entirely from cache — tested by hit-count).
- **Apply writes through the normal input-change path** (autosave +
  history record it like a manual edit); the modal never mutates state
  directly.

## J6 — Replacement reserves + escrows (Run 5)

- **[FIN, pinned] One reserves dollar vector; the convention changes only
  WHERE the line sits.** $/unit/yr × the unit-mix count plus $/SF/yr ×
  commercial SF (lease-roll SF, else rentableSf), growing on the
  expense-growth clock in BOTH conventions — so toggling the convention
  never changes the dollars, only the placement. A set input whose basis
  is missing (per-unit with no unit mix; PSF with no SF) contributes
  nothing and warns — never a silent guess.
- **[FIN] below_noi (default): reserves are a capital cost after NOI**,
  like TI/LC — both cash-flow vectors, never DSCR / sizing / the exit
  cap basis. The lender-underwriting view is surfaced as the
  `underwrittenDscr` detail output (min DSCR on NOI − reserves), not by
  changing the deal's own DSCR.
- **[FIN] above_noi_underwritten: reserves sit inside opex for ALL
  NOI-derived metrics** — exit value, DSCR, sizing NOI, debt yield,
  break-evens. Category key `reservesUnderwritten` (the flat legacy
  `replacementReserves` opex field already owns that key and is
  untouched). Note: mixed-use component-level exit caps use component
  NOIs, which exclude this whole-property line.
- **[FIN] Escrows are pure cash timing, levered only**: funded at close
  (a use; the Equity source absorbs it), released at exit; never in the
  cost basis (it comes back), never in P&L, and never unlevered — an
  all-cash buyer posts no lender escrow. Sized on the FIRST OPERATING
  month's modeled taxes + insurance (× monthsOfTaxesAndInsurance) so
  every tax source — flat field, line items, reassessment — is honored
  from one place. Rejected: sizing on the raw input fields, which
  reassessment (H4) can replace.
- New reserves inputs and escrows join the Excel-export refusal list —
  the exported workbook has no below-NOI reserve or escrow rows, and a
  silently-diverging export is worse than a refusal.
- Housekeeping: vitest was collecting Playwright's e2e/smoke.spec.ts as
  a unit-test file (a failed suite with 0 failed tests, easy to misread
  as green); vitest.config.ts now excludes e2e/**.

## J5 — Floating-rate debt + rate cap (Run 5)

- **[FIN, pinned] Monthly rate = max(index(m), floor) + spread, capped at
  strike + spread while the cap is in force.** The cap strikes on the
  INDEX (market convention for SOFR caps); the borrower always pays the
  spread. In force means m ≤ capTermMonths; after expiry the rate is
  uncapped.
- **[FIN, pinned] The forward curve is a STEP function — no smoothing.**
  index(m) = the last curve point with month ≤ m; before the first point
  (or with no curve at all) the index is currentIndexPct. Rejected:
  linear interpolation between points — the curve rows are the user's
  assumption blocks, not samples of a continuous process, and steps are
  hand-checkable.
- **[FIN] Floating amortization reprices like an ARM**: each amortizing
  month's payment is recomputed at that month's rate over the REMAINING
  amortization; a flat vector degenerates to exactly the fixed
  level-payment schedule (tested to 1e-9). Rejected: freezing the payment
  at the initial rate — it silently un-floats the principal path.
- **[FIN] Sizing and the reported loan constant use the in-force rate at
  the loan's funding event** (month 1 at close; the takeout month + refi
  spread for developments). Rejected: a curve-average rate — a lender
  sizes at today's rate; the curve is the borrower's carry risk, and the
  strike-DSCR row is where that risk is surfaced.
- **[FIN] The cap premium is a levered financing cost at close** — it
  rides the loanFees statement row (never unlevered — rate protection is
  a capital-structure choice, like origination fees), joins uses and the
  cost basis, and the Equity source row absorbs it.
- **DSCR at the cap strike replaces the generic +200bps stress rows in
  the UI for capped floaters** (the +200bps repricing is a fiction the
  borrower already paid to escape while the cap runs); NOI-haircut rows
  stay. Uncapped floaters keep the full generic grid. Conditional
  `debt.rate` block + `dscrAtCapStrike` output only — fixed mode (the
  default) reproduces the J0 baseline exactly, and floating inputs are
  inert unless rateMode = "floating".
- **Seed-from-FRED is an explicit button** (like the millage lookup),
  reusing the existing /api/market/rates SOFR fetch — never an
  auto-fill. Floating-rate debt joins the Excel-export refusal list
  (a formula-live forward-curve engine is not exportable honestly).

## J4 — Junior tranche (Run 5)

- **[FIN, pinned] Ranking**: current-pay tranche interest is a below-NOI
  financing cost AFTER senior debt service and property capital costs
  (TI/LC, reno) and BEFORE the partnership AM fee and any equity
  distribution. At exit the tranche is repaid after senior payoff and
  before common equity, with a warning when proceeds don't cover it.
- **[FIN] A current-pay shortfall converts to PIK** (the shortfall joins
  the balance and compounds): the levered month is swept to zero, never
  negative. Rejected: hard default — a modeling engine shouldn't
  simulate an event of default; the PIK conversion is the standard
  intercreditor outcome and keeps the vectors well-defined.
- **[FIN] Funding matches the senior's event** (close for acquisitions,
  perm takeout for developments); interest starts the month AFTER
  funding in both shapes. Senior sizing is UNAFFECTED; fill-to-LTC
  sizing = max(0, pct × total cost basis − senior). The tranche and its
  origination fee ride the debtDraws/loanFees statement rows so the
  close-month identity holds unchanged.
- **Pref equity differs from mezz in LABELING only** here: senior-only
  ltv/ltc stay untouched for both kinds; combinedLtv/combinedLtc are new
  conditional detail outputs for both. Accrued mode compounds monthly at
  rate/12 (balance = amount × (1+r/12)^m — hand-tested).
- Conditional payload/statement keys only (juniorTranche block,
  juniorInterest/Balance/Payoff rows) — the J0 baseline is untouched.
  The tranche joins the Excel-export refusal list.

## J3 — GP fee economics (Run 5)

- **[FIN, pinned] The asset management fee is a PARTNERSHIP expense BELOW
  property NOI**: it reduces levered cash flow (and therefore levered/LP
  IRRs and the waterfall) but never NOI, DSCR, unlevered flows, or lender
  metrics. Rejected: treating it as opex — lenders don't underwrite a
  sponsor's AM fee, and folding it into NOI would corrupt DSCR, debt
  yield, cap-rate math, and every comp. Basis options: % of EGI
  (monthly, on the engine's own EGI vector) or % of committed equity
  (annual pct / 12 on the equity at close).
- **[FIN] Acquisition and developer fees are USES capitalized into basis**
  (they already were — F2/H-run behavior); J3 adds the REPORTING that all
  three streams are paid TO the GP. Waterfall distributions stay on
  contributed-capital promote math (fees never run through the
  waterfall); GP total compensation = fees + promote + pro-rata net.
- **The gpEconomics block activates on the AM fee (new input) or an
  acquisition fee — never on the developer fee alone**: the pre-J3
  engine default (developerFeePct 0.04) would otherwise put the block on
  every Run-4 development deal, breaking the baseline. The developer fee
  reports inside the block once another stream fires. Similarly, the
  spec's "developerFeePct default 0" is NOT adopted — the Run-1 default
  (0.04) is load-bearing for existing outputs, and compatibility is
  absolute.
- The AM fee joins the Excel-export refusal list (levered-only
  partnership flows have no cell in the property model).

## J2 — Loss-to-lease burn-off (Run 5)

- **[FIN] Analytic expected-value blend, no per-unit simulation**: because
  in-place and market rents grow on the SAME clock, a unit turned in any
  month earns `inPlace + capture × gap` (× growth) thereafter, so the
  blend is closed-form: in-place share `s(om) = (1 − turnover/12)^(om−1)`.
  Month 1 is fully in-place — the month-1 GPR equals the no-LTL baseline
  by construction. Rejected: per-unit simulation (noise for zero extra
  information under identical growth clocks).
- **[FIN] Reno supersedes LTL**: renovated units EXIT the pool at reno
  START; delivered units re-base to FULL market (+ the J1 premium) —
  capture doesn't apply to a renovated unit.
- LTL activates per type only when BOTH rents and a turnover are present
  (Run 4 effectively prices in-place from day one — documented
  interaction). The statement identity stays on SCHEDULED GPR; the
  market-GPR / less-LTL build is a conditional DISPLAY block (baseline
  safe), with market GPR covering active types only so the line never
  shows un-modeled gap. LTL joins the Excel-export refusal list.

## J1 — Renovation program (Run 5)

- **[FIN] Reno downtime is IN ADDITION to natural vacancy, no overlap
  credit**: offline units lose 100% of their rent while the REST of the
  pool still bears the full vacancyPct —
  `vacancy(m) = (GPR − offlineRent)·vacancyPct + offlineRent`. Rejected:
  absorbing downtime inside the vacancy allowance (less conservative, and
  makes small programs invisible). Credit loss was re-expressed as
  `(GPR − vacancy)·clp`, algebraically identical to Run 4 at defaults.
- **[FIN] The premium joins the rent basis and grows on the SAME deal
  anniversary clock as rent.** Rejected: growing each premium from its
  unit's delivery date — a second clock per cohort that nothing else in
  the engine uses, for pennies of precision.
- **[FIN] Capex lands per unit in its START month, below NOI** (like
  TI/LC), and the FULL budget joins total_cost_basis (the yield-on-cost
  denominator) under both funding modes — the value-add convention.
- **Funding modes are pure cash TIMING**: equity_at_close puts the whole
  budget in uses at close (escrow view — equity up, levered[0] down);
  operating_cash draws both vectors as incurred with a warning when
  cumulative operating cash goes negative (never silently re-sequenced).
  Total levered dollars are identical across modes.
- Statement keys (renovationCapex row, renovation progress block) are
  CONDITIONAL — absent without a program, so the J0 baseline is
  untouched. The program joins the Excel-export refusal list.
- stabilized_annual_noi (debt sizing) stays IN-PLACE (pre-reno) — lenders
  size on in-place; the exit already values delivered premiums through
  the forward-12 NOI window.

## I14 — Lease-engine performance guard (Run 4)

- Two budgets, both hard: a 2-second wall-clock cap on a 50-lease /
  10-year / mixed-recovery / rollover-heavy compute (measured after a
  warm-up run so imports don't count), and a CALL-COUNT budget —
  build_lease_income must run ≤ 4 times per compute (currently 2: the
  extended main build + the stabilized window), because a regression
  that re-evaluates per lease or per month explodes the call count long
  before a CI clock notices. Policy in the test text itself: fix the hot
  spot, never raise the budget.
- Measured at introduction: ~0.01–0.02s locally for the full 50-lease
  compute — no hot spot existed, nothing was optimized.

## I13 — Batch deck export (Run 4)

- One title slide (firm branding, count, date) + one H12-style slide per
  computable deal, rendered by the SAME slide function the single deck
  uses — no second layout to drift. Slide order = the id order the client
  sends, which is the pipeline's current sort.
- Incomputable deals SKIP with their names listed BOTH on the title slide
  (the artifact is self-describing when forwarded) and in the
  X-Deck-Skipped header (the UI can toast it). All-incomputable → 422,
  never an empty deck. Hard cap 20 deals per file, rejected before any
  compute runs.

## I12 — History diff view (Run 4)

- **Tables diff BY ROW KEY** (unitMix → unitType, commercialLeases →
  suiteId, opexLineItems → category, waterfallTiers → position), so
  reordering rows is NOT a change; duplicate keys disambiguate with a
  tick suffix rather than dropping rows. Scalars group by schema section
  with per-type formatting; the quickScreen blob diffs one level in.
- **The restore preview diffs against the LAST SAVED deal state** — that
  is literally what restore replaces (unsaved keystrokes autosave within
  seconds); diffing against in-memory form state would preview a
  transaction that doesn't exist. Compare mode always orders the older
  snapshot as the before side regardless of pick order.
- The snapshot LIST endpoint stays metadata-only; full inputs come from
  the new single-snapshot GET on demand (diffing is client-side over the
  pure snapshotDiff lib).

## I11 — Comps hygiene + map (Run 4)

- **Duplicate = same normalized address AND date within ±30 days**
  (lowercased, punctuation stripped, street suffixes abbreviated).
  Duplicates flag in the import PREVIEW using the suggested mapping
  (best-effort — no confirmed mapping exists yet) and default to SKIP
  (keep the existing comp); unchecking imports the row anyway. "Merge"
  is deliberately skip-or-import — silently overwriting an existing
  comp's fields from a CSV would destroy manual curation.
- **Staleness = 12 months** (COMP_STALE_MONTHS): amber age chips on
  comp rows, and benchmark flag explanations append "N of the comps are
  older than 12 months" so a stale median can't masquerade as current.
- **The map is a schematic lat/lon scatter, not tiled** — map tiles mean
  external requests and a dependency; positions normalize to the comp
  set's bounding box and the caption says so. Comps that fail to geocode
  (or have no address) are SKIPPED WITH A WARNING naming them — silently
  missing pins would misrepresent the set.

## I9 — Commercial extraction breadth (Run 4)

- **Header matching gained COLUMN RESERVATION**: exact alias claims beat
  substring claims, and a claimed column can't be claimed twice. This
  fixed two latent bugs the old goldens had blessed — unitType matching
  the Unit/Lease-Type column, and marketRentMonthly duplicating a single
  "Rent" column — so those two goldens were regenerated as bug fixes
  (diffs inspected line by line first; yardi/realpage byte-identical).
  Also: no bare "rent/sf" alias (normalizes to "rentsf" and would swallow
  every plain SF header); the header-inside-alias direction requires
  len ≥ 4.
- **Rent magnitude heuristic**: a "monthly" rent whose implied annual $/SF
  exceeds $250 is read as ANNUAL, always with a per-row warning naming
  the value — never silently. If the $/SF column exists it wins outright.
- **Month-year-only lease END dates read as the LAST day of the month** (a
  lease expiring "Jun 2027" runs through June); start dates keep the
  first-of-month read. MTM terms parse as no expiry with a named warning
  suggesting rollover assumptions instead.
- **Stacking-plan rows with SF but no rent propose at $0/SF with a
  fill-in warning** rather than vanishing — losing a tenancy silently is
  worse than an obviously-wrong zero. Combined suite ranges stay ONE
  lease with a split-manually warning (per-suite SF is unknowable).
- New keys on parsed rows (floor, annualRent, rentPsfAnnual,
  rentDerivedFrom, mtm, monthYearEndDate) appear only when their source
  column/flag exists, so pre-I9 fixtures produce byte-identical rows.

## I8 — Per-lease drill-down (Run 4)

- The per-lease slices are accumulated IN the same loop that builds the
  property vectors — never recomputed — so `Σ slices == property` is an
  identity, and it's tested as one. Slices key by suiteId (tenant, then
  index as fallbacks) and expose scheduled rent, free rent, downtime
  loss, recoveries, TI/LC, and rollover events per generation.
- The `?detail=true` payload gained `statement.leases.perLease` — a pure
  EXPANSION of the I0 baseline (verified: the only diff on every lease
  case was the new key, zero value changes) — so the baseline was
  regenerated under the expansion rule.
- Slice vectors are trimmed to the hold horizon in the engine (the
  extended forward window is an exit-valuation internality); the annual
  view and CSV are client-side summing only (leaseSlice.ts, unit-tested).

## I7 — Widened native Excel export (Run 4)

- **Expenses block is formula-live per line**: each row carries basis,
  raw amount, growth, and a RESOLVING formula (`amount × units` for
  per_unit, `× SF` for psf, falling back to ×1 exactly like the engine's
  warning fallback); the statement's fixed-opex cell SUMPRODUCTs over the
  block. pct_of_egi lines fold into the fee cell. Recoverable flags are
  ANNOTATIONS — recoveries need lease-level modeling, which the export
  still refuses. Non-ad-valorem (I5) exports as a block row with its own
  growth column.
- **Development mechanics mirror the engine cell-for-cell**: S-curve
  weights as LITERAL values on the Draws sheet (the cosine ogive isn't
  worth mirroring); costs, equity-first split (MIN/SUM prior-equity
  recursion), first-draw fee, and capitalized interest as formulas over
  them; carry months sweep NOI against the balance (MAX(0, bal+int−NOI),
  levered CF pinned 0); the perm takeout is the app-sized VALUE with the
  refi delta − costs hitting the takeout month; IO→amortizing perm
  schedule on the perm clock. Sold-before-stabilization developments are
  the one remaining dev refusal (no takeout exists to model).
- **Debt tab is a presentation view tied to Model by reference** — one
  schedule, two renderings, no second source of truth.
- Export parity corpus doubled: opex-detail acquisition (per_unit
  resolution + separate-growth non-ad-valorem line) and an S-curve
  development — 14 outputs each, zero deltas at introduction. Found and
  fixed in the process: acquisition yieldOnCost must divide by basis +
  loan fees (the engine's total_cost_basis), not basis alone.

## I6 — Comp normalization (Run 4)

- **Rent flags compare in tiers, best evidence first**: (1) unit-type
  weighted — per-bedroom medians blended by the SUBJECT's unit-count
  distribution; usable only when EVERY weighted subject class has ≥3
  typed comps (a half-covered mix would silently skew the blend, so it
  disqualifies the tier rather than partially applying); (2) $/SF —
  subject rent/avg-unit-SF vs the comp rent/SF median when both sides
  have SF; (3) pooled median with an explicit "low-confidence comparison"
  note. The minimum-3 rule applies PER TIER; thresholds (+10% caution /
  +20% warning) are unchanged at every tier. The explanation always
  states which basis fired.
- Sale-comp flags keep the cap-rate comparison as the signal; the
  explanation now carries the asset-class-appropriate price basis as
  context — median $/unit for multifamily/mixed, $/SF otherwise — when ≥3
  priced comps support it.
- Subject gains avgUnitSf (unit-count-weighted Avg SF), derived
  identically on the frontend and the memo path.

## I5 — Non-ad-valorem assessments (Run 4)

- **[FIN] Non-ad-valorem assessments are a separate fixed line** with its
  own growth clock (default = expense growth), NEVER reset by
  reassessment — special assessments (solid waste, drainage, CDD bonds)
  are flat charges that don't reprice at sale. Recoverable by DEFAULT
  (they bill like taxes and sit in every NNN pool); the flag can turn it
  off. Statement category key: nonAdValorem.
- **[FIN] Derived millage now uses adValoremTaxes / taxableValue** — the
  H4 derivation divided TOTAL taxes by taxable value, silently folding
  non-ad-valorem charges into the millage and overstating every
  reassessment projection. When the PA payload has no split, the old
  total-based derivation remains as the fallback WITH an explicit note.
- The reassessment projection is now `price × ratio × millage (ad
  valorem) + carried non-ad-valorem = projected total`, shown as the
  split in the lookup panel.
- nonAdValoremTaxes defaults 0 → no line, no pool change; I0 baseline
  pins Run-3 behavior.

## I4 — Mixed-use opex allocation basis (Run 4)

- **[FIN] Three bases** for the commercial share of shared opex:
  revenue_share_y1 (default = Run-3's frozen year-1 scheduled-revenue
  share), sf (commercial SF vs unit-mix SF — one scalar), and
  revenue_share_annual (the y1 ratio recomputed per calendar year, gross
  scheduled revenue on both sides so occupancy noise doesn't move the
  split).
- **Under the DEFAULT basis, component reporting keeps Run-3's monthly-EGI
  split** (the pool uses y1 revenue share, reporting uses EGI — the
  legacy pairing), because changing the reporting split at defaults would
  move component NOIs on existing deals. The sf and revenue_share_annual
  bases drive BOTH the pool and the reporting split, per the spec's
  internal-consistency requirement. Component NOIs sum to blended under
  every basis by construction (the allocation only redistributes fixed
  opex).
- sf basis with unknown SF on either side (no lease SF or no unit-mix Avg
  SF) falls back to the default basis with an explicit warning — never a
  silent half-basis.

## I3 — Base-year gross-up (Run 4)

- **[FIN] Gross-up applies to base_year_stop leases only** (the
  office-standard clause it implements): both the base year and every
  comparison year come from the ADJUSTED pool `R_adj(m) = fixed(m) +
  variable(m) × max(1, grossUpTo / occ(year))`. NNN keeps billing the raw
  pool — NNN tenants pay actual expenses; grossing them up would invent
  dollars. The ratio floors at 1 (never gross DOWN below actuals).
- **[FIN] Occupancy basis is the COMMERCIAL occupied-SF share** (contract
  months full, downtime months at p, speculative terms full) in both pure
  and mixed deals. Rejected: blended mixed-use occupancy — residential
  vacancy must not gross up commercial CAM; the clause references the
  building's commercial occupancy. Occupancy is averaged per calendar
  year; pre-epoch base years reuse year 1's occupancy (consistent with the
  pool's backward extrapolation).
- Variable/fixed split needs expense-line detail: category defaults
  (utilities, repairs_maintenance variable; taxes, insurance, payroll,
  G&A, management fixed) with a per-line variableWithOccupancy override;
  reassessed taxes are never variable. Simple-expense mode has no split —
  grossUpToPct is ignored with an explicit warning, and the input is
  hidden unless opexLineItems exist.
- The occupancy pre-pass is an extracted helper with a DRIFT-GUARD test
  asserting it matches the main loop's occupancy vector exactly.
- grossUpToPct defaults null (off); the I0 baseline pins Run-3 behavior.

## I2 — Rollover refinements (Run 4)

- **[FIN] Split TI/LC timing is OPT-IN** (reletCapitalAtCommencement,
  default false). The refinement — renewal capital at expiry+1, re-let
  capital at commencement (expiry + downtime + 1) as two
  probability-weighted entries — changes cash TIMING whenever downtime > 0,
  and Run 4's compatibility rule is absolute, so the default keeps Run-3's
  single blended entry at expiry+1. A re-let commencement past the analysis
  end simply never incurs its capital (the model doesn't know about
  post-horizon cash). Rejected: making the new timing the default with a
  legacy flag — that silently moves every existing deal's cash.
- **[FIN] Renewal spread (renewalRentPsfDiscountPct, default 1.0)**:
  renewal-path rent = discount × that generation's market rent; the re-let
  path always pays market. The spread applies AT EACH renewal event and
  never compounds through generations — every generation re-derives from
  the market track, not the prior generation's realized rent (explicit in
  code). Downtime months collect p × discounted rent; scheduled (GPR) is
  the probability blend so the statement identities hold; downtime loss
  stays (1−p) × market.
- **[FIN] LC bases follow the contract each side signs**: renewal LC = pct
  × (discount × market) × term; re-let LC = pct × market × term. TI is
  $psf and unaffected by the spread.

## I1 — CAM admin fee + management recoverability (Run 4)

- **[FIN] The admin fee is a BILLING markup on pool-based recoveries**:
  `rec(m) ×= (1 + adminFeePct)` for NNN and base-year-stop leases only.
  fixed_psf is a stated contract amount and gross recovers nothing, so
  neither can carry a markup. For base-year stops the year comparison
  happens on RAW pool amounts and the markup applies to the billed delta —
  marking up the pool before comparison would distort the stop itself.
- **[FIN] Management-fee pool contribution is the fee on PRE-RECOVERY EGI**
  (collected base rent net of credit loss + other income), because the fee
  is EGI-based and EGI includes recoveries — the naive definition is
  circular. Rejected: fixed-point iteration (converges fast but makes the
  engine non-deterministic in iteration count and impossible to mirror in
  a formula workbook). The fee EXPENSE itself stays on full EGI (Run-0 M6
  convention). The optional cap (mgmtRecoveryCapPct) is % of the same
  pre-recovery EGI for the same reason.
- The augmented pool feeds `_annual_recoverable_by_calendar_year`
  directly, so base-year stops see mgmt dollars in BOTH the base and
  comparison years — no spurious step. Accepted simplification: pre-epoch
  base years de-grow the whole pool (incl. the mgmt component) at the
  expense growth rate.
- All three inputs default to Run-3 behavior exactly (adminFeePct 0,
  mgmtFeeRecoverable false, cap null); the I0 baseline pins it.

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
  calendar everywhere). *(Superseded — analysisStartDate, see "Engine audit
  fixes".)*
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
  *(Superseded — see "Engine audit fixes": LTC now includes financing.)*
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
