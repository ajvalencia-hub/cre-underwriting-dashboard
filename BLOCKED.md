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
