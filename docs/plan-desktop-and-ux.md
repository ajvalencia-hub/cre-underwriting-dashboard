# CRE Underwriting Dashboard: desktop packaging and UI/UX plan

Status: **approved and implemented** on branch `desktop-app-and-ux` (Gatekeeper: one documented
first-launch step; Quick Screen gets Copy share link). Every Critical and High finding below is
addressed, plus most Medium/Low ones. Not done, by choice: two-browser-tab last-write-wins,
arrow-key stepping in the main form, confirmation on table-row removal. Out of scope as agreed:
signing/notarization, auto-update, Windows. The sections below are the original proposal.
Target platform: macOS on Apple Silicon (this machine is arm64). Windows is out of scope.

---

## Phase 1: Packaging investigation

### 1. How Excel recalculation is actually done

**It's LibreOffice, run in headless mode as an external program.** Nothing in Python evaluates formulas.

- **Discovery.** `backend/app/services/soffice.py:21-31` looks for `soffice` or `libreoffice` on `PATH` using `shutil.which`, then tries two hard-coded **Windows** install paths. The result is stored once, at import time, in `LIBREOFFICE_BIN`. There is **no macOS path**.
- **How it's invoked.** `soffice.py:37-89` runs
  `soffice --headless -env:UserInstallation=<scratch profile> --convert-to xlsx --outdir <scratch> <file>`
  through `subprocess.run`, with a 60 s timeout and 3 attempts. The file is converted from xlsx to xlsx. That round trip makes LibreOffice recalculate every formula and save the cached values, which `openpyxl` (`data_only=True`) then reads back (`excel_writer.read_output_values`).
- **Where it's used:**

  | Path | File | If LibreOffice is missing |
  |---|---|---|
  | Generate with "Recalculate on server" | `routers/generate.py:88-96` | The workbook still downloads. A warning is added: *"Server-side recalc skipped: LibreOffice not found on PATH"*. **No template outputs come back to the app.** The file itself is still correct when opened in Excel, because `fullCalcOnLoad` is set. |
  | Sensitivity, template mode ("Verify via Excel template") | `routers/sensitivity.py:68-73` | Refused with a 400 error and a clear message |
  | IC memo as PDF (the docx is converted) | `routers/scenarios.py:175` | Refused; the .docx still works |

- **Not affected:** the native pro-forma engine, native sensitivity, Monte Carlo, the Excel model export, the .docx memo and the .pptx decks. None of these touch LibreOffice.

**Can it be bundled?** In practice, no. LibreOffice.app is about 700 MB to 1 GB. Its MPL-2.0 licence would allow redistribution, but putting a second signed app inside ours is awkward, and we'd own its security updates. A pure-Python formula evaluator (`formulas`, `pycel`) would bundle cleanly. It doesn't cover everything real underwriting models use (XIRR edge cases, data tables, iterative circular interest carry), and it would **change recalculation behaviour**, which is ruled out anyway. Its failure mode is a silently wrong number.

**What "desktop app" can realistically mean:** a self-contained app in which everything works except the three template-recalc paths above. Those need LibreOffice installed separately, as a documented prerequisite. The app has to detect it and explain clearly when it's missing.

**A problem that exists today and blocks this on Mac:** an app launched from Finder gets a minimal `PATH` (`/usr/bin:/bin:/usr/sbin:/sbin`). With a standard install (`/Applications/LibreOffice.app/Contents/MacOS/soffice`) or a Homebrew cask (`/opt/homebrew/bin/soffice`), `soffice.py` would **never find LibreOffice from the packaged app, even when it's installed.** Tesseract and Poppler (OCR) have the same problem (`extraction/ocr.py:21-59`, Windows fallbacks only).

- **Proposed fix, with no backend change:** before the launcher imports the backend, it prepends `/Applications/LibreOffice.app/Contents/MacOS`, `/opt/homebrew/bin` and `/usr/local/bin` (plus an optional folder chosen in Settings) to `PATH`. `shutil.which` then finds everything. Discovery and recalc code stay untouched.

