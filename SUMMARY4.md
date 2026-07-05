# SUMMARY4 — Autonomous Build Run 4 (I0–I15)

Sixteen commits (I0..I15), each gated on pytest (370), vitest (100),
tsc -b, oxlint, the three-way parity CLI (7 workbook cases, zero deltas),
AND the I0 regression baseline: five representative deals whose full
`?detail=true` payloads are pinned to 1e-9 — every Run-4 input at its
default reproduces Run-3 byte-for-byte. **BLOCKED.md delta: none.** The one
spec-vs-compatibility conflict (I2's TI/LC timing changes cash timing at
defaults whenever downtime > 0) was resolved by making the refinement
opt-in rather than blocking it.

Notation: `m` month (1-based), `p` renewal probability, `M(m)` market rent,
`R(m)` monthly recoverable pool, `⌊x⌋` floor.

---

## 1. BEFORE → AFTER algebra (I1–I8, the core deliverable)

### I1 — CAM admin fee + management recoverability

Pool-based recovery billing (NNN and base-year-stop only):

```
BEFORE   rec_NNN(m)  = share · R(m)
AFTER    rec_NNN(m)  = share · R(m) · (1 + adminFeePct)          [default 0 → identical]

BEFORE   rec_stop(m) = share · max(0, R_yr(m) − R_base) / 12
AFTER    rec_stop(m) = share · max(0, R_yr(m) − R_base) / 12 · (1 + adminFeePct)
         (the year comparison stays on RAW pool amounts; only the billed
          delta is marked up; fixed_psf and gross carry no markup)
```

Recoverable pool composition:

```
BEFORE   R(m) = Σ recoverable expense lines(m)
AFTER    R(m) = Σ recoverable lines(m) + mgmtPool(m)              [flag default off]
         mgmtPool(m) = min( fee% · preEGI(m),  cap% · preEGI(m) )
         preEGI(m)   = collectedBaseRent(m)·(1−creditLoss) + otherIncome(m)
```

The fee EXPENSE stays on full EGI (M6). Pre-recovery EGI breaks the
fee→EGI→recoveries→fee circle deterministically (iteration rejected: not
mirrorable in a formula workbook).

### I2 — Rollover timing + renewal spread

Rent paths per speculative generation (spread default 1.0 → identical):

```
BEFORE   scheduled(m) = M(m);   downtime: collected = p·M,  loss = (1−p)·M
AFTER    renewal side = d·M(m)  where d = renewalRentPsfDiscountPct
         scheduled(m) = p·d·M + (1−p)·M
         downtime:  collected = p·d·M,   loss = (1−p)·M
         post:      collected = p·d·M + (1−p)·M
         (d applies at EACH renewal event against that generation's market
          track — never compounding through generations)
```

Leasing capital (timing flag default off → identical):

```
BEFORE   cap(expiry+1) = [p·TIᵣ + (1−p)·TIₙ]·SF + [p·LCᵣ% + (1−p)·LCₙ%]·M·SF·T
AFTER (flag on)
         cap(expiry+1)            = p·(TIᵣ·SF + LCᵣ%·d·M·SF·T)
         cap(expiry+downtime+1)   = (1−p)·(TIₙ·SF + LCₙ%·M·SF·T)
         (a commencement past the analysis end never incurs its capital)
LC bases follow the contract each side signs: renewal on d·M, re-let on M.
```

### I3 — Base-year gross-up (base_year_stop only; default off)

```
BEFORE   R_yr from the raw pool
AFTER    R_adj(m) = fixed(m) + variable(m) · max(1, grossUpTo / occ(year))
         R_yr(base AND comparison years) from R_adj;  NNN still bills raw R(m)
occ(year) = calendar-year mean of the COMMERCIAL occupied-SF share
            (contract months 1, downtime months p, speculative months 1);
            pre-epoch base years reuse year 1's occupancy.
variable = detail lines flagged variableWithOccupancy (defaults: utilities,
           R&M); simple-expense mode has no split → input hidden/ignored+warn.
```

