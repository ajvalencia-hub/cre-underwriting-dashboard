# Run 5 (J0–J17) — Summary

Run 5 added a value-add income layer, a full capital stack, three analytics
tools, and the workflow/packaging features that make the app a self-hostable
book-of-record. The absolute compatibility rule held: **every new engine
input defaults to reproducing Run-4 outputs byte-for-byte** (1e-9), pinned by
`backend/tests/regression/` across six fixtures — now including a
value-add-shaped multifamily deal added in J0.

Final gate state: **461 backend tests**, **108 vitest**, parity clean (31
outputs, 0 delta), regression baseline green, Playwright smoke green, `tsc`
+ `oxlint` + `vite build` clean.

---

## Before / after algebra — J1–J6 (the behavior-changing features)

Each is written so that at its default the "after" collapses to the "before".

### J1 — Renovation program

- **Before:** `vacancy(m) = gpr(m)·(1 − occ)`; `gpr(m)` = scheduled rent.
- **After:** offline (in-reno) units lose 100% of rent *in addition to* the
  general vacancy on the rest of the pool, and delivered units earn a
  premium:
  - `gpr(m) = scheduled(m) + premium(m)`
  - `vacancy(m) = (gpr(m) − offline(m))·(1 − occ) + offline(m)`
  - credit loss re-expressed as `(gpr − vacancy)·clp` (identical at defaults).
  - Reno capex hits the cost basis always; funded by equity-at-close (whole
    budget a use at close) or operating cash (drawn as incurred, shortfall
    warned).
- **Default:** no `renovationProgram` section → `offline = premium = capex =
  0` → every term above is the "before".

### J2 — Loss-to-lease burn-off

- **Before:** GPR = scheduled in-place rent, flat blend.
- **After:** analytic turnover blend `s(m) = (1 − turnover/12)^(m−1)`
  (month 1 fully in-place); turned units earn `inPlace + capture·(market −
  inPlace)`; uplift joins scheduled rent. Reno-delivered units supersede LTL
  (re-based to full market + premium). Display block only — the levered
  identity stays on scheduled GPR.
- **Default:** no per-unit `annualTurnoverPct` → uplift 0 → GPR unchanged.

### J3 — GP fee economics

- **Before:** GP receives its pro-rata equity distributions + promote.
- **After:** an **asset-management fee** is a partnership expense **below
  NOI**, levered only — `levered(m) −= amFeePct·EGI(m)` (or
  `amFeePct/12·initialEquity`); it never touches NOI, DSCR, unlevered, or
  lender metrics. A `gpEconomics` block splits acquisition/developer/AM fees
  + promote from pro-rata.
- **Default:** `assetMgmtFeePct = 0` and no acquisition fee → no fee vector,
  no `gpEconomics` block (gated so the pre-existing dev developer-fee default
  of 0.04 never activates it).

### J4 — Mezzanine / preferred-equity tranche

- **Before:** `equity(0) = basis − seniorLoan + loanFees`; exit =
  `... + saleProceedsNet`.
- **After:** a junior tranche funds at the senior's event and reduces common
  equity: `equity(0) −= (tranche − trancheFee)`. Current-pay interest is a
  below-NOI cost after senior DS, before AM fee/equity; a shortfall converts
  to PIK (month swept to 0, balance grows). At exit `levered(total) −=
  balance` after senior payoff, before equity. `combinedLtv/Ltc` reported;
  senior ltv/ltc untouched.
- **Default:** `juniorTrancheKind = "none"` → no tranche, no combined outputs.

### J5 — Floating-rate debt + rate cap

- **Before:** fixed `rate` for all months; DS on a level schedule.
- **After (rateMode = floating):** `rate(m) = max(index(m), floor) + spread`,
  capped at `strike + spread` while `m ≤ capTerm`; `index(m)` = the last
  forward-curve point with `month ≤ m` (step function). Amortization reprices
  monthly (ARM); construction interest, the carry sweep, and the perm takeout
  all honor the vector. Cap premium is a levered close cost.
- **Default:** `rateMode` absent/"fixed" → `rate_vec = None` → the fixed
  level schedule, unchanged; floating inputs inert.