### 2. Frontend build output, and serving it from FastAPI

- `npm run build` produces `frontend/dist/`: 500 KB in total (`index.html`, one 448 KB JS bundle and one 34 KB CSS file). It's fully static.
- FastAPI **already** serves it when `CRE_FRONTEND_DIST` is set (`main.py:126-134`, added for Docker). **Verified today:** I ran the backend on a scratch port with `CRE_FRONTEND_DIST` pointed at `dist/` and a scratch storage folder. `/`, the JS asset and `/api/deals` all returned 200 with no Vite server running.
- The frontend calls a relative `/api` (`api.ts:12`), so serving from the same origin just works, and CORS doesn't apply. `react-router` is installed but not used (tabs live in React state), so no SPA deep-link fallback is needed.

### 3. Python dependencies that are hard to freeze

These are in the current venv (246 MB unpacked, which includes pip, setuptools, pytest and pygments; none of those ship).

| Dependency | Problem | Handling |
|---|---|---|
| numpy, matplotlib, kiwisolver, contourpy | Native extensions. matplotlib loads fonts and `mpl-data` by path and builds a font cache on first run (several seconds). | PyInstaller hooks exist. Set `MPLCONFIGDIR` to the app cache folder, and let the startup screen cover the first run. |
| Pillow, lxml (python-docx, python-pptx) | Native libraries | Hooks exist |
| python-docx, python-pptx | Default template files loaded by path | `collect_data_files` |
| pdfplumber → pdfminer.six, **pypdfium2** | pdfminer loads CMap data files; pypdfium2 ships a native `libpdfium` dylib | Hooks in pyinstaller-hooks-contrib. **Test PDF extraction in the built app.** |
| reportlab | Fonts loaded by path | `collect_data_files` |
| uvicorn[standard]: uvloop, httptools, watchfiles, websockets | Loaded dynamically by name, so PyInstaller misses them | The launcher builds `uvicorn.Config(loop="asyncio", http="h11")` directly, so the optional native parts aren't needed. `--reload` isn't used. |
| pydantic_core, jiter (anthropic), cryptography, cffi | Native, but wheels freeze cleanly | None needed |
| pytesseract, pdf2image | Wrappers around **external** programs (Tesseract, Poppler) | Same as LibreOffice: optional, detected at runtime |
| `app/data/input_schema.json` | Loaded by path from `__file__` (`config.py:30`, `memo_service.py:24`, `goal_seek.py:20`) | Works under PyInstaller as long as it's added as a data file |
| pytest | Listed in `requirements.txt` | Excluded from the bundle |

**Build interpreter:** the README says Python 3.12+. Building with this Mac's Anaconda 3.10 would pull Anaconda's libraries into the bundle. **I recommend building from a Homebrew `python@3.12` venv**, which is a build-time tool only.

### 4. API keys and credentials

- **None are required.** All six are optional: FRED, Census, BEA, HUD, BLS and Anthropic. Every consumer degrades gracefully.
- **How they're supplied today:** `config.py:7` runs `load_dotenv(BACKEND_ROOT / ".env")`, and the values are then read into module constants **once, at import**. Consumers copy them by value (`from app.config import CENSUS_API_KEY`).
- **Why that breaks once packaged:**
  1. In a frozen app, `BACKEND_ROOT/.env` points inside the app bundle. Users can't find or edit it, and changes would be wiped by any rebuild.
  2. Because the values are copied at import, changing a key requires restarting the backend.
- **Plan:** in desktop mode, the launcher reads keys from the **macOS Keychain** and puts them in `os.environ` **before** importing the backend. The Settings screen writes to the Keychain and offers "Restart to apply". `.env` loading stays exactly as it is for the browser dev workflow.

### 5. Where the app writes files

