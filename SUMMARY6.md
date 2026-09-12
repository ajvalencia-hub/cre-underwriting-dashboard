# Run 6 — Full audit and fix run — Summary

Run 6 started from a full audit of the build rather than a feature spec:
five parallel read-only reviews (engine math, API/security, frontend,
tests/CI/docs, and the preserved `agent-underwriting-line` branch) produced
verified findings with file:line evidence, and every accepted finding shipped
with a failing-first test. The compatibility rule held: **every new engine
input defaults to reproducing the prior outputs byte-for-byte** — the six
Run-4 regression baselines are unchanged at 1e-9, and a seventh fixture now
pins the feature-on paths.

Gate state after the audit fixes (before the agent port — see the last
section for the final numbers): **569 backend tests**, **170 vitest**, parity clean, regression baseline green (7 cases),
2 Playwright journeys green, `ruff` clean, `mypy` clean (ratchet), `tsc` +
`oxlint` + `vite build` clean.

---

## What the audit found, and what changed

### Financial engine (all changes tested; baseline values untouched)

| Finding | Fix | Baseline impact |
|---|---|---|
| Refi-vs-sale charged the **sale-at-stabilization** leg refinance costs plus a 1-month perm schedule it never incurs | Takeout fires only when `takeout_month < hold end` (general rule, not a hold.py flag) | none (no fixture ends in its stabilization month) |
| Legacy-mode `stabilized_annual_noi` ignored `useReassessedTaxes`, so loan sizing / yield on cost / debt yield were computed on pre-reassessment NOI while the statement used the reassessed figure | Same substitution as the expense vectors | none (toggle default off) |
| `avgCashOnCash` / `cashOnCashYear1` stripped only sale proceeds from the exit month — the junior-tranche payoff and escrow release polluted the last year | All exit-month capital events stripped | none (feature-on only) |
| `amortYears = 0` (schema min) ballooned the whole loan in month IO+1 and reported a 1200% loan constant | IO everywhere: payment = interest, constant = rate, Excel emits the IO formula | none |
| Development with `constructionMonths = 0` silently exported a workbook with only land in Draws | Engine warning + Excel refusal | none |
| Construction origination fee charged on the **first draw** while its comment claimed the commitment | `constructionFeeBasis` [first_draw (default) \| commitment] | **would change** `analytic_development` (1% fee) → shipped behind the flag |
| Detail-mode legacy `breakEvenRatio` put stabilized EGI and NOI on different bases (flat vs line recoveries) | Implemented behind `operations.DETAIL_MODE_YEAR1_RECOVERIES` (default off) | **would move** `commercial_rollover.breakEvenRatio` 0.8429 → 0.8777 (only value affected) |
| Insurance-stress triple-compute inside hold sweep / refi fork / tornado / sensitivity / goal-seek | Skipped where nothing reads it (tornado 39 → 13 computes) | none |
| Silent double counts | Warnings: LTL % + turnover burn-off, flat + per-unit reserves, in-place sizing on a development, exit cap < 1% | none |

**Two operator decisions are pending** (both documented in DECISIONS.md with
the exact deltas): flipping `constructionFeeBasis` to `commitment` by default,
and turning on `DETAIL_MODE_YEAR1_RECOVERIES`. Each is a correctness
improvement that changes one baseline case; the baseline guard now refuses
value changes mechanically, so either flip is a deliberate regeneration.

### New engine feature — prepayment penalty at exit [FIN]

- `prepaymentPenaltyPct` (percent of the senior balance repaid at exit, both
  deal types, default 0).
- **Before:** `saleProceedsNet(T) = gross·(1 − costOfSale) − exitBalance`.
- **After:** `saleProceedsNet(T) = gross·(1 − costOfSale) − exitBalance·(1 + pct)`
  — levered only; unlevered and the terminal value never see it. Applies to
  whatever senior balance is repaid at exit (perm loan, or the construction
  balance when a development is sold before takeout); the junior tranche is
  not subject to it.
- Conditional output `prepaymentPenalty` + display statement row (only when
  > 0), mirrored in the Excel export (`B8 = B6 − B7 × (1 + pct)`).

### API and security (backend)

- Backup restore validated by construction (kind whitelist, snapshot-name
  regex, root containment) — previously any `app.sqlite3` on the filesystem
  could be loaded over the live DB. New validated download endpoint.
- Scheduler no longer snapshots on every process start (restart loops were
  rotating the daily retention away).
