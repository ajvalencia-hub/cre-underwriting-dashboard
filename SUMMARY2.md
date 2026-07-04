# Autonomous Build Run 2 — Summary

Nine features (G1–G9) on top of Run 1: engine conventions as explicit
options, the period-level cash-flow statement, native sensitivity, scenario
comparison + tornado, rent-roll-to-unit-mix wiring, hold/refi analysis, deal
export/import, memo charts + PDF, and a Playwright smoke. Final state:
**215 backend tests + 64 frontend unit tests + 1 e2e happy path green, tsc
and oxlint clean, parity clean** (every mapped output still matches the
LibreOffice-recalculated Excel path with zero deltas — the corpus pins the
Run-1 defaults, which every new convention preserves when unset).

One commit per feature (G1..G9 prefixes). Two real defects were found and
fixed by the run's own verification: an off-by-one in XIRR flow dating that
read as a spurious 45bp convention gap, and LibreOffice Writer crashing with
0xC0000409 when its scratch profile path exceeded Windows MAX_PATH (Calc's
shallower profile tree had always fit — diagnosed empirically, fixed by
shortening the scratch names).

## Formulas added, in plain algebra

### G1 — American waterfall (`proforma/equity.py`)
- Ledgers per partner: unreturned capital C and accrued unpaid pref A.
- Monthly accrual (compounded): A += (C + A) * r_p, r_p = (1+pref)^(1/12)-1.
- Each distribution, strictly in order: (1) accrued pref pro rata by A;
  (2) return of capital pro rata by C; (3) the promote stack, tier-1 splits
  applying immediately (its hurdle is deemed met by pref + full ROC);
  higher tier hurdles stay LP-IRR-measured with the Run-1 closed form
  (fill = -NPV_h(LP flows) * (1+h_m)^m / lpSplit).

### G1 — GP catch-up (both styles)
- Replaces the pref-to-first-hurdle band. Profits measured as nominal net
  positions: P_lp = sum(lpFlows), P_gp = sum(gpFlows).
- Band size x at split (1-c, c) solves: P_gp + c*x = p * (P_lp + P_gp + x)
  => x = (p*(P_lp+P_gp) - P_gp) / (c - p), taken only while x > 0 and
  total capital is back (P_lp + P_gp >= 0). c <= p is unreachable: warned
  and skipped. Full catch-up (c = 1) lands the GP at exactly p of ALL
  profit.

### G1 — XIRR convention (`returns.py` + `timeline.py`)
- Flows dated on a fixed calendar: index 0 = 2026-01-01 (documented epoch);
  operating month m settles at the END of the calendar month at offset m-1
  (month 12 = Dec 31 = exactly one year).
- r solves sum_k CF_k / (1+r)^(days_k/365) = 0 (Actual/365, Excel
  convention, Newton + bisection). periodic_monthly stays the default.

### G2 — statement identities (hold by construction, tested per month)
- egi = gpr - vacancyLoss - creditLoss + otherIncome
- noi = egi - opexTotal;  opexTotal = sum(fixedByCategory) + managementFee
- levered = noi - debtService + debtDraws - costs - loanFees
  + saleProceedsNet;  lp + gp = levered per period.

### G4 — tornado perturbations (`tornado_service.py`)
- One driver at a time through engine.compute: rent, cost (hard costs or
  purchase price by deal type), opex (every line + mgmt fee), vacancy at
  ±10% RELATIVE; interest rate and exit cap at ±50bps ABSOLUTE. Rent
  perturbs the deal's actual GPR source (unit-mix rents > per-SF > flat).
- impact = max(|metric(up) - base|, |metric(down) - base|), bars sorted
  descending; chart geometry scales the widest swing to the plot edges.

### G5 — unit-mix grouping (`rent_roll_parser.propose_unit_mix`)
- Group by unit-type label, UNLESS two labels parse to the same bed/bath
  ('1BR/1BA' vs '1x1' vs '1 Bed 1 Bath') — then group by the parsed
  bed/bath key with a warning. Per group: count, avg SF, avg in-place rent
  (occupied rows only), avg market rent, occupiedCount/occupancyPct,
  sourceRowCount (provenance).

