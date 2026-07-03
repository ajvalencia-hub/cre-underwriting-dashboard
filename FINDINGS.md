# Correctness Audit Findings

Audit date: 2026-07-02. Scope per Phase 0: extraction silent-failure paths, Excel
injection edge cases, frontend numeric handling, API contract drift,
concurrency/file handling. Severity rubric: **critical** = a wrong number can
reach the user; **high** = crash or data loss; **medium** / **low** = triage.

Critical and high items are fixed in this audit (one commit per fix, each with a
test that would have caught it). Medium items M1–M14 were fixed in a follow-up
pass later the same day, under the same one-commit-per-fix-with-test convention.
Low items remain open.

Three openpyxl behaviors asserted below (C4/C5 crash modes, M1 invisibility) were
verified empirically against openpyxl 3.1.5 before being written down, not assumed.

## Critical — wrong number reaches the user

| # | Issue | Location | Fix |
|---|---|---|---|
| C1 | T-12 line items that match no income/expense alias vanish silently: `_classify_label` only returns bucket `expense`/`income` together with a category, so `aggregate_categories`' uncategorized-expense branch is dead code and unmatched lines (e.g. "Landscaping", "Pest Control") are excluded from every total with no trace on the review screen. Compounding it, the LLM branch maps `mappedCategory: None` line items to bucket `"income"` (`"expense" if cat in EXPENSE_CATEGORIES else "income"`), where they are also silently dropped. User confirms understated opex. | `t12_parser.py:49-57,135-167`; `extraction_service.py:125` | **Fixed.** Unclassified lines are surfaced in the review screen's UNMATCHED section with a warning stating the count and dollar total; LLM `None` categories now bucket as `unknown`, not `income`. |
| C2 | Multi-page PDF rent rolls lose all pages but one: `_load_grid_and_text` keeps only the single largest table across all pages, so a 5-page rent roll is aggregated (unit count, occupancy, GPR) from one page's fragment — all plausible-looking. | `extraction_service.py:52-61` | **Fixed.** Same-shape tables are concatenated across pages in document order (repeated header rows skipped), with a warning naming the merged page range. |
| C3 | T-12 rows with a blank/unparseable Total cell are dropped even when the month columns contain data (e.g. the total was a formula whose cached value didn't survive), understating category totals with no signal. | `t12_parser.py:99-109` | **Fixed.** Falls back to summing the month columns (× annualize factor) when the total cell parses to `None`. |

## High — crash / data loss

| # | Issue | Location | Fix |
|---|---|---|---|
| H4 | A mapping whose named range spans multiple cells crashes the whole generate with a 500: `destinations[0]` yields a coord like `B1:C2`, `ws[coord]` returns a tuple, and `_is_formula_cell(tuple)` raises `AttributeError` (verified). | `excel_writer.py:18-33,71-84` | **Fixed.** Multi-cell destinations are skipped with an explicit warning (consistent with the existing formula-cell policy); read-back skips them too. |
| H5 | A mapping targeting a non-anchor cell of a merged range crashes generate: `MergedCell.value` is read-only → `AttributeError` (verified). Affects both scalar and table injection. | `excel_writer.py:84,100-106` | **Fixed.** Scalar targets remap to the merge anchor (the cell the user visually mapped); table injection skips merged cells and counts them in the existing skip warning; read-back reads the anchor. |
| H6 | A template filename containing non-ASCII characters (e.g. `Modèle.xlsx`) crashes every generate download with `UnicodeEncodeError` (ASGI headers are latin-1); embedded double quotes corrupt the `Content-Disposition` header. | `generate.py:59` | **Fixed.** ASCII-sanitized `filename=` fallback plus RFC 5987 `filename*=UTF-8''…` carrying the real name. |
| H7 | Selecting two T-12s (or two rent rolls) in one extraction run silently **sums** them into single fields — a YTD plus prior-year T-12 doubles GPR and every expense category with no warning. | `extraction_service.py:272-287` | **Fixed.** An explicit warning is emitted whenever more than one document of the same type contributes line items/rows to a merged run (intent can't be inferred, so warn rather than guess). |

## Medium — fixed in the follow-up pass

Each row's fix landed as proposed unless noted. Deviations worth knowing:
M6 prefers the statement's own EGI line, then derived EGI, then GPR (basis
always named in the field note). M7 scores quality as parse rate × substantive-
line classification rate, so unusual charts of accounts still fall to the LLM.
M14 applies templateId/mappingProfileId under create's validation but rejects
kind changes (kind is immutable; a dedicated ScenarioUpdate schema
distinguishes an omitted kind from an attempted change).

| # | Issue | Location | Fix (implemented) |
|---|---|---|---|
| M1 | Worksheet-scoped defined names are invisible: `wb.defined_names` omits them (verified), so `parse_workbook` never lists them for mapping and they can't be resolved. Templates using sheet-scoped names silently lose those mapping candidates. | `template_service.py:30`, `excel_writer.py:20` | Also enumerate `ws.defined_names` per sheet (qualified as `Sheet!Name`), resolve accordingly. |
| M2 | LLM extraction contract doesn't specify percent scale — a model returning `5` vs `0.05` for a percent-typed field is undetectable at validation time. Review screen would show 500%, so it's visible, but the contract should pin it. | `llm_extraction.py:82-112` | Add one line to the contract: percent-typed fields must be decimal fractions (0.05 = 5%). |
| M3 | LLM input silently truncated at 15,000 chars — long OMs lose later pages with no warning. | `llm_extraction.py:22,141` | Append a warning when `len(text) > _MAX_TEXT_CHARS`. |
| M4 | `parse_numeric("12%")` returns `12.0`, not `0.12` — any percent-formatted string cell parses at 100× scale. Currently no percent columns are deterministically parsed, so latent. | `excel_extractor.py:28` | Detect `%` and divide by 100, or return None and flag. |
| M5 | T-12 formats that report expenses as negatives produce negative expense fields (visible on review, but plausible to miss). | `t12_parser.py:135-167` | Normalize expense signs (abs) with a note, as done for vacancy. |
| M6 | Management fee $ converted to % using **GPR**; industry convention is % of EGI (collections). Overstates the denominator, understates the pct. | `extraction_service.py:256-258` | Convert using EGI when derivable; note the basis either way. |
| M7 | Annual-only operating statements (Total column, no month columns) can never pass the deterministic confidence gate (`(0 months + 1)/12 = 0.08 < 0.4`) and always fall to the LLM even when the table parsed perfectly. | `t12_parser.py:131`, `extraction_service.py:106` | Score confidence on parse quality (rows matched), not column count alone. |
| M8 | SensitivityPanel: empty min/max coerce via `Number('') === 0` and the run proceeds, sweeping from 0 (e.g. a 0% exit cap grid point). Labels show 0 so it's visible, but the run button shouldn't be enabled. | `SensitivityPanel.tsx:71-110` | Disable run until min/max parse to finite numbers. |
| M9 | No upload size limits — documents and templates are read fully into memory (`await file.read()`). | `documents.py:47`, `templates.py:42` | Cap at e.g. 50 MB with a 413. |
| M10 | Orphaned files accumulate in `backend/storage/generated/` after crashes/kills (a stale `.recalc-*` dir exists right now). | `generate.py`, `recalc_service.py`, `sensitivity_service.py` | Startup sweep deleting generated files older than a day. |
| M11 | `X-Generation-Outputs` missing from CORS `expose_headers` — works today only because the dev proxy makes requests same-origin; served cross-origin, sidebar outputs silently vanish. | `main.py:28` | Add the header to `expose_headers`. |
| M12 | Concurrent LibreOffice recalcs (generate + sensitivity, or two generates) can contend for the shared user-profile lock and fail intermittently (caught, surfaced as a warning — but flaky). | `recalc_service.py:29` | Per-invocation `-env:UserInstallation` scratch profile, or a process-wide lock. |
| M13 | Scanned PDFs are classified `other` with a stale "OCR isn't implemented yet" rationale; OCR exists in the extraction path but is never used for classification. | `document_classifier.py:188-197` | Run OCR (when available) before classifying; at minimum fix the message. |
| M14 | Scenario PUT ignores `kind`/`templateId` in the payload — accepted, silently not applied. | `scenarios.py:71-80` | Either apply or reject mismatched fields. |

## Low

| # | Issue | Location |
|---|---|---|
| L1 | `_coerce_value`'s date branch is dead code — `cell_type` is never passed at either call site (no date fields exist in the schema today, so latent). | `excel_writer.py:36-42,84,106` |
| L2 | Re-uploading identical content under a different filename returns the original record/filename (hash dedup) with no note. | `documents.py:50-52`, `templates.py:45-49` |
| L3 | OCR page splitting relies on `\f` separators pytesseract may not emit; multi-page OCR text can collapse into page 1. | `pdf_extractor.py:37-42` |
| L4 | Header-row detection scans only the first 8 rows; longer title blocks misdetect (self-healing via the LLM fallback). | `excel_extractor.py:72` |
| L5 | ScalarInput arrow-stepping from an empty draft starts from 0 rather than the field's previous value. | `ScalarInput.tsx:79-81` |

## API contract check (priority 4)

Compared `frontend/src/lib/api.ts` payloads/response types against
`backend/app/schemas.py` and `backend/app/routers/*`: templates, mappings,
generate (headers), scenarios (incl. the new `kind`/nullable fields), documents,
extraction, sensitivity, and market-context all line up. The only drift found is
M11 (CORS expose_headers) and M14 (PUT silently ignoring fields), both above.