### I4 — Mixed-use opex allocation basis

```
BEFORE   pool split: share_c = y1 commercial scheduled rev / y1 total (frozen)
         reporting split: monthly EGI share
AFTER    basis = revenue_share_y1 (default)  → BOTH unchanged (legacy pairing)
         basis = sf                → share_c = SF_c / (SF_c + Σ units·avgSf),
                                     drives pool AND reporting (scalar)
         basis = revenue_share_annual → share_c(year) recomputed per calendar
                                     year on gross scheduled revenue, drives
                                     pool AND reporting (per-month vector)
Component NOIs sum to blended under every basis (allocation only
redistributes fixed opex). Unknown SF on either side → default + warning.
```

### I5 — Non-ad-valorem assessments

```
BEFORE   millage = totalTaxes / taxableValue      (overstates ad-valorem)
AFTER    millage = adValoremTaxes / taxableValue  (fallback: old formula + note)

BEFORE   projected taxes = price · ratio · millage
AFTER    projected = price · ratio · millage  +  nonAdValorem (carried, never reset)

Engine line: nonAdValorem(m) = NAV/12 · (1+g_nav)^⌊(om−1)/12⌋, its own
growth clock, recoverable by DEFAULT, never touched by reassessment.
```

### I6 — Comp normalization (context flags; thresholds unchanged)

```
BEFORE   benchmark = pooled median(comp rents), min 3 comps
AFTER    tier 1: Σ w_b · median(rents of bedroom class b) / Σ w_b
                 (usable only when EVERY weighted subject class has ≥3 typed comps)
         tier 2: subjectRent/avgUnitSf  vs  median(comp rent/SF), ≥3 psf comps
         tier 3: pooled median + explicit low-confidence note
         min-3 applies PER TIER; premium thresholds (+10%/+20%) unchanged.
Sale flags: cap-vs-cap unchanged; explanation adds median $/unit (MF/mixed)
or $/SF (commercial) context, plus "N comps older than 12 months" notes.
```

### I7 — Excel export widening (formulas, not engine changes)

```
Expenses block:  annual_i = amount_i · units (per_unit) | · SF (psf) | · 1
                 fixed(m) = SUMPRODUCT(annual/12, (1+growth)^⌊(om−1)/12⌋)
Development:     cost(m) = (Hard+Cont)·w_m + (Soft+Fee)/CM   [w = literal S-curve]
                 equity_m = max(0, min(cost_m, EqTarget − Σ prior equity))
                 bal_m = (bal_{m−1} + fee_m + draw_m)·(1 + r/12·[m≥1])
                 carry: bal = max(0, bal·(1+r/12) − NOI);  levered ≡ 0
                 takeout: levered += Perm − carryBal − Perm·refiCosts%
Fixed en route:  acquisition yieldOnCost = stabNOI / (basis + loan fees)
                 (was ÷ basis alone — a real divergence the harness caught)
```

### I8 — Per-lease drill-down (pure exposure)

`Σ per-lease slices ≡ property vectors` for scheduled rent, free rent,
downtime, recoveries, TI/LC — accumulated in the same loop, tested as an
identity, keyed by suiteId, trimmed to the hold horizon. The only baseline
change of the run: a pure payload EXPANSION (verified key-only diff, then
regenerated).

---

## 2. DECISIONS / BLOCKED deltas

Nine new DECISIONS blocks (I1–I5 [FIN]-tagged throughout; I6, I9, I11–I14
convention entries), highlights: pre-recovery-EGI convention with iteration
rejected (I1); opt-in TI/LC timing because the compatibility rule beats the
spec's default (I2); commercial-occupancy gross-up basis — residential
vacancy must not gross up commercial CAM (I3); legacy reporting pairing
under the default allocation basis (I4); non-ad-valorem never resets at
sale, recoverable by default (I5); refuse-don't-degrade retained for the
Excel export with sold-before-stabilization the one dev refusal (I7);
extraction column RESERVATION fixing two golden-blessed bugs (I9); dedupe
skip-or-import, never silent merge (I11); restore preview diffs the LAST
SAVED state (I12); fix-the-hot-spot-never-raise-the-budget (I14).
**BLOCKED.md: still empty — nothing was blocked.**