- Everything goes under `STORAGE_ROOT` (`config.py:10-23`): the SQLite database, templates, documents, generated files, backups and cache (`data_sources/source_cache.py:19`, `fred.py:46`). LibreOffice scratch folders are created next to the file being converted, which is inside `generated/`. **The default is `backend/storage` inside the repo**, which in a frozen app means inside the bundle or a temp folder.
- `CRE_STORAGE_ROOT` already overrides this (Docker uses it). The launcher will set it to `~/Library/Application Support/CRE Underwriting/`, logs will go to `~/Library/Logs/CRE Underwriting/`, and `MPLCONFIGDIR` to `~/Library/Caches/CRE Underwriting/`.
- Folders are created at import time (`config.py:22`), so the environment variables must be set before the backend is imported. The launcher does that.
- **Browser-side storage also has to survive.** The frontend keeps the active deal id, theme and saved pipeline views in `localStorage`. pywebview must run with `private_mode=False` and a fixed `storage_path`. Otherwise each launch starts on a blank deal selection.

---

## Phase 2: UI/UX audit (ranked by user impact)

Sources: my own reading of the template and recalc path, plus a full-frontend audit by a helper agent. **I re-checked every Critical item below against the code.**

### Critical: can silently produce a wrong number or lose work

**T1. Generate uses the *saved* mapping profile, not the one on screen.**
- **Where:** `GeneratePanel` sends `mappingProfileId` (`GeneratePanel.tsx:120-125`). Edits in `TemplateUpload` live only in local state until the user clicks "Update Mapping Profile" (`TemplateUpload.tsx:228-248`). Nothing marks unsaved changes.
- **Impact:** the analyst re-maps a cell, goes to Deal Inputs, clicks Generate, and gets the old mapping. The screen they just looked at says otherwise.

**T2. Mapped fields left blank are skipped silently, so the template's placeholder value stays in the cell.**
- **Where:** `excel_writer.inject_values:94-96` skips mapped fields whose value is `None`, `""` or `[]`, and adds **no warning**. The UI reports only "Wrote N field(s)" (`GeneratePanel.tsx:328`). It doesn't say which N, or which mapped fields weren't written.
- **Impact:** the recalculated IRR includes the template's leftover number for, say, vacancy, and nothing says so.

**T3. Unmapped inputs are invisible when the user generates.**
- **Where:** `TemplateUpload.tsx:233-242` reports "N required field(s) still unmapped" only after saving, and only for the schema's `required` set. At Generate time, nothing lists which inputs *with values on this deal* have no target cell.
- **Impact:** the analyst enters a value, it never reaches the model, and the output reflects the template default.

**T4. Nothing catches a percentage or unit mismatch between the app and the template cell.**
- **Where:** percentages are stored as fractions (0.055) and written raw (`_coerce_value` passes them through). If a template cell expects `5.5`, or holds a monthly figure where the app has an annual one, the result is off by 100× or 12×.
- **Why it's hard to spot:** the mapping screen never shows the cell's current value or number format next to the value that will be written, so there's nothing to compare against. (The injection logic stays unchanged. The fix is to show the comparison.)

**T5. Formula-cell protection is forgotten after a reload.**
- **Where:** `formulaWarnings` is only filled by a manual pick (`TemplateUpload.tsx:206-211`) and is reset when a profile loads (`:134`). Auto-matched or saved mappings pointing at formula cells show no ⚠.
- **What happens:** at generate time the backend correctly refuses to overwrite a formula cell, but the input then silently doesn't reach the model. The only sign is an amber line in the footer.

**C1. Results never go stale.**
- **Where:** results clear only when a deal loads (`App.tsx:185-189`). Editing a field, applying a preset, "Send to Deal Inputs", applying an extraction, loading a scenario, or applying a goal seek all leave the sidebar, the footer debt tables and the cash-flow statement showing numbers for the *previous* inputs, with nothing marking them.

**C2. An old server result permanently outranks a newer native compute.**
- **Where:** the sidebar's order of precedence is server > native > estimate (`App.tsx:507-518`). `serverOutputs` is cleared only on deal load.
- **Impact:** after one Generate with recalc, later "Compute (native)" runs don't change those metrics on screen.