### J6 — Replacement reserves + escrows

- **Before:** reserves, if any, are the flat `replacementReserves` opex line.
- **After:** per-unit ($/unit/yr) and PSF reserves as one growing vector; the
  `reservesConvention` toggle changes only placement:
  - `below_noi` (default): capital cost after NOI (both cash vectors); DSCR
    stays on NOI; `underwrittenDscr = min NOI−reserves / DS` reported.
  - `above_noi_underwritten`: folded into opex for **all** NOI-derived
    metrics (exit value, DSCR, sizing).
  - Escrows: `monthsOfTaxesAndInsurance × (first-operating-month taxes +
    insurance)` — `levered(0) −= E`, `levered(total) += E`; pure timing,
    levered only, never in the basis or P&L.
- **Default:** all reserve/escrow inputs 0 → no vectors, no new keys.

---

## Feature ledger (J7–J17)

| Feature | Shape |
|---|---|
| J7 Goal-seek | `POST /api/compute/goal-seek`; bracket scan (12 pts) + bisection, no monotonicity assumption, metric-typed tolerances, typed no-solution, full compute-cache reuse; sidebar ◎ modal |
| J8 Monte Carlo | `POST /api/compute/monte-carlo` (job + poll); ≤6 drivers, Gaussian-copula correlations via numpy Cholesky, seeded, P5–P95 + tail probs + histogram; Risk tab; scenario `monte_carlo` column; memo risk section |
| J9 Break-evens | Analytic per-year occupancy + rent-level break-evens on statement vectors; null+note when impossible; statement footer + year-1 sidebar |
| J10 OM wizard | Upload → confirm types → extract → existing review gate → `POST /api/deals/from-extraction` (server-side ack gate, provenance rows); resumable draft on `inputs._omWizard` |
| J11 Critical dates | `inputs.criticalDates`; pipeline deadline strip, header chips, share section; pure date lib |
| J12 File cabinet | Document `deal_id`; attachments (any type, size cap, PDF text preview) + `DealNote` timeline; bundle lists attachments by hash, carries notes |
| J13 Global search | `GET /api/search`; SQLite LIKE + indexes (migration), tenant scan; Cmd+K palette with pure ring-nav helper |
| J14 IC deck | `GET /api/deals/{id}/ic-deck.pptx`; 8 slides, clean skip list (X-Deck-Skipped); `investmentThesis` field; MC-or-tornado risk slide |
| J15 Portfolio | `GET /api/portfolio` (+ CSV); equity-weighted blends from live compute, uncomputable deals excluded+listed |
| J16 Docker + backup | Multi-stage image (SPA + LibreOffice/Tesseract/Poppler), compose + volume; SQLite online-backup rotation (7 daily / 4 weekly), admin endpoints, CI docker job |

---

## DECISIONS.md deltas (Run 5)

New `[FIN]`-tagged convention blocks: **J1** (reno downtime additive, credit-
loss re-expression, funding modes), **J2** (analytic turnover blend, reno
supersedes LTL, display-only), **J3** (AM fee below NOI levered-only,
gpEconomics gating), **J4** (junior ranking, PIK conversion, fill-to-LTC,
pref = labeling), **J5** (max/floor/cap rate rule, step curve no-smoothing,
ARM repricing, sizing at in-force rate, cap premium levered), **J6**
(one vector / placement-only convention, escrow timing sizing). Plus
non-`[FIN]` blocks for J7–J16 (goal-seek method, Monte Carlo copula + numpy
justification, break-even response model, wizard gate/provenance, critical
dates storage, file-cabinet generalization, search LIKE-not-FTS, IC-deck skip
rules, portfolio equity weighting + stale exclusion, Docker/backup safety).

## BLOCKED.md deltas (Run 5)

**None.** No feature hit the compatibility wall or a hard dependency block.
The pre-existing optional-key notes (`ANTHROPIC_API_KEY`, `FRED_API_KEY`
unset → graceful degradation by design) are unchanged. numpy was permitted
for J8 because it is already a transitive dependency (via matplotlib,
verified in `pip freeze`; not added to `requirements.txt`), so the stdlib
Iman–Conover fallback was not needed.