## 3. Manual QA checklist (recovery math first)

1. **Admin fee.** NNN tenant, $36k recoverable taxes, share 1: recoveries
   $3,000/mo; set adminFeePct 10% → $3,300/mo and NOI up exactly $300.
   Switch to fixed_psf → the markup must do NOTHING.
2. **Mgmt recoverability.** Fee 3%, flag ON: recoveries rise by fee% ×
   pre-recovery EGI (not by fee% × full EGI — check the delta against
   collected rent only). Cap 1% halves nothing until it binds. Base-year
   lease under flat growth: still $0 recovery (no spurious step).
3. **Gross-up.** Opex detail with utilities variable, 60%-occupied year,
   grossUpTo 95%: base-year tenant recovers the grossed delta (hand: $140/mo
   on the fixture numbers); set grossUpTo 50% → floor keeps it $0. In
   simple-expense mode the input is hidden and warned if set via API.
4. **Renewal spread + timing.** d = 0.95, p = 1: post-rollover rent and LC
   both scale by 0.95; p = 0: nothing changes. Flag the timing ON with
   downtime 4: TI/LC splits into expiry+1 (renewal) and expiry+5 (re-let),
   same total dollars, levered CF at expiry+1 visibly higher.
5. **Allocation basis.** Mixed deal: flip to 'sf' with unit-mix Avg SF set →
   recoveries move to the SF share and the Commercial statement filter's
   opex matches it; 'revenue_share_annual' with an escalating lease → the
   commercial share (and recoveries) rise each calendar year. Component
   NOIs must still sum to blended under all three.
6. **Non-ad-valorem.** Set $12k NAV: statement gains its own line; enable
   reassessment → ad-valorem line resets, NAV line doesn't; lookup panel
   shows "projected ad-valorem + carried non-ad-valorem = total" and the
   millage-from-total fallback note when the PA split is missing.
7. **Excel export.** Export a development: change the LTC cell → equity,
   draws, capitalized interest, and IRR all move; the Draws sheet weights
   stay literal. Export the opex-detail deal: edit a per_unit amount → the
   statement moves through the resolving formula. Both recalc under
   LibreOffice with zero parity deltas (CI enforces).
8. **Per-lease drill-down.** Sum the drill-down rows' scheduled rent for
   any month against the statement GPR; check a rollover chip's months
   match the expiry ladder; CSV export opens with the right year buckets.
9. **Comp tiers.** Typed comps covering the subject mix → explanation says
   "unit-type weighted"; delete one class's comps → falls to $/SF or pooled
   with the low-confidence note; stale comps show age chips and the flag
   note.
10. **Extraction.** Import the hostile CoStar fixture: the $87,500 "monthly"
    rent lands at $35/SF with a magnitude warning; MTM tenant proposes with
    no expiry + warning; "Suites 100-102" stays one lease; month-year
    expiries land on month END. Stacking plan: no-rent tenants survive at
    $0 with the fill-in warning.
11. **Pipeline/comps/history UX.** Bulk-select two deals → set status +
    export a screening deck (title slide lists skips, ≤20 cap); save a
    named view and re-apply it; import a duplicate comp → preview flags it
    with default-skip; compare two snapshots → row-level badges; Restore
    shows the last-saved→target preview before confirming.

## 4. Suite status at wrap-up

- pytest **370 passed** (incl. the I0 baseline, recoverability, rollover
  refinements, gross-up, allocation, non-ad-valorem, comp normalization,
  drill-down identities, extraction goldens ×15, perf guard)
- parity CLI: **3 template + 4 export cases, zero deltas**
- I0 regression baseline: **5 deals, 1e-9, green** (one documented
  expansion for I8's perLease key)
- vitest **100 passed** · tsc -b clean · oxlint clean · Playwright e2e
  **2 journeys green**