**C3. A failed compute leaves the previous numbers in the sidebar.**
- **Where:** `GeneratePanel.tsx:105-108`. The error appears only in the footer.

**C4. Formatted entries are thrown away without a word.**
- **Where:** `ScalarInput.tsx:47-48` runs `Number(raw.replace(/,/g,''))`, and anything that isn't a finite number is dropped. The field silently goes back to its previous value.
- **Affected inputs:** `$12,500,000`, `5.50%` (the usual paste from Excel), `(250)`, `1.25M`.

**C5. Currency fields display rounded to whole dollars.**
- **Where:** `ScalarInput.tsx:26`. $32.50/SF shows as "33" and $0.25/SF as "0". The stored value is correct; the display misstates it.

**C6. Four different percentage conventions.**
- The main form uses whole numbers. The Risk panel uses fractions (`RiskPanel.tsx:256-264`). `opexLineItems.amount` and `escalationValue` mix $ and fractions. Sensitivity bounds are whole numbers with no unit label.
- **Impact:** 100× entry errors go unflagged.

**C7. Quick Screen clamps values to limits without saying so.**
- **Where:** `commit` clamps to min/max (`ScalarInput.tsx:52-53`). The range warning is computed from the already-clamped value, so it can never show.
- **Example:** a 2.75% exit cap becomes 3%, and the verdict changes.

**C8. Edits can be lost with no warning.**
- **Failed save plus deal switch:** after a failed autosave, nothing retries automatically. If the user then switches deals and the flush fails again, the next edit replaces the queued save and the old deal's edits are dropped (`dealPersistence.ts:73-86`, `App.tsx:271-280`).
- **No close guard:** there's no `beforeunload` handler, so closing within 2 s of an edit loses it. A value still being typed isn't committed until the field loses focus.

**C9. Results carry over between deals.**
- Sensitivity grids, Monte Carlo runs, the hold sweep, the footer debt block and the extraction review aren't reset when the deal changes. Deal A's sensitivity run can be saved onto deal B's scenario and end up in B's IC memo.

**C10. Scenario outputs may not match the scenario's inputs.**
- **Where:** saving a scenario stores whatever outputs were last computed (`ScenariosPanel.tsx:95-98`). If those outputs are stale (C1), the comparison view pairs them with inputs they didn't come from.

**C11. URL parameters overwrite the saved Quick Screen napkin.**
- **Where:** on first load, the napkin in the URL overwrites the active deal's saved napkin (`App.tsx:198-199, 220-222`). The acquisition napkin is never saved to the deal at all.

### High: blocks or confuses the core flow

- **M1. The mapping screen doesn't show coverage at a glance.**
  - All 18+ sections start collapsed (`<details>`) and show no per-section mapped or unmapped count.
  - A named range is displayed by name only; the cell it points to isn't shown.
  - The grid preview sits *above* a long field list, so after clicking "Pick cell" low in the list you have to scroll back up to the grid.
  - The grid shows at most 60 rows × 30 columns (`template_service.py:57`), so cells below row 60 can't be picked.
  - Cell values appear raw, without their number format.