---

## Excel-export refusal list (complete, as of Run 5)

The native formula-live Excel export (`unsupported_features`) refuses — with
a named blocker, never a wrong formula — any deal using:

1. Commercial lease-level rent rolls (escalations / recoveries / rollover)
2. Promote waterfall tiers
3. XIRR date-based IRR convention
4. Reassessed property taxes (separate tax growth clock)
5. **Renovation program (value-add unit sequencing)** — J1
6. **Loss-to-lease burn-off (turnover blend)** — J2
7. **Asset management fee (partnership expense below NOI)** — J3
8. **Junior tranche (mezzanine / preferred equity)** — J4
9. **Floating-rate debt (forward curve, floor, rate cap)** — J5
10. **Per-unit / PSF replacement reserves (convention-dependent placement)** — J6
11. **Tax & insurance escrows (close/exit cash timing)** — J6
12. Development sold before stabilization (no permanent takeout occurs)

Items 5–11 are the Run-5 additions. Each remains fully supported in the
native engine, the cash-flow statement, the memo, and the IC deck — the
refusal is specific to the formula-mirrored Excel workbook, where reproducing
these behaviors as live cell formulas honestly is not feasible.

---

## Manual QA checklist — ordered by risk

Highest-risk first (financial correctness), then workflow, then packaging.

1. **Compatibility (critical).** With all J1–J6 inputs at defaults, confirm a
   handful of saved deals produce identical outputs to Run 4 — the regression
   baseline enforces this, but spot-check the sidebar IRR/multiple on a real
   deal after upgrading.
2. **J5 floating debt (highest new-math risk).** Enter a forward curve with a
   mid-hold step and a rate cap; verify (a) DS steps on the curve month, not
   before; (b) the "At cap strike" DSCR row replaces the +200bps rows; (c) a
   fixed-mode deal is unchanged. Cross-check the sparkline against the curve.
3. **J4 tranche + J3 fees + J6 reserves interaction.** On one deal, stack a
   mezz tranche, an AM fee, and below-NOI reserves; confirm the levered
   month-1 identity (`NOI − seniorDS − juniorInt − AMfee − reserves`) and that
   NOI/DSCR ignore the AM fee and reserves. Flip reserves to
   `above_noi_underwritten` and confirm exit value drops but month-1 levered
   cash is unchanged.
4. **J6 escrow round-trip.** Set escrow months; confirm total levered dollars
   are unchanged vs no escrow, IRR is lower, and unlevered is untouched.
5. **J8 Monte Carlo determinism.** Run twice with the same seed → identical
   percentiles. Add a correlation and confirm the run still completes;
   jointly-inconsistent correlations should 400, not silently "fix".
6. **J7 goal-seek.** Solve purchase price for a target levered IRR; Apply and
   confirm the value writes through to the form + history. Try an unreachable
   target → typed no-solution with the scanned range.
7. **J9 break-evens.** On a flat deal, confirm year-1 break-even occupancy
   equals the quick-screen break-even ratio; an over-levered deal shows null +
   note, not a >100% number.
8. **J10 wizard.** Run Yardi RR + T-12 → deal; confirm the review gate blocks
   on a failing cross-check until acknowledged, provenance rows land in
   `_provenance`, and an abandoned draft is resumable then deletable.
9. **J14 IC deck.** Full deal → 8 slides; a sparse all-equity deal → reduced
   deck with the skip list in `X-Deck-Skipped`.
10. **J15 portfolio.** Add a half-entered deal; confirm it's excluded + listed
    and doesn't move the blended IRR; check the CSV footer.
11. **J11–J13 workflow surfaces.** Critical-date chip colors (overdue red),
    file upload/preview/download + note edit, and Cmd+K search grouping +
    keyboard nav.
12. **J16 Docker (packaging).** `docker compose up --build` → app on :8000;
    create a deal, `POST /api/admin/backups/run`, then restore and restart;
    confirm data persists across a `docker compose down && up` (named volume).