- Monte Carlo: a negative seed hung jobs in "running" forever; any worker
  exception now fails the job; seed validated; 2-worker pool with a queue
  cap (429 + Retry-After).
- Content-addressed files unlink only when the last row referencing the
  hash goes away (document delete, new attachment delete).
- File cabinet isolation: another deal's attachment is unreachable by id;
  provenance-linked docs restricted to global rows; SVG never inline;
  inline responses carry nosniff + a sandbox CSP; stored extension
  whitelisted.
- LIKE metacharacters escaped (`__` matched every deal; `%` disabled the
  comps filter); chunked CSV import; template/mapping delete clears deal
  selections; LibreOffice timeout is a 500-free failure; Content-Disposition
  strips control chars; X-Request-ID bounded; IC deck scenario must belong
  to the deal; `.xls` refused with guidance; `.env` excluded from the image.

### New features

- **Optional API token** (`CRE_API_TOKEN`): Bearer / X-API-Token header or an
  HttpOnly HMAC session cookie set by `/api/auth/login`; health, auth and the
  SPA stay public; unset = unchanged. Full-page token prompt in the UI, any
  401 re-shows it, Sign out in Settings.
- **Deal archive / unarchive** (soft delete: hidden from pipeline, portfolio
  and search; everything attached kept) with a "Show archived" pipeline
  toggle; **deal clone** (inputs, stage, template refs, scenarios; not notes
  or history) from the header's More menu.
- **Attachment delete**, **backup download**, **unsaved-changes guard**,
  **Escape / outside-click** for every modal and popover, **Ctrl/Cmd+1..9**
  tab switching and a "?" shortcut list, **confirmation** on every
  destructive action, **Settings > Workflow** (default New Deal type, last
  tab restored), **Recent deals** in the palette, boot **Retry**.
- **Output metrics filtered by deal type**; hold-sweep copy is type-aware.
- **Dark mode** coverage completed (remaining utilities, chart SVG fills,
  emphasis rows inside cards), a global focus-visible ring, a print
  stylesheet.

### Frontend bugs fixed (from the audit)

Template & Mapping wiped the deal's mapping selection on every page load;
the quick-screen URL sync autosaved defaults over the deal's napkin on slow
boots; untyped deals were silently typed as acquisition on first edit
(schema default removed); analysis results leaked across deal switches;
out-of-order async responses (deal switch, palette, comps, market context,
rate hints); acquisition napkin never persisted; sticky portfolio error;
comps filter stuck on the boot deal's market; blank critical dates saved;
deleting a deal fired its pending autosave into a 404; unguarded
localStorage (blank page in private mode); a dozen unhandled promise
rejections now surface as toasts; duplicate keys, empty-histogram crash,
NaN Monte Carlo seed, tab-number copy.

### Ported from `agent-underwriting-line`

Extraction fixes (letter guard in `parse_numeric`, "Tenant ID" vs
"Resident Name", studio/"2-bd" multifamily signals, structural fallback),
classification threshold + word-boundary scoring + OM page bonus, the
two-column operating-statement parser, rent-roll boundary detection (with
a two-row lookahead guard against truncating rolls with mid-table
subtotals), unit mix grouped by SF, bidirectional comps market matching,
the e2e scratch-DB sweep fix, and the ruff + mypy gate (applied to this
line's code, not the branch's config verbatim). The branch's own engine
work was not taken (this line has its own implementations).

### Test infrastructure, CI, docs

Shared `conftest.py` (15 fixture copies removed; the suite no longer
touches `backend/storage`); baseline guard (`UPDATE_BASELINE=1` refuses
value changes); seventh regression case `feature_on_value_add`; hard
parity gate in CI; ruff + mypy (ratchet) in CI; concurrency, timeouts,
advisory dependency audits, docker health smoke, dependabot; requirements
split; non-root Docker image with HEALTHCHECK; README rewritten for the
current tab set + full API/env tables; `ARCHITECTURE.md`; demo seed script;
`docs/history/` for the closed audit files.

---

## DECISIONS.md deltas (Run 6)

Four new blocks at the top: financial-engine fixes + prepayment penalty
(with the two pending compat flips and their exact deltas); API hardening,
token gate, archive + clone; frontend fixes, UX features, test
infrastructure, lint gate; and the Underwriting Agent port (see below).

## Excel-export refusal list (complete, as of Run 6)

