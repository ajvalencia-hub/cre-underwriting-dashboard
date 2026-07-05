# SUMMARY3 — Autonomous Build Run 3 (H1–H14)

Fourteen features, one commit each (H1..H14), all gates green at every
step: pytest (302), vitest (86), tsc -b, oxlint, `python -m
tests.parity.run` (now three-way, zero deltas), Playwright e2e (2
journeys). No BLOCKED.md was needed.

---

## 1. The formulas, in plain algebra

Notation: `m` = month index (1-based from the analysis start; statement
index 0 = close). `⌊x⌋` = floor. All rates annual unless noted.

### H1 — Commercial lease engine (`proforma/leases.py`)

For each lease with start month `s`, end month `e`, area `sf`, base rent
`r₀` ($/SF/yr), escalation rate `g_esc` every `escalationMonths` (default
12) on lease anniversaries (calendar-anchored, pre-epoch anniversaries
counted):

```
months_elapsed(m)  = m − s                       (0 at lease start)
steps(m)           = ⌊months_elapsed(m) / escalationMonths⌋
rent_psf(m)        = r₀ · (1 + g_esc)^steps(m)               (fixed_pct)
                   = r₀ + step · steps(m)                    (fixed_step)
scheduled_rent(m)  = sf · rent_psf(m) / 12       for s ≤ m ≤ e
free_rent(m)       = scheduled_rent(m)           for the first freeRentMonths
```

Recoveries per month, where `R(m)` = property recoverable opex (H3 flags
or the default set = all fixed categories except replacement reserves):

```
NNN:            rec(m) = (sf / total_sf) · R(m)
gross:          rec(m) = 0
fixed_psf:      rec(m) = sf · recoveryValue / 12
base_year_stop: rec(m) = (sf / total_sf) · max(0, R_year(m) − R_base) / 12
                R_base = the lease-start CALENDAR year's recoverable opex
                         (pre-epoch bases de-grown at the expense growth)
```

