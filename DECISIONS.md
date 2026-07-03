# Decisions Log

Non-obvious choices made during the autonomous build run, with the
alternatives rejected. Financial-convention decisions are marked **[FIN]**.

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
