# Roadmap: improvements and features

Source: three independent audits (September 2026) that compared this
dashboard with market-leading products. The analyst audit covered ARGUS
Enterprise, Rockport VAL, Dealpath, A.CRE models, Valuate and CoStar. The
design audit covered Dealpath, ARGUS, Juniper Square, Causal, Pigment,
Linear and Stripe. The engineering audit covered Electron and Tauri security
practice, Sparkle, Alembic, the FastAPI full-stack template and
Hypothesis. I checked their claims against the code before listing them
here. **✓** means I reproduced or read the problem in code.

Effort: **S** is under a day, **M** is a few days, **L** is a week or more.

## Done: engine audit fixes

Each fix below has a test that fails without it. They're recorded in
DECISIONS.md under "Engine audit fixes".

| Fix | Effect |
|---|---|
| IRR solver no longer crashes on long or stressed deals | 19 of 64 stress cases returned a 500; 720 stressed runs now all compute |
| Several IRRs are flagged | warning lists every root |
| Construction LTC includes interest and fees; fee charged on the loan commitment | a stated 60% LTC used to carry 61.4% of cost; the fee was about 1% of one draw |
| Development permanent loan can have its own LTV | `permanentLtvPct` (blank = same as LTC) |
| Value-add yield on cost counts the renovation premium | a rent-raising renovation used to *lower* yield on cost |
| Per-deal analysis start (closing) date | lease timing used to be fixed to Jan 2026 |
| Min DSCR is tested per loan year | one downtime month used to set the headline (0.83x vs 1.12x) |
| Inputs are type- and range-checked | text "0.1" used to read as 0 (IRR 11.6% → 15.4%) |
| The form labels the 25 inputs Compute ignores | hotel, for-sale homes, draw schedule, loan term… |
| Going-in debt yield; American waterfall hurdle warning | |
| Excel export: development with no build period | the exported IRR used to be nonsense |

## Now: small fixes with a real risk behind them

| # | Item | Why | Effort |
|---|---|---|---|
| 1 | ~~**Deleting a document can break another deal's attachment**~~ **Done** (4f4a778) | `documents.py` deletes a file that other records share (same content hash), and a re-upload can then fail with a 500 | S |
| 2 | ~~**Backup rotation and restore safety**~~ **Done** (5cd7d8e, 137af9e) | A backup runs on every launch and only 7 dailies are kept, so 7 relaunches wipe older backups. Failures are swallowed silently. Restore doesn't snapshot first, and `kind` isn't validated | S–M |
| 3 | ~~**Docker mode is open to the local network** ✓~~ **Done** (367a8f1) | Binds to `0.0.0.0` with no login; publish on `127.0.0.1`, add `nosniff` and CSP headers, serve SVGs as downloads | S |
| 4 | ~~**Loading a scenario silently replaces every input** ✓~~ **Done** (63bd3d8) | Add a confirm (reuse the preset diff) and a "Working from: <scenario>" chip | S |
| 5 | ~~**Numbers people read are hard to read** ✓~~ **Done** (58664ba, a81f16e) | 182 uses of `text-slate-400` (about 2.6:1, below WCAG AA). Negative money shows as `$-2,116,364` | S |
| 6 | ~~**Six of the twelve tabs are off-screen at 1440px**~~ **Done** (a992089) | Move module navigation into the left rail, grouped, without the numbering | M |
| 7 | ~~**Quick Screen total cost leaves out the developer fee and financing**~~ **Done** (34355a4) | Its yield on cost reads higher than Compute for the same deal | S |
| 8 | ~~**Bridge tightening** ✓~~ **Done** (6da1c29) | `DesktopBridge.attach` is callable from the page; rename it private and check the origin in each method | S |
| 9 | ~~**Default the analysis start date from Critical Dates "Closing"**~~ **Done** (5614529) | The new input should fill itself when the date is already known | S |

## Next: substantive gaps an analyst would hit