1. Commercial lease-level rent rolls (escalations / recoveries / rollover)
2. Promote waterfall tiers
3. XIRR date-based IRR convention
4. Reassessed property taxes (separate tax growth clock)
5. Renovation program (value-add unit sequencing)
6. Loss-to-lease burn-off (turnover blend)
7. Asset management fee (partnership expense below NOI)
8. Junior tranche (mezzanine / preferred equity)
9. Floating-rate debt (forward curve, floor, rate cap)
10. Per-unit / PSF replacement reserves (convention-dependent placement)
11. Tax & insurance escrows (close/exit cash timing)
12. Development sold before **or at** stabilization (no permanent takeout occurs) — widened in Run 6
13. **Development with no construction period (`constructionMonths <= 0`)** — new in Run 6

The prepayment penalty and `amortYears = 0` (interest-only) are mirrored as
formulas, not refused. The `constructionFeeBasis` selection is mirrored in
the Draws sheet.

## Manual QA checklist — ordered by risk

1. **Compatibility (critical).** Upgrade against a real DB; spot-check the
   sidebar IRR / multiple on a saved deal — unchanged unless you flip one of
   the two documented compat flags.
2. **Untyped deals.** A deal created before the dealflow split with no type
   shows the "Untyped — set type" chip; compute-driven panels prompt for a
   type instead of erroring; choosing a type moves it onto the right board.
3. **Prepayment penalty.** Set 1% on an acquisition: levered IRR, equity
   multiple, total profit and NPV fall; unlevered IRR unchanged; the
   `prepaymentPenalty` row appears in the statement; the Excel export
   recalcs to the same numbers.
4. **Refi-vs-sale.** On a development, change `refiCostsPct` — the "sell at
   stabilization" leg must not move.
5. **Token gate.** Set `CRE_API_TOKEN`, restart: the prompt appears, a wrong
   token is rejected inline, the right one lands you in the app, Excel /
   deck / backup downloads still work, Sign out returns to the prompt.
6. **Archive / clone.** Archive a deal: gone from boards, portfolio and
   search, back via Show archived → Unarchive. Clone: scenarios copied,
   notes not; editing the clone leaves the source untouched.
7. **Backups.** Restore with a hand-edited request (`..` in the name) → 400;
   Download returns an SQLite file; restarting the backend twice within a
   day does not add a second daily snapshot.
8. **Monte Carlo.** Seed `-1` → 400 at submit (not a stuck poll); launch 7
   runs quickly → the 7th is a 429 with Retry-After.
9. **Dark mode.** Scenarios tornado, comps map and cash-flow hold chart
   labels are readable; sensitivity heat cells keep dark text.
10. **Keyboard.** Escape closes the goal-seek / dates / wizard / palette /
    New Deal popover; Ctrl+3 jumps to Deal Inputs; "?" in the palette lists
    shortcuts.

---

## Underwriting Agent port

The K-phase AI Underwriting Agent from the preserved branch was ported
from its pre-settings snapshot (f8a272d) and adapted to this line:

- **Backend**: `/api/agent/*` router; runner with hard caps (25 tool calls,
  15 compute-family calls, 60 s per turn); 10 read tools wrapping existing
  services and 2 write tools that produce *proposals* only (structurally —
  they take no DB session, asserted by test); provenance checker that
  flags every number in a reply not traceable to that turn's tool results
  (`unverifiedClaims`); Anthropic and OpenAI adapters behind one vendor-
  neutral shape plus a deterministic `scripted` provider for the e2e gate;
  four `create_all` tables; per-thread token totals.
- **Adaptation**: the branch's second bisection solver was dropped — the
  agent's `solve` tool wraps the J7 goal-seek (`{values?, targetInput,
  outputMetric, targetValue, bounds?}`, values default to the deal); config
  is read from `app.config` (no settings service); new modules pass the
  mypy gate with no ignore-list additions.
- **Frontend**: Agent tab (after Portfolio) and a floating dock sharing one
  per-deal thread; proposal cards with before/after diff and preview
  metrics; approve flushes the pending autosave, adopts the returned deal
  like a history restore and records an "Agent-applied" snapshot; reject
  takes a note; provider picker per thread; dark-mode classes only.
- **Tests**: +105 backend tests (context, plays, provenance, providers,
  router, runner, scripted provider, security, tools) and 2 Playwright
  journeys (scripted provider, including the "fabricate" turn that must be
  flagged).

Final gate state after the port: **674 backend tests**, **170 vitest**,
**4 Playwright journeys**, parity clean, 7-case baseline green, ruff clean,
mypy clean, `tsc` + `oxlint` + `vite build` clean.