- **M2. Destructive actions on the mapping screen have no confirmation.** Deleting a template or a mapping profile happens on one click (`TemplateUpload.tsx:137-163`). The same is true for scenarios, documents, table rows and presets elsewhere.
- **M3. The Template tab doesn't restore after a refresh.** The deal restores its active template and profile at the App level (`App.tsx:190-192`), but `TemplateUpload`'s own `template` state starts empty. After a refresh, Deal Inputs says "mapping profile ready" while the Template tab shows nothing to review.
- **H1. "Send to Deal Inputs" overwrites up to 15 fields with no preview.** This can include flipping `dealType`.
- **H2. Compute errors show raw field ids** ("purchasePrice, grossPotentialRent…") in the footer, not tied to the fields. The backend already returns a `missing` array, which `api.ts:14-22` discards. FastAPI's 422 validation errors appear only as "422 Unprocessable Entity".
- **H3. The form's `*` markers don't match what the engine requires, and Purchase Price is in section 9 of 18.**
- **H4. There are no headline metrics.** The sidebar lists 44 metrics at equal weight, and Min DSCR is below the fold. Debt sizing and stress results render in the pinned footer, not next to the returns.
- **H5. Compute exists only on the Deal Inputs tab, but the app opens on Quick Screen.** On Quick Screen, the sidebar shows full-model numbers that don't respond to the napkin.
- **H6. About a dozen actions fail with no message:** deal switch, rename, delete, export, status changes, linking a template, FileCabinet actions.
- **H7. Results race the inputs.** A compute that returns after a deal switch or an edit is applied without checking which deal or input version it belongs to.

### Medium and Low (summary)

