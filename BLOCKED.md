# Blocked Items

## ~~F4 — local Excel-recalc parity verification~~ (CLEARED)

The LibreOffice winget install eventually completed (it was slow, not
blocked). `python -m tests.parity.run` now passes locally: **all 31 mapped
outputs match between the native engine and the LibreOffice-recalculated
Excel path with zero deltas** (IRRs to 6dp), after adding an explicit
convergence guess to the templates' IRR() formulas — LibreOffice's default
10%-per-period guess fails to converge on low monthly-IRR vectors.

## Pre-existing, discovered during L-phase verification (not introduced by this run)

- `tests/test_deal_history.py::test_retention_caps_snapshots_per_deal` is
  flaky — asserts the newest of 10 rapid-fire snapshot writes survives a
  5-item retention cap, but fails intermittently with a DIFFERENT wrong
  snapshot surviving each time (`{"n": 7}`, `{"n": 6}`, etc.), pointing at a
  `created_at` timestamp-resolution tie-break race, not a real data-loss
  bug. Confirmed unrelated to the L0-L7 build: no L-phase commit touches
  `deals.py`/`DealSnapshot`/deal-history code at all (last touched by I13,
  well before this run). Not fixed here — out of scope for the proforma
  engine work this run covers.

## Pre-existing (not introduced by this run)

- `ANTHROPIC_API_KEY` is unset in backend/.env — LLM extraction fallback,
  ambiguous-document classification, and the Agent (when
  `AGENT_PROVIDER=anthropic`, the default) degrade to a clear
  "unavailable" message rather than erroring (by design).
- `OPENAI_API_KEY` is unset — the Agent degrades the same way when
  `AGENT_PROVIDER=openai` (by design).
- `FRED_API_KEY` is unset — /api/market/rates returns graceful nulls and the
  rates helper text stays hidden (by design).