| # | Item | Why | Effort |
|---|---|---|---|
| 10 | ~~**General vacancy and credit reserve on lease-roll deals, and free rent on speculative leases**~~ **Done** (f4fa54b) | NOI and exit value are overstated for well-leased office and retail; ARGUS layers general vacancy on top of rollover downtime | M |
| 11 | ~~**Loan maturity, balloon and refinance within the hold**~~ **Done** (25d58c8) | `loanTermYears` is ignored, so a 10-year hold on a 5-year loan never refinances | M |
| 12 | ~~**User-defined construction draw schedule**~~ **Done** (2077d3c) | `constructionDrawSchedule` is ignored today (S-curve only) | M |
| 13 | ~~**Template results say "Excel" but are LibreOffice recalculations**~~ **Done** (347c22c) | LibreOffice's IRR can differ. Label them honestly, and check a template on upload by recalculating it unmodified and comparing mapped outputs with Excel's saved values | M |
| 14 | ~~**Where each value came from**~~ **Done** (74ca9bb) | After applying OM extraction, presets or goal seek, a field doesn't show that the app filled it. Add a source chip and an "unreviewed extraction" filter | M |
| 15 | ~~**Field definitions**~~ **Done** (a839b30) | None of the 151 inputs explains its units or meaning. Add a frontend help map with an accessible ⓘ popover | M |
| 16 | ~~**Scenario comparison with a base and Δ column**~~ **Done** (917a466) | Today it shows absolute values only (Causal and Pigment show variance to a base) | S–M |
| 17 | ~~**Sensitivity grid anchored on the base case**~~ **Done** (bd167f8) | Pre-fill ± steps, outline the base cell, use a colour-blind-safe scale around the base value and an optional user hurdle | S–M |
| 18 | ~~**Pipeline columns with numbers**~~ **Done** (acb2422) | Price, equity, IRR and yield on cost from each deal's last result, with a stale dot (Dealpath-style configurable fields) | M |
| 19 | ~~**Per-tab side panels**~~ **Done** (ede84ff) | The deal-inputs rail and the single-deal summary take 576px on Portfolio, Comps and Settings | M |
| 20 | ~~**Accessibility**~~ **Done** (877cfc2) | Tie error messages to inputs (`aria-describedby`), make Goal Seek reachable by keyboard, add Esc and `aria-expanded` to the New Deal menu | S |
| 21 | ~~**Database migrations: versioning and backup before migrating**~~ **Done** (6c3ff9f) | No `user_version`; an older build silently opens a newer database | M |
| 22 | ~~**Typed API contract**~~ **Done** (9a46eb6, 065d762, 36aefc3, d6dcba2) | 29 of 89 routes declare a response model; the frontend casts JSON to hand-written types. Generate TS types from OpenAPI and check them in CI | M |
| 23 | ~~**Trended vs untrended yield on cost; growth during construction**~~ **Done** (cf54772) | Development rents are flat through construction; show both conventions explicitly | S |
| 24 | ~~**Exit mechanics**~~ **Done** (d67fb79) | Prepayment, defeasance and yield maintenance at sale; exit cap on NOI after reserves; trailing vs forward NOI as a choice | S–M |

## Later: new capability

| # | Item | Notes | Effort |
|---|---|---|---|
| 25 | **Hotel model** (keys, ADR, occupancy, departmental and undistributed expenses, FF&E) | The inputs already exist and are labelled template-only | L |
| 26 | **For-sale / build-to-sell** (homes, absorption, sale price) | The inputs already exist; needs a sales-absorption cash-flow engine | L |
| 27 | **Market leasing profiles per tenant or space type** | ARGUS-style market leasing assumptions; today there is one global rollover profile | M–L |
| 28 | **Investment committee workflow** | Approvals, sign-off, change log with reasons, several users (Dealpath and Rockport VAL audit trail) | L |
| 29 | **Market data feeds for comps** | CoStar, CompStak or MSCI integrations; licensing-dependent | L |
| 30 | ~~**⌘K for fields, tabs and actions**~~ **Done** | Linear-style: Compute, Generate, or jump to any field | M |
| 31 | **Signing, notarization and auto-update for the desktop app** | Previously out of scope; needed before wider distribution (Developer ID with hardened runtime, then Sparkle) | L |
| 32 | ~~**Engineering hygiene**~~ **Done** (f4ae14b, d515893, ad3d73b, ef4b8e7, e088d0b, and the CI job) | Split `App.tsx` (1,226 lines), add ruff and mypy, share test cases between the TypeScript Quick Screen math and the engine, add property-based input tests, SQLite WAL and `busy_timeout`, and build the `.app` plus its self-test in CI | M |

## Strengths to keep

All three audits named these as ahead of the leaders:
- **Template workflow:** the mapping preview and coverage view, and Excel
  template injection that keeps the analyst's own model. Neither ARGUS nor
  Valuate does the latter.
- **Result trust:** freshness and staleness labelling on every result, and
  engine–Excel–LibreOffice parity tests with a byte-level regression baseline.
- **Analytics depth:** debt sizing by governing constraint, a stress grid,
  Monte Carlo, goal seek, tornado and hold-period sweeps.
- **Desktop shell:** a per-launch token gate, a Host allowlist, a
  single-instance lock, clean shutdown and a frozen self-test.