Rollover at expiry with renewal probability `p`, downtime `d` months,
market rent `M(m)` (input, grown at market growth; fallback = the expired
lease's escalated rent at expiry):

```
expected rent during downtime window  = p · M(m) · sf / 12    (renewal side
                                        pays; re-let side is vacant)
after downtime: both paths pay market → M(m) · sf / 12
TI/LC (month after expiry, BELOW NOI):
  leasing_capital = p · (tiRenewal + lcRenewal·M·newTerm)
                  + (1−p) · (tiNew + lcNew·M·newTerm)   [per SF · sf]
```

Statement mapping (identities hold with no schema change):
`gpr := Σ scheduled_rent`, `vacancyLoss := downtime loss + free rent`,
`otherIncome := recoveries + otherIncome input`, credit loss applies to
collected revenue. `WALT = Σ(sf · remaining_years) / Σ sf`. The general
`vacancyPct` NEVER applies to lease income (downtime IS the vacancy).

### H2 — Mixed-use composition

```
blended_X(m)   = residential_X(m) + commercial_X(m)     for every income row
fixed opex     : held ONCE (commercial side of the build)
mgmt fee       : fee_pct · EGI_component(m), summed     (linear in EGI)
recoverable pool for commercial tenants:
    R_c(m) = R(m) · share_c,  share_c = year-1 commercial scheduled revenue
                                        / year-1 total scheduled revenue
component reporting opex: fixed(m) · EGI-share(m) + own mgmt fee
component exit (both caps set):
    TV = Σ fwd-12 NOI_res / cap_res + Σ fwd-12 NOI_com / cap_com
component YoC: basis allocated pro-rata to component value at its cap
```

### H3 — Expense-line detail

```
line annual base:  annual_total → a
                   per_unit     → a · Σ unitCount
                   psf          → a · known SF        (fallback: annual, warned)
                   pct_of_egi   → aggregated into fee_pct (NEVER recoverable)
line vector:       base/12 · (1 + g_line)^⌊(om−1)/12⌋   (g_line falls back
                                                         to deal growth)
recoverable pool R(m) = Σ flagged dollar-line vectors
insurance stress (+25 / +50%): FULL engine re-computes with insurance
lines scaled — DSCR and levered-CF deltas are exact, knock-ons included.
```

### H4 — Property tax reassessment (opt-in, default OFF)

```
projected_taxes = price · assessmentRatio · millage
    price  = purchasePrice   (acquisitions)
           = land + hard + soft costs  (developments)
    assessmentRatio default 0.85; millage from the assessor lookup or manual
growth: reassessedTaxGrowthPct (blank = deal expense growth), while other
        categories keep the deal growth
Replaces the modeled taxes in BOTH expense modes; detail-mode recoverable
flags survive, so NNN recoveries track the reassessed amount.
Derived millage when the PA API doesn't state it: currentTaxes / taxableValue.
```

### H5 — Comps benchmark flags (≥ 3 comps in market required)

```
rent premium   = subject_rent / median(comp rents) − 1
                 caution > +10%, warning > +20%
cap compression = median(comp caps) − subject exit cap
                 caution > 50bps, warning > 100bps   (exit above median: never flagged)
```

### H9 — History • H13 — Cache (mechanics, not finance)

```
snapshot = inputs AFTER a save; coalesce while newest snapshot age < 10 min
           (anchored on created_at); changedPaths = ∪ per-save diffs;
           retention 200/deal; restore records itself (undoable)
compute cache: key = canonical sorted-JSON of inputs, LRU 128,
               hits return deep copies
```

### H11 — Native Excel model (formula-live, mirrors the engine)

```
GPR(m)      = GPR_annual/12 · (1+g_rent)^INT((m−1)/12)
vacancy(m)  = GPR(m) · v          credit(m) = GPR(m)·(1−v)·cl
EGI(m)      = GPR − vac − credit + Other(m)
opex(m)     = SUMPRODUCT(category annuals/12, (1+g_cat)^INT((m−1)/12))
              + EGI·fee
PMT         = L·r/12 / (1 − (1+r/12)^−ROUND(amort·12))    (IO first io months)
TV          = Σ NOI(hold+1 .. hold+12) / exit_cap
IRR         = (1 + IRR(monthly flows, guess .005))^12 − 1
```

Two value-only cells, flagged on the Notes sheet: the app-sized loan
amount and the collapsed annual GPR/other income. Unsupported shapes
(development, leases, opex detail, waterfall tiers, XIRR, reassessed
taxes) refuse with the blocker list.

---

## 2. DECISIONS.md delta (Run 3)

All logged in DECISIONS.md with rejected alternatives; the load-bearing
[FIN] ones:

- **H1** calendar-anchored anniversary escalations; free rent abates base
  only; base-year stop floored at 0 with the base = lease-start calendar
  year; expected-value rollover (single blended path, not scenario trees);
  market-rent fallback = escalated in-place at expiry; TI/LC below NOI;
  vacancyPct never applies to lease income; break-even occupancy = 1.0
  for pure lease deals.
- **H2** composition of the two existing paths (no third engine); fixed
  opex held once; commercial recovery share pro-rated by year-1 scheduled
  revenue (avoids EGI circularity); EGI-share allocation is REPORTING
  only; component-cap exit is opt-in (both caps required).
- **H3** detail mode replaces flat fields entirely (mixing double-counts);
  pct_of_egi lines never recoverable (circular); insurance stress by full
  re-compute, not analytic deltas (wrong for NNN).
- **H4** reassessment = price × ratio × millage with ratio default 0.85;
  toggle default OFF; missing millage warns and no-ops.
- **H5** comps flags need ≥3 comps ("two comps are an anecdote"); exit cap
  above the comps median is conservative, never flagged; import preview
  writes nothing until a mapping is submitted.
- **H8** presets carry rates/terms only (server-side whitelist); apply is
  checkbox-gated per row.
- **H9** baseline snapshot before the first edit; restores are snapshots
  (undoable); baseline eventually rolls off retention (history, not a pin).
- **H10/H12** zero math in renderers; share must never 500 (error page),
  deck 422s instead of serving a corrupt file.
- **H11** refuse rather than degrade; the two value-only cells are flagged.
- **H13** cache NOT inside engine.compute (sweeps would churn it);
  deep-copy on hit.

**BLOCKED.md delta: none** — no feature was blocked.

---

## 3. Manual QA checklist (ordered by risk)

Lease-engine conventions first — these are silent-wrong-number risks;
UI/plumbing last.

1. **Lease escalations & anniversaries.** Enter a lease starting
   2024-06-01 (pre-epoch) at $30 NNN, 3% fixed_pct. Confirm the 2026
   monthly rent shows TWO escalation steps ($31.83), stepping again every
   June. Compare month before/after the anniversary on the Cash Flow tab.
2. **Recovery math.** One 5,000 SF NNN tenant in a 10,000 SF property with
   $60k recoverable taxes → recoveries exactly $2,500/mo. Switch to
   base_year_stop: year-1 recoveries $0; raise expense growth and confirm
   they appear in year 2 and NEVER go negative if opex declines.
3. **Rollover blend.** Set a lease expiring month 18, p=0.7, 6-mo
   downtime, TI/LC non-zero. Confirm: months 19–24 collect 70% of market
   rent; month 19 shows leasing capital BELOW NOI (statement row) and IRR
   drops when p → 0 (pure re-let) and rises when p → 1 (pure renewal,
   no downtime).
4. **vacancyPct isolation.** On a pure commercial-lease deal, change
   vacancyPct 5% → 20%: NOI must NOT move (downtime is the vacancy).
5. **Mixed-use identity.** Enter both a unit mix and a rent roll. Sum the
   Residential and Commercial statement filters' NOI for any month and
   confirm it equals Blended. Set both component exit caps and check
   terminal value = the two component values summed.
6. **Detail-mode equivalence.** Re-express the flat expense fields as
   detail lines with the same growth: every output identical. Then bump
   insurance +25% via the stress table and sanity-check the DSCR delta.
7. **Reassessed taxes.** Toggle ON with price $10M, ratio 85%, millage 2%:
   taxes become $170k/yr in the statement; toggle OFF restores the input
   taxes exactly. Missing millage → amber warning, unchanged taxes.
8. **Excel model export.** Export a plain acquisition, open in Excel,
   change the exit cap cell — IRR must move. Confirm the Notes sheet flags
   the loan-amount and GPR cells. Try exporting a lease deal → clear 422
   listing the blockers.
9. **Comps flags.** Import the Yardi CSV fixture (3+ Miami comps), set the
   deal market to Miami with an exit cap 100bps inside the comps median →
   warning flag appears in the benchmarks panel; delete a comp (down to 2)
   → flag disappears.
10. **History restore.** Edit purchase price twice within 10 minutes (one
    snapshot), wait for a new window or restore the baseline: the form
    rehydrates and the restore itself appears in the drawer (undo works).
11. **Presets.** Apply "Conservative" over a deal via the preview diff —
    only checked rows change; save the current form as a preset and
    confirm purchase price is NOT captured.
12. **Pipeline & staleness.** Change a deal's stage from the Deals tab;
    reload; confirm persisted. (Staleness badges need a 14-day-old deal —
    verify by backdating updated_at in SQLite if desired.)
13. **Share & deck.** Open share.html for a computed deal — no external
    requests in DevTools' network tab; download deck.pptx and confirm it
    opens with the two charts.
14. **Hardening.** Check the backend log shows `rid=… → status ms` lines;
    throw a render error (React devtools) and confirm the boundary page +
    a client-error log line; import a 500-row comps CSV and confirm the
    table scrolls smoothly (windowed).

## 4. Suite status at wrap-up

- pytest: **302 passed** (incl. leases, mixed-use, opex detail, property
  tax, comps, demographics, presets, history, share, deck, export
  structure, hardening)
- parity CLI: **3 template cases + 2 native-export cases, zero deltas**
- vitest: **86 passed** · tsc -b clean · oxlint clean
- Playwright: **2 journeys green** (happy path + Run-3 surfaces)
