# Blocked Items

## F4 — local Excel-recalc parity verification

The native-vs-Excel output diff needs LibreOffice. The winget MSI install
(`TheDocumentFoundation.LibreOffice`) hung at "Starting package install…" —
it appears to require a UAC elevation prompt this unattended session cannot
answer. The injection-layer parity assertions (right cells, sheet-scoped
names, merge anchors, fullCalcOnLoad) run and pass locally; the full recalc
diff skips with a reason locally and runs in CI (ubuntu installs
libreoffice-calc via apt in .github/workflows/ci.yml), and via
`python -m tests.parity.run` on any machine with LibreOffice.

**To clear:** install LibreOffice interactively (or approve the pending UAC
prompt), then re-run `python -m tests.parity.run` from `backend/`.

## Pre-existing (not introduced by this run)

- `ANTHROPIC_API_KEY` is unset in backend/.env — LLM extraction fallback and
  ambiguous-document classification degrade to heuristics (by design).
- `FRED_API_KEY` is unset — /api/market/rates returns graceful nulls and the
  rates helper text stays hidden (by design).