- **Medium:**
  - A percentage typed as 0.055 is accepted as 0.055%.
  - Validation messages use fraction units, and `min`/`max` never reach the main form's inputs.
  - The "API connected" check runs only once, at boot.
  - Goal seek appears only on hover and accepts an empty target.
  - Tab numbers in help text are wrong ("1. Template", "5. Scenarios").
  - Around 40 tab stops come before the first input.
  - Section links don't open collapsed sections.
  - The Deck and IC deck links navigate the app window itself.
  - Two tabs on the same deal: the last write wins.
  - Refreshing loses your place (the active tab isn't stored anywhere).
- **Low:**
  - Labels aren't linked to their inputs.
  - Arrow-key stepping doesn't work in the main form.
  - "Development Spread" is named in basis points but shows as a percentage.
  - A new deal shows "Required" before the user has touched anything.

---

## Phase 3: Combined plan

### (a) Packaging decision

Whichever shell we choose, a frozen Python backend of about 170 MB (numpy, matplotlib, lxml, Pillow) makes up most of the size. That erases the "smallest binary" advantage of Tauri.

| | **pywebview + PyInstaller** | Tauri + Python sidecar | Electron + Python child process |
|---|---|---|---|
| App size (est.) | ~170-220 MB .app, ~70-90 MB zipped | ~180-230 MB (a ~10 MB shell plus the same frozen sidecar) | ~400-450 MB (Chromium plus the sidecar) |
| Build toolchain | Python only: one `.spec` file and one build script | Rust, the Tauri CLI, PyInstaller, a sidecar port handshake, capability config | Node, electron-builder, PyInstaller, child-process management |
| Webview engine | WKWebView (Safari engine) | WKWebView (the same) | Bundled Chromium |
| Backend lifecycle | **Runs inside the app's own process** (uvicorn on a thread). No separate backend process, so nothing can be orphaned. | Separate process; needs kill-on-exit and a watchdog that stops Python if the parent dies | Separate process; same watchdog needs; Electron crashes can orphan Python |
| Native dialogs | `window.create_file_dialog` via the JS bridge | Tauri dialog plugin | `dialog.showOpenDialog` via IPC |
| Keychain | Python `keyring` (native macOS backend) | Rust keyring crate or the Python side | keytar/safeStorage, or the Python side |
| If the recalc tool can't be frozen | **The same for all three.** LibreOffice is an external program found at runtime; no shell can bundle it sensibly. The PATH handling and missing-tool UI are identical. | same | same |
| Maintenance | Lowest. One language and a small surface. pywebview is a smaller project, which is its main risk. | Two languages, fast-moving Rust dependencies | Frequent Chromium security updates, heaviest footprint |
| Keeps browser dev workflow | Yes: the same FastAPI app and the same SPA | Yes | Yes |

**Recommendation: pywebview + PyInstaller**, built as an `.app` folder (onedir), **not onefile**, because onefile unpacks to a temp folder on every launch, which takes seconds.

**Launch sequence:**
1. The launcher sets the environment: storage folders, PATH additions, and Keychain keys loaded into `os.environ`.
2. It takes a single-instance lock.
3. It opens a socket on `127.0.0.1:0`, so the OS assigns a free port with no race.
4. It starts `uvicorn.Server` on a thread against that socket.
5. It opens the window immediately with an inline "Starting…" page.
6. It polls `/api/health`, then loads the app.
7. On failure it shows a readable error in the window, with the log path and a "Copy details" button.

**On quit:** it signals `server.should_exit`, joins the server thread, and terminates any child `soffice` process that's still running (found with `pgrep -P <pid>`; no new dependency).

**New dependencies (need your OK):**
- `pywebview` (the window and dialogs; brings in `pyobjc` on macOS)
- `keyring` (Keychain storage)
- `pyinstaller` (build-time only)
- **No new frontend dependencies.**

**Two items for your decision:**

1. **Gatekeeper conflicts with the definition of done.** An unsigned app that arrives by browser download, AirDrop or email is quarantined. On macOS 15 and later, the colleague can't just double-click it; they have to go to System Settings → Privacy & Security → **Open Anyway** once. That's the "without being told how" test failing on step one.
   - (a) Bring signing and notarization into scope. This is the only clean fix.
   - (b) Accept one documented first-launch step.
   - (c) Transfer by USB or a shared drive, which usually doesn't set the quarantine flag. This is fragile.
2. **LibreOffice stays a separate install.** The app will show its status ("Template recalculation: available / not installed → how to install"). In Settings the user can point to a custom install location.

**Small backend additions** (outside the engine, injection and recalc code; they need your OK):
- A **read-only mapping-preview endpoint.** For each mapping it returns the resolved `Sheet!A1` (named ranges resolved), the cell's current value and number format, whether it contains a formula, whether it's a merged or multi-cell range, and the value that would be written. It reuses the existing resolution helpers **without modifying** `excel_writer.py`. This powers T1-T5 and M1.
- The grid endpoint also returning each cell's `number_format`, and a larger or paged row window. This is presentation data only.
- A **per-launch access token.** Any web page open in the user's browser can send requests to `127.0.0.1:<port>`. The launcher would generate a random token and a small middleware would require it on `/api/*`. It applies in desktop mode only, and the dev workflow is untouched.

### (b) UI/UX work

**High-impact, low-risk (no component restructuring):**

1. **Staleness (C1, C3, H7).** Add an input-version counter. Every result is tagged with the version that produced it. Stale results are dimmed and show a "Inputs changed — Compute" banner (sidebar, footer, Cash Flow). A failed compute marks results as failed rather than keeping them. Responses for an older deal or version are discarded.
2. **Result source (C2).** Show the *most recent* result, with its source and time ("Native · 14:02" / "Excel template · 13:55"), instead of always ranking server above native. **This changes the documented "server > native" ordering, so it needs your OK.**
3. **Numeric entry (C4, C5, C7).**
   - One parser that accepts `$`, `%`, commas, `(neg)`, K/M/B suffixes and the tabs and newlines Excel adds when you copy a cell.
   - Input it can't parse keeps the typed text and shows an inline error instead of silently reverting.
   - Out-of-range values show an error instead of being clamped.
   - Currency displays with cents when the value has cents.
   - A warning when a rate-type percentage is entered below 1 ("Did you mean 5.5%?").
4. **Mapping-screen quick wins (T1, T5, M2).**
   - An "Unsaved mapping changes" marker. Generate is blocked with "Save mapping first" while edits are unsaved.
   - Formula-cell ⚠ markers derived from the preview endpoint, so they survive a reload.
   - Confirmations on deleting a template or profile.
   - Per-section "3/7 mapped · 1 required missing" in each collapsed section header.
   - Corrected tab numbers in help text.
5. **Errors (H2, H6).**
   - Carry the `missing` array through, turn ids into field labels, and add "Go to field" links that open the right section and highlight the field.
   - Parse FastAPI 422 `detail` arrays into readable messages.
   - One app-wide error toast for actions that currently fail silently.
   - Replace the hard-coded "Is FastAPI running at 127.0.0.1:8000" message.
6. **Autosave (C8).**
   - Retry automatically on a timer.
   - Block a deal switch while that deal's save is failing, and explain why.
   - Commit the focused field's draft before a switch or close.
   - Close guard: `beforeunload` in the browser; pywebview's `closing` event on desktop.
7. **Per-deal reset (C9).** Clear sensitivity, Monte Carlo, hold sweep, footer debt and extraction-review state when the active deal changes.

**Changes that need component restructuring:**

1. **Mapping coverage view (the main fix for T2-T4, M1).** A table becomes the primary view of the Template tab:

   | Input | Value on this deal | Target cell | Cell now holds (with its format) | Will write | Status |

   Status is one of: ✓ ok · unmapped · blank, so the template default will be kept · formula cell, will be skipped · multi-cell range · unresolved · **possible unit mismatch**.

   A unit mismatch is flagged when the app value is a percentage and the cell's format isn't `%`, or when the magnitudes differ by roughly 100× or 12×. The same checks run as a pre-flight step before Generate. After Generate, a written/skipped report lists every field, replacing "Wrote N field(s)".

   The cell picker becomes a sticky side-by-side grid with a "Go to cell" box, so rows beyond 60 can be reached. The Template tab also restores the deal's template on load (M3).
2. **Results hierarchy (H4).**
   - A pinned headline block in the sidebar: levered IRR, unlevered IRR, equity multiple, Min DSCR, yield on cost or going-in cap (by deal type), and year-1 cash-on-cash.
   - The governing debt constraint and the base-case DSCR move from the footer into this block.
   - The remaining metrics go into collapsible groups, with not-applicable metrics hidden.
   - No green/red hurdle colours unless you want user-set hurdles. I won't invent thresholds.
3. **Form ordering and readiness (H3).**
   - Change the display order in the frontend only, so Deal Basics → Acquisition/Development Details → Operating Income come first.
   - Add a "Ready to compute" checklist built from the engine's `missing` list.
   - `input_schema.json` is **not** edited; see below.
4. **Previews (H1).** "Send to Deal Inputs" shows a before/after diff, reusing the Presets diff component.
5. **Scenarios (C10).** Saving a scenario while results are stale asks "Compute first?", and the comparison view flags scenarios whose outputs were stale when they were saved.

**Things I recommend against:**

- **Automatic recompute as you type.** Template recalc takes seconds per run and writes files. Even for the native engine, a clear stale marker plus one Compute (with ⌘↩ as a shortcut) makes it clearer which numbers are current than numbers that shift mid-entry would.
- **Editing `input_schema.json`** to reorder sections, change `required` flags or split the mixed $/% fields. The schema drives auto-matching, the memo, the export and saved deals, so editing it alters existing capabilities. Presentation-layer reordering and labels get the same benefit.
- **Changing how values are stored** to unify percentages (C6). Instead, the Risk panel and Sensitivity bounds get display conversion with a visible `%`. The mixed $/fraction fields get explicit unit hints and a magnitude warning.
- **Extracting a shared Button/Modal component library.** That's restyling without a usability reason, and it risks the dark-mode class list (`index.css:18-106`). New UI will reuse the existing class conventions.
- **Hurdle colouring with thresholds I pick myself.**
- **Browser drag-and-drop upload zones, or any custom download UI.** Native dialogs replace them.

### (c) Sequencing

**Packaging goes first, but only the skeleton and the file bridge**, so the template-mapping work is built once against native dialogs.

1. **Launcher**: app-data folders, PATH handling, in-process server on a free port, startup and error screens, clean shutdown, single-instance lock. *Check it with `python desktop/launcher.py`.*
2. **PyInstaller spec and `desktop/build_mac.sh`**, producing a double-clickable `.app`.
3. **`frontend/src/lib/platform.ts`**: `pickFile()` and `saveFile()`. On desktop these go through the pywebview bridge; in a browser they fall back to exactly today's `<input type=file>` and blob download.
   - Migrate the template open and Generate save first, then the other 5 file inputs and 8 download sites.
   - The direct server links (Share, Deck, IC deck, portfolio CSV) become fetch + `saveFile`, which also fixes the Deck links navigating the app window away.
4. **Settings**: Keychain keys (desktop only; the browser keeps its `.env` instructions), LibreOffice/Tesseract status, a custom install-folder setting, "Restart to apply".
5. **README**: prerequisites prominently at the top; how to build.

Then UI work in the order you gave, with one proposed change:

6. **Mapping**: quick wins (T1, T5, M2), then the preview endpoint, then the coverage view, pre-flight check and post-generate report.
7. **Errors and empty states.**
8. **Staleness (C1-C3, H7). I propose moving this ahead of input ergonomics.** It's small, and it's the other main source of silently wrong numbers.
9. **Input ergonomics** (the numeric parser and ordering).
10. **Results hierarchy.**
11. **Persistence** (C8, C9, C11, M3).

**UI work that packaging makes unnecessary or invalidates:**

- **Don't build:** a better browser file picker or drag-and-drop for templates, a download-location UI, or "where did my file go" help. Native dialogs cover all of these. The existing `<input type=file>` stays as the browser fallback, unchanged.
- **Keeping the tab in the URL (H5)** doesn't help on desktop, since there's no address bar and refreshes are rare. Remember the last tab in `localStorage` instead, which works in both.
- **Quick Screen URL sharing** (an existing feature) has no address bar to copy from on desktop. It keeps working in the browser. On desktop I'd add a "Copy share link" button, **or you tell me to leave it browser-only.** Either way, C11 (a URL silently overwriting the saved napkin) is fixed in both.
- **The boot error text** ("Is FastAPI running at 127.0.0.1:8000?") becomes a generic "can't reach the backend" message. On desktop, the launcher's own startup and error screens take over.
- **Cmd+K** is fine: pywebview installs no conflicting menu shortcut. **Native `confirm()`** works in pywebview's WKWebView; I'll verify it in the built app.

### Effort estimates for out-of-scope items (not implemented)

| Item | Estimate | Notes |
|---|---|---|
| Code signing + notarization (macOS) | 1-2 days, plus the $99/yr Apple Developer Program | Hardened runtime entitlements for the embedded Python; every nested `.so`/`.dylib` signed; `notarytool` plus stapling. **This is the only real fix for the Gatekeeper conflict above.** |
| Auto-update | 1 day for "a new version is available" with a download link; 3-5 days for true in-place updates | Sparkle through pyobjc is awkward |
| Windows build | 3-5 days | WebView2 runtime check, PyInstaller on Windows, Credential Manager (keyring supports it), an installer (Inno Setup). The LibreOffice and Tesseract Windows paths already exist. Long-path issues are already noted in `soffice.py`. |
| Intel Mac / universal2 | 1-2 days | A separate Intel build is simpler than universal2, which needs every wheel to be universal |

---

## What I need from you before writing code

1. **Approve the packaging choice** (pywebview + PyInstaller, onedir `.app`) and the dependencies: `pywebview`, `keyring`, `pyinstaller` (build only), and a Homebrew `python@3.12` build venv.
2. **Gatekeeper:** (a) bring signing in scope, (b) accept one documented first-launch step, or (c) USB or shared-drive distribution.
3. **Approve the three small backend additions:** the mapping-preview endpoint, `number_format` and paging on the grid endpoint, and the desktop access-token middleware. The engine, injection and recalc code stay untouched.
4. **Approve changing the result-source rule** from "server > native" to "most recent wins, labelled".
5. **Approve moving staleness ahead of input ergonomics.**
6. **Quick Screen URL sharing on desktop:** add a "Copy share link" button, or leave it browser-only?