### G6 — refi pricing and the hold sweep (`engine.py`, `proforma/hold.py`)
- Development perm takeout = the stabilization refinance:
  permRate = constructionRate + refiRateSpreadPct; refiCosts =
  refiCostsPct * permLoan, deducted from equity at takeout. Sizing,
  amortization, DSCR metrics, and the stress grid all price at permRate.
- Hold sweep: full engine re-compute at each whole exit year from
  stabilization+1 (year 1 when stabilized at close) through the modeled
  hold. Refi-vs-sale: sale leg computes with hold = stabilizationMonth/12;
  refi leg is the base modeled compute; cashOut = sizedLoan - carry
  balance at takeout.

## DECISIONS.md deltas (Run 2, inlined)

- **[FIN] American waterfall = ledger + strict sequencing** (monthly-
  compounded pref on capital+accrued; pref → ROC → promote with tier-1
  immediate). Rejected: annual compounding; simple pref; IRR-measured
  tier-1 in American (with pari passu capital and a common pref rate it
  makes the styles algebraically identical — a no-op option).
- **[FIN] Catch-up counts the pref as profit** (nominal net positions).
  Rejected: excluding the pref (makes the target vacuously satisfied at
  zero — a dead band); time-valued profit bases (no standard reference).
- **[FIN] XIRR dates from a fixed 2026-01-01 epoch, Actual/365.** Rejected:
  today()-based dating (non-reproducible); an analysisStartDate input (a
  date field for bp-level noise).
- **[FIN] The perm takeout IS the stabilization refi**, priced with an
  explicit spread + costs (defaults 0/1% — parity pins zero). Rejected: a
  second refi event inside the hold; a standalone perm-rate input (term
  sheets quote spreads).
- **[FIN] Hold sweep = whole exit years from stabilization+1 through the
  modeled hold**; sale-at-stabilization uses fractional hold years.
- **Deal bundles carry no documents/extractions** (they're global, not
  deal-scoped) **and no template binaries** (firm IP; named placeholders
  instead). Import never merges.
- **Full scenarios no longer require a template** (native-engine era);
  template/mapping ids are validated when provided, as a pair.

## BLOCKED.md delta

Nothing new. The two pre-existing notes stand (ANTHROPIC_API_KEY and
FRED_API_KEY unset — both degrade by design). The Run-1 LibreOffice item
remains cleared.

## Manual QA checklist (ordered by risk)

1. Set waterfallStyle=american + a catch-up % on a real promote deal and
   compare LP/GP IRRs against european — confirm the deltas match your
   term sheet's reading of the two structures.
2. Enter a development deal with refiRateSpreadPct > 0 and verify the debt
   panel's governing constraint, DSCR, and stress grid move the way your
   lender model says they should.
3. Compute (native) → Cash Flow tab: spot-check one year's NOI and levered
   CF against the annual CSV export and the sidebar scalars.
4. Run the hold sweep on a development deal and confirm the modeled-hold
   row equals the base compute; sanity-check the refi-vs-sale fork's
   cash-out against loan sizing minus the construction balance.
5. Upload a real rent roll → confirm the proposed unit mix groups
   sensibly, then apply with an existing unit mix present and verify the
   merge/replace choice does what it says.
6. Native sensitivity 25×25 on exit cap × rent growth; save to a scenario;
   generate that scenario's memo and confirm the heatmap matches the grid.
7. Generate a memo as PDF (LibreOffice installed) and skim every section —
   charts render, numbers match the scenario, conventions footnoted.
8. Export a deal, import it back, and confirm scenarios + saved sensitivity
   arrived and template warnings listed everything you need to re-link.
9. Compare 3 scenarios of one deal — verify only differing inputs show,
   and best-value highlighting never marks an ambiguous metric (LTV, cap).
10. Run `npm run e2e` and `python -m tests.parity.run` on a fresh clone —
    both must pass with zero local setup beyond the README.
