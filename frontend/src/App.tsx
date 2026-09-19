import { useEffect, useMemo, useRef, useState } from 'react'
import DealInputForm from './components/DealInputForm'
import GeneratePanel from './components/GeneratePanel'
import Layout from './components/Layout'
import CashFlowTab from './pages/CashFlowTab'
import CompsPage from './pages/CompsPage'
import PipelinePage from './pages/PipelinePage'
import PresetsPanel from './components/PresetsPanel'
import HistoryDrawer from './components/HistoryDrawer'
import Documents from './pages/Documents'
import QuickScreen from './pages/QuickScreen'
import PortfolioPage from './pages/PortfolioPage'
import RiskPanel from './pages/RiskPanel'
import ScenariosPanel from './pages/ScenariosPanel'
import SensitivityPanel from './pages/SensitivityPanel'
import SettingsPage from './pages/SettingsPage'
import TemplateUpload from './pages/TemplateUpload'
import {
  createDeal,
  deleteDeal,
  exportDeal,
  fetchDeal,
  fetchDeals,
  bulkUpdateDealStatus,
  fetchHealth,
  fetchInputSchema,
  fetchTemplate,
  importDeal,
  updateDeal,
  type DealExportBundle,
} from './lib/api'
import {
  ACTIVE_DEAL_STORAGE_KEY,
  createAutosaver,
  hydrateDealState,
  serializeDealInputs,
  type Autosaver,
  type AutosaveState,
} from './lib/dealPersistence'
import { formatValue } from './lib/formatValue'
import { flattenFields } from './lib/schemaFields'
import { isVisible } from './lib/visibility'
import {
  ACQUISITION_QUICK_SCREEN_DEFAULTS,
  QUICK_SCREEN_DEFAULTS,
  QUICK_SCREEN_FULL_MODEL_ONLY_OUTPUT_IDS,
  computeAcquisitionQuickScreen,
  computeQuickScreen,
  mapAcquisitionQuickScreenToOutputMetrics,
  mapQuickScreenToDealInputs,
  mapQuickScreenToOutputMetrics,
  type AcquisitionQuickScreenInputs,
  type QuickScreenInputs,
} from './lib/quickScreenMath'
import type { Deal } from './types/deal'
import CommandPalette from './components/CommandPalette'
import CriticalDatesEditor from './components/CriticalDatesEditor'
import FileCabinet from './components/FileCabinet'
import FileChooser, { type FileChooserHandle } from './components/FileChooser'
import { saveOutput } from './lib/saveOutput'
import { showToast, toastError } from './lib/toast'
import { isDesktop, reportUnsavedToShell } from './lib/platform'
import MetricsSidebar from './components/MetricsSidebar'
import ResultsStatus from './components/ResultsStatus'
import { focusUnparsedEntry, goToField } from './lib/goToField'
import { orderSections } from './lib/sectionOrder'
import { presetDiff } from './lib/presetDiff'
import { inputsKey, isStale, latestStamp, pickMetric } from './lib/resultFreshness'
import { useComputeResults } from './lib/useComputeResults'
import { parseShareLink, shareParams, type SharedScreen } from './lib/shareLink'
import GoalSeekModal from './components/GoalSeekModal'
import OmWizard from './components/OmWizard'
import { dateStatus, readCriticalDates, sortByDate } from './lib/criticalDates'
import { dealTypeOf, type DealType } from './lib/dealStages'
import type { InputSchema, OutputMetric } from './types/schema'
import type { TemplateSummary } from './types/template'
import { clearProvenance, recordProvenance, sameSourceFor, type FieldProvenance } from './lib/provenance'

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; schema: InputSchema; apiOk: boolean }

const TABS = [
  'pipeline',
  'quickscreen',
  'documents',
  'setup',
  'dashboard',
  'cashflow',
  'sensitivity',
  'risk',
  'scenarios',
  'comps',
  'portfolio',
  'settings',
] as const
type Tab = (typeof TABS)[number]

// Left-rail module navigation. Grouped (workflow steps under "This deal"),
// no step numbers — "0." / "5b." implied a strict order that doesn't exist.
const NAV_GROUPS: { label: string; items: readonly (readonly [Tab, string])[] }[] = [
  {
    label: 'Portfolio',
    items: [
      ['pipeline', 'Deals'],
      ['portfolio', 'Portfolio'],
      ['comps', 'Comps'],
    ],
  },
  {
    label: 'This deal',
    items: [
      ['quickscreen', 'Quick Screen'],
      ['documents', 'Documents'],
      ['setup', 'Template & Mapping'],
      ['dashboard', 'Deal Inputs'],
      ['cashflow', 'Cash Flow'],
      ['sensitivity', 'Sensitivity'],
      ['risk', 'Risk'],
      ['scenarios', 'Scenarios'],
    ],
  },
  { label: '', items: [['settings', 'Settings']] },
]

// Reopen where the user was (per browser / desktop profile). Storage can be
// unavailable (private mode); the app then just starts on Quick Screen.
const LAST_TAB_KEY = 'cre.lastTab'
const HEALTH_POLL_MS = 30_000
function loadLastTab(): Tab {
  try {
    const stored = localStorage.getItem(LAST_TAB_KEY)
    return (TABS as readonly string[]).includes(stored ?? '') ? (stored as Tab) : 'quickscreen'
  } catch {
    return 'quickscreen'
  }
}

function blockedByUnparsedEntry(): boolean {
  if (!focusUnparsedEntry()) return false
  showToast({
    kind: 'error',
    message: "Not computed — a field has an entry that isn't a number",
    detail: 'Fix or clear it first; otherwise its previous value would be used.',
  })
  return true
}

function defaultValuesFor(schema: InputSchema): Record<string, unknown> {
  const values: Record<string, unknown> = {}
  for (const field of flattenFields(schema)) {
    if (field.default !== undefined) values[field.id] = field.default
  }
  return values
}

const AUTOSAVE_LABEL: Record<AutosaveState, string> = {
  idle: '',
  pending: 'Saving…',
  saving: 'Saving…',
  saved: 'Saved',
  error: 'Not saved — retrying automatically',
}

function App() {
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [tab, setTab] = useState<Tab>(loadLastTab)
  useEffect(() => {
    try {
      localStorage.setItem(LAST_TAB_KEY, tab)
    } catch {
      // storage unavailable — not remembering the tab is harmless
    }
  }, [tab])
  const [formValues, setFormValues] = useState<Record<string, unknown>>({})
  const [activeTemplate, setActiveTemplate] = useState<TemplateSummary | null>(null)
  const [activeMappingProfileId, setActiveMappingProfileId] = useState<string | null>(null)
  const [mappingUnsaved, setMappingUnsaved] = useState(false)
  const [quickScreenInputs, setQuickScreenInputs] = useState<QuickScreenInputs>(QUICK_SCREEN_DEFAULTS)
  // The acquisition-side napkin (lifted here for URL sharing + sidebar
  // estimates, same as the development inputs above).
  const [acquisitionQuickScreenInputs, setAcquisitionQuickScreenInputs] =
    useState<AcquisitionQuickScreenInputs>(ACQUISITION_QUICK_SCREEN_DEFAULTS)
  const [quickScreenMode, setQuickScreenMode] = useState<'development' | 'acquisition'>('development')
  // A Quick Screen link the app was opened with, waiting for the user to
  // open it (it replaces this deal's napkin) or dismiss it.
  const [sharedFromLink, setSharedFromLink] = useState<SharedScreen | null>(null)
  // The saved scenario the working inputs were loaded from (header chip).
  const [loadedScenario, setLoadedScenario] = useState<{ name: string; key: string } | null>(null)
  // J7: which sidebar metric the Goal Seek modal is open for.
  const [goalSeekMetric, setGoalSeekMetric] = useState<OutputMetric | null>(null)
  // J10: OM-to-deal wizard visibility.
  const [omWizardOpen, setOmWizardOpen] = useState(false)
  // J11: critical-dates editor visibility.
  const [datesEditorOpen, setDatesEditorOpen] = useState(false)
  // J13: Cmd+K command palette.
  const [paletteOpen, setPaletteOpen] = useState(false)
  // Typed New Deal chooser (header button popover).
  const [newDealMenuOpen, setNewDealMenuOpen] = useState(false)

  const [deals, setDeals] = useState<Deal[]>([])
  const [activeDealId, setActiveDealId] = useState<string | null>(null)
  const [autosaveState, setAutosaveState] = useState<AutosaveState>('idle')
  const [renamingName, setRenamingName] = useState<string | null>(null)
  const [importPreview, setImportPreview] = useState<DealExportBundle | null>(null)
  const [importNotice, setImportNotice] = useState<string | null>(null)
  const importInputRef = useRef<FileChooserHandle>(null)

  const activeDealIdRef = useRef<string | null>(null)
  // Computed results (engine + Excel read-back), each stamped with the deal
  // and inputs it came from — see lib/resultFreshness.ts.
  const results = useComputeResults(activeDealIdRef)
  const hydratedRef = useRef(false)
  // JSON of the state as last hydrated/saved — suppresses the no-op autosave
  // that hydration itself would otherwise trigger.
  const lastPersistedJsonRef = useRef('')
  const autosaverRef = useRef<Autosaver<{ dealId: string; inputs: Record<string, unknown> }> | null>(null)
  if (autosaverRef.current === null) {
    autosaverRef.current = createAutosaver(async ({ dealId, inputs }) => {
      await updateDeal(dealId, { inputs })
    })
  }

  const quickScreenResults = useMemo(() => computeQuickScreen(quickScreenInputs), [quickScreenInputs])
  const acquisitionQuickScreenResults = useMemo(
    () => computeAcquisitionQuickScreen(acquisitionQuickScreenInputs),
    [acquisitionQuickScreenInputs],
  )
  // Sidebar estimates follow the ACTIVE napkin.
  const quickScreenOutputs = useMemo(
    () =>
      quickScreenMode === 'acquisition'
        ? mapAcquisitionQuickScreenToOutputMetrics(
            acquisitionQuickScreenResults, acquisitionQuickScreenInputs,
          )
        : mapQuickScreenToOutputMetrics(quickScreenResults, quickScreenInputs),
    [quickScreenMode, quickScreenResults, quickScreenInputs,
     acquisitionQuickScreenResults, acquisitionQuickScreenInputs],
  )
  const quickScreenFullModelOnlyIds = useMemo(
    () => new Set<string>(QUICK_SCREEN_FULL_MODEL_ONLY_OUTPUT_IDS),
    [],
  )

  // Freshness of what's on screen vs the inputs on screen.
  const currentInputsKey = useMemo(() => inputsKey(formValues), [formValues])
  const nativeResponse = results.native?.response ?? null
  const nativeStale = results.native ? isStale(results.native.stamp, currentInputsKey, activeDealId) : false
  const excelStale = results.excel ? isStale(results.excel.stamp, currentInputsKey, activeDealId) : false
  const resultSets = useMemo(
    () => [
      ...(results.native ? [{ stamp: results.native.stamp, outputs: results.native.response.outputs as Record<string, unknown> }] : []),
      ...(results.excel ? [results.excel] : []),
    ],
    [results.native, results.excel],
  )
  const latestResult = latestStamp(results.native?.stamp ?? null, results.excel?.stamp ?? null)
  const anyStale = (results.native !== null && nativeStale) || (results.excel !== null && excelStale)
  // What Scenarios saves as "the current results": the most recent value of
  // each metric, whichever source produced it.
  const latestOutputs = useMemo(() => {
    const merged: Record<string, unknown> = {}
    for (const metric of state.status === 'ready' ? state.schema.outputs : []) {
      const picked = pickMetric(metric.id, resultSets)
      if (picked) merged[metric.id] = picked.value
    }
    return merged
  }, [resultSets, state])
  const formValuesRef = useRef(formValues)
  formValuesRef.current = formValues
  const computeNow = () => {
    if (blockedByUnparsedEntry()) return
    void results.compute(formValuesRef.current)
  }

  // Cleanup only unsubscribes — never dispose here: StrictMode's simulated
  // remount would permanently kill the ref'd autosaver otherwise.
  useEffect(() => autosaverRef.current!.subscribe(setAutosaveState), [])

  // Closing with edits the server hasn't accepted loses them: ask first.
  // Browser: the standard leave-page prompt. Desktop: the window's quit
  // confirmation (Cmd+Q / close button), switched on through the bridge.
  const hasUnsavedWork = autosaveState === 'pending' || autosaveState === 'saving' || autosaveState === 'error'
  useEffect(() => {
    reportUnsavedToShell(hasUnsavedWork)
    if (!hasUnsavedWork) return
    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault()
      // Kick off the save; if it lands before the user answers, nothing is lost.
      void autosaverRef.current!.flush()
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [hasUnsavedWork])

  function applyDealState(schema: InputSchema, deal: Deal) {
    const hydrated = hydrateDealState(defaultValuesFor(schema), deal.inputs)
    setFormValues(hydrated.formValues)
    setQuickScreenInputs(hydrated.quickScreen)
    setAcquisitionQuickScreenInputs(hydrated.acquisitionQuickScreen)
    results.reset()
    setLoadedScenario(null)
    setActiveMappingProfileId(deal.activeMappingProfileId)
    // Clear the previous deal's template now: otherwise the template tab sees
    // this deal's profile paired with the old deal's template until the fetch
    // lands, and would link that template to this deal. (Re-applying the
    // same deal, e.g. a History restore, keeps its template loaded.)
    setActiveTemplate((prev) => (prev && prev.id === deal.activeTemplateId ? prev : null))
    if (deal.activeTemplateId) {
      fetchTemplate(deal.activeTemplateId)
        .then((template) => {
          if (activeDealIdRef.current === deal.id) setActiveTemplate(template)
        })
        .catch((err) => {
          if (activeDealIdRef.current !== deal.id) return
          // Template gone (or unreachable): show "no template" rather than
          // leave the tab waiting. The deal's stored link isn't touched.
          setActiveMappingProfileId(null)
          toastError(`Couldn't open "${deal.name}"'s Excel template — pick one on the Template tab`, err)
        })
    }
    lastPersistedJsonRef.current = JSON.stringify(
      serializeDealInputs(hydrated.formValues, hydrated.quickScreen, hydrated.acquisitionQuickScreen),
    )
    activeDealIdRef.current = deal.id
    hydratedRef.current = true
  }

  const bootStartedRef = useRef(false)
  useEffect(() => {
    // StrictMode double-invokes effects in dev; without this guard the boot
    // would run twice and could create two "Default Deal" rows.
    if (bootStartedRef.current) return
    bootStartedRef.current = true
    Promise.all([fetchInputSchema(), fetchHealth(), fetchDeals()])
      .then(async ([schema, health, dealList]) => {
        let list = dealList
        if (list.length === 0) {
          list = [await createDeal({ name: 'Default Deal' })]
        }
        const storedId = localStorage.getItem(ACTIVE_DEAL_STORAGE_KEY)
        const active = list.find((d) => d.id === storedId) ?? list[0]
        localStorage.setItem(ACTIVE_DEAL_STORAGE_KEY, active.id)
        applyDealState(schema, active)
        // A Quick Screen link is offered, never applied automatically — it
        // used to overwrite the active deal's saved napkin on every load.
        const shared = parseShareLink(window.location.search)
        if (shared) {
          const hydrated = hydrateDealState({}, active.inputs)
          const differs =
            (shared.development && inputsKey(shared.development) !== inputsKey(hydrated.quickScreen)) ||
            (shared.acquisition && inputsKey(shared.acquisition) !== inputsKey(hydrated.acquisitionQuickScreen))
          if (differs) {
            setSharedFromLink(shared)
            setTab('quickscreen') // so the offer is seen
          } else {
            setQuickScreenMode(shared.mode)
          }
        }
        setDeals(list)
        setActiveDealId(active.id)
        setState({ status: 'ready', schema, apiOk: health.status === 'ok' })
      })
      .catch((err: Error) => {
        setState({ status: 'error', message: err.message })
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Keep the connection indicator honest after boot: re-check every 30s so a
  // backend that went away shows before the next action fails.
  const ready = state.status === 'ready'
  useEffect(() => {
    if (!ready) return
    const id = window.setInterval(() => {
      fetchHealth()
        .then((h) => h.status === 'ok')
        .catch(() => false)
        .then((ok) => setState((prev) => (prev.status === 'ready' && prev.apiOk !== ok ? { ...prev, apiOk: ok } : prev)))
    }, HEALTH_POLL_MS)
    return () => window.clearInterval(id)
  }, [ready])

  // J13: Cmd/Ctrl+K opens the global search palette; Cmd/Ctrl+Enter
  // computes with the inputs on screen (committing a field being typed in
  // first — its value only lands in the form on blur).
  const { compute } = results
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((v) => !v)
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault()
        const active = document.activeElement
        if (active instanceof HTMLElement) active.blur()
        requestAnimationFrame(() => {
          if (!blockedByUnparsedEntry()) void compute(formValuesRef.current)
        })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [compute])

  // Debounced autosave of the whole working state into the active deal.
  useEffect(() => {
    if (!hydratedRef.current || activeDealId === null) return
    const blob = serializeDealInputs(formValues, quickScreenInputs, acquisitionQuickScreenInputs)
    const json = JSON.stringify(blob)
    if (json === lastPersistedJsonRef.current) return
    lastPersistedJsonRef.current = json
    autosaverRef.current!.schedule({ dealId: activeDealId, inputs: blob })
  }, [formValues, quickScreenInputs, acquisitionQuickScreenInputs, activeDealId])

  // Keep the sharable URL in sync with BOTH napkins + the active screen.
  useEffect(() => {
    const handle = setTimeout(() => {
      const params = shareParams(quickScreenInputs, acquisitionQuickScreenInputs, quickScreenMode)
      window.history.replaceState(null, '', `${window.location.pathname}?${params.toString()}`)
    }, 500)
    return () => clearTimeout(handle)
  }, [quickScreenInputs, acquisitionQuickScreenInputs, quickScreenMode])

  /** Before leaving the current deal: make sure its edits reached the
   *  server. If they didn't, stay put — otherwise the retry would be
   *  superseded by the next deal's saves and the edits silently lost. */
  async function ensureSaved(): Promise<boolean> {
    const ok = await autosaverRef.current!.flush()
    if (!ok) {
      toastError(
        "This deal's latest changes haven't been saved yet, so you're staying on it",
        'The server did not accept the save. The app keeps retrying — try again in a moment.',
      )
    }
    return ok
  }

  // Only the most recent switch applies: picking two deals in quick
  // succession used to open whichever fetch finished last.
  const switchRequestRef = useRef(0)
  async function switchDeal(dealId: string) {
    if (state.status !== 'ready' || dealId === activeDealId) return
    const request = ++switchRequestRef.current
    if (!(await ensureSaved())) return
    try {
      const deal = await fetchDeal(dealId)
      if (request !== switchRequestRef.current) return
      localStorage.setItem(ACTIVE_DEAL_STORAGE_KEY, deal.id)
      // Deal switches never re-apply URL params — those are first-load-only.
      applyDealState(state.schema, deal)
      setActiveDealId(deal.id)
      setDeals((prev) => [deal, ...prev.filter((d) => d.id !== deal.id)])
    } catch (err) {
      toastError("Couldn't open that deal — you're still on the current one", err)
    }
  }

  // Typed creation: every new deal carries its dealflow (acquisition |
  // development) in inputs from birth, so server-side surfaces (share, deck,
  // portfolio, hold-sweep) agree with the form instead of splitting between
  // "missing dealType" and a silent acquisition default.
  async function handleNewDeal(type: DealType) {
    if (state.status !== 'ready') return
    if (!(await ensureSaved())) return
    setNewDealMenuOpen(false)
    const label = type === 'development' ? 'Development' : 'Acquisition'
    try {
      const deal = await createDeal({
        // Next unused number — count-based names repeated after a delete.
        name: `Untitled ${label} ${
          Math.max(
            0,
            ...deals.map((d) => Number(d.name.match(new RegExp(`^Untitled ${label} (\\d+)$`))?.[1] ?? 0)),
          ) + 1
        }`,
        inputs: { dealType: type },
      })
      setDeals((prev) => [deal, ...prev])
      localStorage.setItem(ACTIVE_DEAL_STORAGE_KEY, deal.id)
      applyDealState(state.schema, deal)
      setActiveDealId(deal.id)
    } catch (err) {
      toastError("Couldn't create the deal", err)
    }
  }

  // Assign a dealflow to an untyped (legacy) deal. The active deal routes
  // through the normal field-change path so autosave/history record it; an
  // inactive deal merges server-side directly.
  async function handleSetDealType(dealId: string, type: DealType) {
    if (dealId === activeDealId) {
      handleFieldChange('dealType', type)
      // Save it explicitly: the form may already show this type as its
      // default, in which case the change is a no-op for autosave and the
      // deal would stay untyped on the server. And update the pipeline's
      // deal list, which the form change alone doesn't touch — otherwise the
      // deal stayed under "untyped" and the click looked like it did nothing.
      autosaverRef.current!.schedule({
        dealId,
        inputs: serializeDealInputs(
          { ...formValuesRef.current, dealType: type },
          quickScreenInputs,
          acquisitionQuickScreenInputs,
        ),
      })
      setDeals((prev) =>
        prev.map((d) => (d.id === dealId ? { ...d, inputs: { ...d.inputs, dealType: type } } : d)),
      )
      return
    }
    const deal = deals.find((d) => d.id === dealId)
    if (!deal) return
    try {
      // Merge into the server's current inputs, not the pipeline's cached
      // copy: that copy isn't refreshed by autosave, and the server replaces
      // inputs wholesale, so a stale merge would erase this session's edits.
      const fresh = await fetchDeal(dealId)
      const updated = await updateDeal(dealId, {
        inputs: { ...fresh.inputs, dealType: type },
      })
      setDeals((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
    } catch (err) {
      toastError(`Couldn't change the type of "${deal.name}"`, err)
    }
  }

  async function refreshDeals() {
    const list = await fetchDeals()
    setDeals(list)
  }

  // J10: the wizard finalized a deal — adopt it as the active deal.
  async function handleWizardCreated(deal: Deal) {
    if (state.status !== 'ready') return
    setOmWizardOpen(false)
    if (!(await ensureSaved())) return
    setDeals((prev) => [deal, ...prev.filter((d) => d.id !== deal.id)])
    localStorage.setItem(ACTIVE_DEAL_STORAGE_KEY, deal.id)
    applyDealState(state.schema, deal)
    setActiveDealId(deal.id)
    setTab('dashboard')
  }

  async function handleRenameDeal(name: string) {
    if (!activeDealId || !name.trim()) {
      setRenamingName(null)
      return
    }
    try {
      const updated = await updateDeal(activeDealId, { name: name.trim() })
      setDeals((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
      setRenamingName(null)
    } catch (err) {
      // Keep the rename box open with what was typed so nothing is lost.
      toastError("Couldn't rename the deal", err)
    }
  }

  async function handleDeleteDeal() {
    if (state.status !== 'ready' || !activeDealId) return
    const deal = deals.find((d) => d.id === activeDealId)
    if (!window.confirm(`Delete "${deal?.name ?? 'this deal'}" and all its scenarios?\n\nThis cannot be undone.`)) return
    try {
      await deleteDeal(activeDealId)
    } catch (err) {
      toastError("Couldn't delete the deal — nothing was removed", err)
      return
    }
    try {
      const remaining = deals.filter((d) => d.id !== activeDealId)
      if (remaining.length === 0) {
        const fresh = await createDeal({ name: 'Default Deal' })
        setDeals([fresh])
        localStorage.setItem(ACTIVE_DEAL_STORAGE_KEY, fresh.id)
        applyDealState(state.schema, fresh)
        setActiveDealId(fresh.id)
        return
      }
      const next = await fetchDeal(remaining[0].id)
      setDeals(remaining)
      localStorage.setItem(ACTIVE_DEAL_STORAGE_KEY, next.id)
      applyDealState(state.schema, next)
      setActiveDealId(next.id)
    } catch (err) {
      toastError('The deal was deleted, but the next one could not be opened — reopen the app', err)
    }
  }

  async function handleExportDeal() {
    if (!activeDealId) return
    try {
      await autosaverRef.current!.flush()
      const bundle = await exportDeal(activeDealId)
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
      await saveOutput(blob, `${bundle.deal.name.replace(/[^\w\- ]+/g, '')}.deal.json`)
    } catch (err) {
      toastError("Couldn't export the deal", err)
    }
  }

  function handleImportFile(file: File) {
    setImportNotice(null)
    file
      .text()
      .then((text) => {
        const bundle = JSON.parse(text) as DealExportBundle
        if (bundle.exportKind !== 'cre-dashboard-deal') {
          setImportNotice('That file is not a deal export bundle.')
          return
        }
        setImportPreview(bundle)
      })
      .catch(() => setImportNotice('Could not read that file as JSON.'))
  }

  async function handleConfirmImport() {
    if (state.status !== 'ready' || !importPreview) return
    if (!(await ensureSaved())) return
    try {
      const imported = await importDeal(importPreview)
      setImportPreview(null)
      setImportNotice(
        imported.importWarnings.length > 0
          ? `Imported with ${imported.importWarnings.length} note(s): ${imported.importWarnings[0]}`
          : `Imported "${imported.name}" with ${imported.importedScenarios} scenario(s).`,
      )
      setDeals((prev) => [imported, ...prev])
      localStorage.setItem(ACTIVE_DEAL_STORAGE_KEY, imported.id)
      applyDealState(state.schema, imported)
      setActiveDealId(imported.id)
    } catch (err) {
      setImportNotice(err instanceof Error ? err.message : 'Import failed')
      setImportPreview(null)
    }
  }

  /** Ask before `next` changes Deal Inputs values the user already has.
   *  `replaceAll` means fields missing from `next` get cleared too (a
   *  scenario load), not kept (a merge). True when there's nothing to ask
   *  about or the user agreed. */
  function confirmInputChanges(next: Record<string, unknown>, what: string, replaceAll: boolean): boolean {
    if (state.status !== 'ready') return true
    const hasValue = (v: unknown) => v !== undefined && v !== null && v !== ''
    const overwrites = presetDiff(formValues, next).filter((row) => row.changed && hasValue(row.current))
    const cleared = replaceAll
      ? Object.keys(formValues).filter((id) => hasValue(formValues[id]) && !hasValue(next[id]))
      : []
    if (overwrites.length === 0 && cleared.length === 0) return true
    const byId = new Map(flattenFields(state.schema).map((f) => [f.id, f]))
    const lines = [
      ...overwrites.map((row) => {
        const field = byId.get(row.fieldId)
        return `• ${field?.label ?? row.fieldId}: ${formatValue(field, row.current)} → ${formatValue(field, row.proposed)}`
      }),
      ...cleared.map((id) => {
        const field = byId.get(id)
        return `• ${field?.label ?? id}: ${formatValue(field, formValues[id])} → (cleared)`
      }),
    ]
    const shown = lines.slice(0, 12).join('\n')
    const more = lines.length > 12 ? `\n…and ${lines.length - 12} more` : ''
    return window.confirm(
      `${what} changes ${lines.length} value(s) already in Deal Inputs:\n\n${shown}${more}\n\nContinue?`,
    )
  }

  /** Apply napkin values to the full form — after confirming any field that
   *  already holds a different value (it used to be overwritten silently). */
  function sendToDealInputs(patch: Record<string, unknown>) {
    if (!confirmInputChanges(patch, 'Sending the Quick Screen', false)) return
    applyFromSource(patch, sameSourceFor(Object.keys(patch), { source: 'quickScreen', at: new Date().toISOString() }))
    setTab('dashboard')
  }

  /** A scenario load replaces every input (it used to, silently); confirm
   *  first and remember where the working inputs came from. */
  function loadScenario(inputs: Record<string, unknown>, name: string) {
    // Over the schema defaults, like a deal load: a scenario saved before a
    // field existed shouldn't clear that field's default.
    const next = state.status === 'ready' ? { ...defaultValuesFor(state.schema), ...inputs } : inputs
    if (!confirmInputChanges(next, `Loading scenario "${name}"`, true)) return
    setFormValues(next)
    setLoadedScenario({ name, key: inputsKey(next) })
    setTab('dashboard')
  }

  function handleSendQuickScreenToDealInputs() {
    sendToDealInputs(mapQuickScreenToDealInputs(quickScreenInputs, quickScreenResults))
  }

  // Acquisition-side quick screen send (the mapped values arrive already
  // shaped by mapAcquisitionQuickScreenToDealInputs, incl. dealType).
  function handleSendAcquisitionToDealInputs(values: Record<string, unknown>) {
    sendToDealInputs(values)
  }

  function applySharedScreen(shared: SharedScreen) {
    if (shared.development) setQuickScreenInputs(shared.development)
    if (shared.acquisition) setAcquisitionQuickScreenInputs(shared.acquisition)
    setQuickScreenMode(shared.mode)
  }

  function handleLoadQuickScreenScenario(inputs: QuickScreenInputs) {
    setQuickScreenInputs(inputs)
    setTab('quickscreen')
  }

  const visibleSections = useMemo(() => {
    if (state.status !== 'ready') return []
    return orderSections(state.schema.sections.filter((s) => isVisible(s.visibleWhen, formValues)))
  }, [state, formValues])

  // Panels holding per-deal work (sensitivity grids, Monte Carlo runs, the
  // hold sweep, extraction review, generate reports) remount when the deal
  // changes, so nothing from one deal can be saved onto another.
  const dealScope = activeDealId ?? 'no-deal'

  const labelsById = useMemo(
    () => new Map(state.status === 'ready' ? flattenFields(state.schema).map((f) => [f.id, f.label]) : []),
    [state],
  )

  if (state.status === 'loading') {
    return <div className="p-8 text-slate-500">Loading…</div>
  }

  if (state.status === 'error') {
    return (
      <div className="p-8">
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-red-700">
          <div className="font-medium">The app couldn't load your deals.</div>
          <div className="mt-1 text-sm">{state.message}</div>
          <button
            onClick={() => window.location.reload()}
            className="mt-3 rounded bg-red-600 px-3 py-1 text-sm text-white hover:bg-red-700"
          >
            Try again
          </button>
        </div>
      </div>
    )
  }

  const { schema, apiOk } = state
  const activeDeal = deals.find((d) => d.id === activeDealId) ?? null

  /** A user edit: the value is now theirs, so any "filled by the app"
   *  marker on the field goes. */
  function handleFieldChange(fieldId: string, value: unknown) {
    setFormValues((prev) => clearProvenance({ ...prev, [fieldId]: value }, fieldId))
  }

  /** Values the app filled in — recorded so the form can say where each
   *  came from (roadmap #14). */
  function applyFromSource(patch: Record<string, unknown>, entries: Record<string, FieldProvenance>) {
    setFormValues((prev) => recordProvenance({ ...prev, ...patch }, entries))
  }

  function goToSection(sectionId: string) {
    setTab('dashboard')
    requestAnimationFrame(() => {
      const section = document.getElementById(`section-${sectionId}`)
      if (section instanceof HTMLDetailsElement) section.open = true
      section?.scrollIntoView({ behavior: 'smooth' })
    })
  }

  return (
    <Layout
      nav={
        // Module navigation lives here: the old top tab strip was 1,298px
        // wide in an 800px column, hiding six modules at 1440px.
        <div className="space-y-4 pb-4">
          {NAV_GROUPS.map((group) => (
            <div key={group.label}>
              {group.label && (
                <div className="px-2 pb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                  {group.label}
                </div>
              )}
              <ul className="space-y-0.5">
                {group.items.map(([id, label]) => (
                  <li key={id}>
                    <button
                      onClick={() => setTab(id)}
                      aria-current={tab === id ? 'page' : undefined}
                      className={`w-full rounded px-2 py-1.5 text-left text-sm ${
                        tab === id ? 'bg-slate-100 font-medium text-slate-900' : 'text-slate-600 hover:bg-slate-100'
                      }`}
                    >
                      {label}
                    </button>
                    {id === 'dashboard' && tab === 'dashboard' && (
                      <ul aria-label="Deal Inputs sections" className="mt-0.5 mb-1 ml-3 border-l border-slate-200 pl-2">
                        {visibleSections.map((section) => (
                          <li key={section.id}>
                            <button
                              onClick={() => goToSection(section.id)}
                              className="w-full rounded px-2 py-1 text-left text-xs text-slate-600 hover:bg-slate-100"
                            >
                              {section.label}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      }
      summary={
        <>
          <div
            className={`mb-3 rounded px-2 py-1 text-xs ${
              apiOk ? 'text-emerald-600' : 'text-amber-600'
            }`}
          >
            {apiOk
              ? 'Connected'
              : isDesktop()
                ? "Calculation engine not responding — quit and reopen the app"
                : 'API unreachable — is the backend running?'}
          </div>
          <ResultsStatus
            latest={latestResult}
            stale={anyStale}
            computing={results.computing}
            failure={results.failure}
            onRecompute={computeNow}
            onGoToField={(fieldId) => {
              setTab('dashboard')
              requestAnimationFrame(() => goToField(fieldId))
            }}
            labelOf={(id) => labelsById.get(id) ?? id}
          />
          <MetricsSidebar
            metrics={schema.outputs}
            view={(metric) => {
              // Elsewhere: the most recent computed value (engine or Excel
              // read-back), labelled with its source. On the Quick Screen the
              // napkin leads — its estimates move as you edit it — and full
              // results only fill metrics the napkin can't estimate.
              const estimate = tab === 'quickscreen' ? quickScreenOutputs[metric.id] : undefined
              const picked = estimate === undefined ? pickMetric(metric.id, resultSets) : null
              const value = picked ? picked.value : estimate
              return {
                value,
                provenance: picked ? picked.stamp.source : estimate !== undefined ? 'estimate' : 'none',
                stale: picked ? isStale(picked.stamp, currentInputsKey, activeDealId) : false,
                fullModelOnly:
                  tab === 'quickscreen' && value === undefined && quickScreenFullModelOnlyIds.has(metric.id),
              }
            }}
            dealType={tab === 'quickscreen' ? quickScreenMode : formValues.dealType}
            irrConvention={nativeResponse?.irrConvention ?? null}
            onGoalSeek={setGoalSeekMetric}
          />
          <p className="mt-4 text-xs text-slate-400">
            {tab === 'quickscreen'
              ? 'On this tab the napkin leads: italic "est." values are Quick Screen approximations that move as you edit; values tagged "engine" / "Excel" come from the last full compute.'
              : latestResult
                ? 'Each value shows its source: "engine" = built-in pro-forma, "Excel" = read back from your template. The newest result wins.'
                : 'Metrics appear after Compute (⌘↩) or after generating with template read-back.'}
          </p>
        </>
      }
    >
      {goalSeekMetric && (
        <GoalSeekModal
          schema={schema}
          metric={goalSeekMetric}
          values={formValues}
          onApply={(fieldId, value) => {
            applyFromSource(
              { [fieldId]: value },
              { [fieldId]: { source: 'goalSeek', label: `goal seek (${goalSeekMetric.label})`, at: new Date().toISOString() } },
            )
            // Recompute with the solved value so the sidebar isn't left stale.
            requestAnimationFrame(() => computeNow())
          }}
          onClose={() => setGoalSeekMetric(null)}
        />
      )}
      {/* The deal header + workflow tabs stay pinned while tab content
          scrolls (main is the scroll container). Negative margins span
          main's px-8/pt-6 padding so scrolled content never peeks around
          the bar; z-30 sits above the statement's sticky cells (z-10) and
          below modals (z-50). */}
      <div data-app-header className="sticky -top-6 z-30 -mx-8 -mt-6 bg-slate-50 px-8 pt-6">
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <label className="text-xs font-semibold tracking-wide text-slate-400">DEAL</label>
        <select
          value={activeDealId ?? ''}
          onChange={(e) => void switchDeal(e.target.value)}
          className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
        >
          {deals.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
        {renamingName === null ? (
          <button
            onClick={() => setRenamingName(activeDeal?.name ?? '')}
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            Rename
          </button>
        ) : (
          <input
            autoFocus
            value={renamingName}
            onChange={(e) => setRenamingName(e.target.value)}
            onBlur={() => void handleRenameDeal(renamingName)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void handleRenameDeal(renamingName)
              if (e.key === 'Escape') setRenamingName(null)
            }}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          />
        )}
        {/* Type badge: which dealflow the active deal belongs to. */}
        {(() => {
          const type = dealTypeOf({ inputs: formValues })
          if (!type) return null
          return (
            <span
              className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
                type === 'development'
                  ? 'bg-orange-100 text-orange-700'
                  : 'bg-sky-100 text-sky-700'
              }`}
            >
              {type === 'development' ? 'DEV' : 'ACQ'}
            </span>
          )
        })()}
        <div className="relative">
          <button
            onClick={() => setNewDealMenuOpen((v) => !v)}
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            New Deal ▾
          </button>
          {newDealMenuOpen && (
            <div className="absolute left-0 top-full z-40 mt-1 w-36 rounded border border-slate-200 bg-white py-1 shadow-lg">
              <button
                onClick={() => void handleNewDeal('acquisition')}
                className="block w-full px-3 py-1.5 text-left text-xs text-slate-700 hover:bg-sky-50"
              >
                Acquisition
              </button>
              <button
                onClick={() => void handleNewDeal('development')}
                className="block w-full px-3 py-1.5 text-left text-xs text-slate-700 hover:bg-orange-50"
              >
                Development
              </button>
            </div>
          )}
        </div>
        <button
          onClick={() => void handleDeleteDeal()}
          className="rounded border border-slate-300 px-2 py-1 text-xs text-red-500 hover:bg-red-50"
        >
          Delete
        </button>
        <button
          onClick={() => void handleExportDeal()}
          className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          Export
        </button>
        <button
          onClick={() => importInputRef.current?.open()}
          className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          Import
        </button>
        <FileChooser
          ref={importInputRef}
          accept="application/json,.json"
          description="Deal export bundles"
          hidden
          onFiles={(files) => handleImportFile(files[0])}
        />
        {/* J11: date chips for the active deal + editor. */}
        {sortByDate(readCriticalDates(formValues)).slice(0, 3).map((row) => {
          const status = dateStatus(row.date, new Date())
          return (
            <span
              key={row.id}
              title={row.notes || row.label}
              className={`rounded px-1.5 py-0.5 text-[11px] ${
                status === 'overdue'
                  ? 'bg-red-100 text-red-700'
                  : status === 'upcoming'
                    ? 'bg-amber-100 text-amber-700'
                    : 'bg-slate-100 text-slate-500'
              }`}
            >
              {row.label} {row.date}
            </span>
          )
        })}
        <button
          onClick={() => setDatesEditorOpen(true)}
          className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          Dates
        </button>
        {loadedScenario && (
          <span
            className="ml-auto rounded border border-slate-200 bg-slate-50 px-2 py-0.5 text-xs text-slate-600"
            title="The Deal Inputs were loaded from this saved scenario."
          >
            Working from scenario “{loadedScenario.name}”
            {inputsKey(formValues) !== loadedScenario.key && ' · modified'}
          </span>
        )}
        <span
          className={`${loadedScenario ? '' : 'ml-auto '}text-xs ${
            autosaveState === 'error' ? 'text-red-500' : 'text-slate-400'
          }`}
        >
          {AUTOSAVE_LABEL[autosaveState]}
        </span>
      </div>

      {importNotice && (
        <div className="mb-3 rounded border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-600">
          {importNotice}
        </div>
      )}
      {importPreview && (
        <div className="mb-3 flex items-center gap-3 rounded border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-slate-700">
          <span>
            Import <span className="font-semibold">{importPreview.deal.name}</span> —{' '}
            {importPreview.scenarios.length} scenario(s), exported{' '}
            {new Date(importPreview.exportedAt).toLocaleString()}
            {importPreview.activeTemplate &&
              ` · used template "${importPreview.activeTemplate.filename}" (not bundled)`}
            ?
          </span>
          <button
            onClick={() => void handleConfirmImport()}
            className="rounded bg-slate-900 px-2 py-1 text-xs text-white hover:bg-slate-700"
          >
            Create new deal
          </button>
          <button
            onClick={() => setImportPreview(null)}
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-white"
          >
            Cancel
          </button>
        </div>
      )}

      </div>

      {/* All tabs stay mounted so in-progress state (unsaved mapping edits, form
          values) survives switching tabs — only visibility toggles. */}
      <div style={{ display: tab === 'pipeline' ? 'block' : 'none' }}>
        <PipelinePage
          active={tab === 'pipeline'}
          deals={deals}
          activeDealId={activeDealId}
          onOpenDeal={(dealId) => {
            void switchDeal(dealId).then(() => setTab('dashboard'))
          }}
          onStatusChange={(dealId, status) => {
            // The reply carries the server's copy of the deal; for the open
            // deal, save pending edits first so it can't roll them back
            // on screen.
            ;(dealId === activeDealId ? autosaverRef.current!.flush() : Promise.resolve(true))
              .then(() => updateDeal(dealId, { status }))
              .then((updated) => setDeals((prev) => prev.map((d) => (d.id === dealId ? updated : d))))
              .catch((err) => toastError("Couldn't change the deal's status", err))
          }}
          onBulkStatus={async (dealIds, status) => {
            try {
              const { updated } = await bulkUpdateDealStatus(dealIds, status)
              const byId = new Map(updated.map((d) => [d.id, d]))
              setDeals((prev) => prev.map((d) => byId.get(d.id) ?? d))
            } catch (err) {
              toastError(`Couldn't change the status of ${dealIds.length} deal(s) — none were changed`, err)
            }
          }}
          onNewDeal={(type) => void handleNewDeal(type)}
          onNewDealFromDocuments={() => setOmWizardOpen(true)}
          onSetDealType={(dealId, type) => void handleSetDealType(dealId, type)}
        />
      </div>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onNavigate={(item, kind) => {
          // Deals/tenants/notes deep-link to their deal's dashboard; comps
          // (global, no dealId) open the Comps tab.
          if (item.dealId) {
            void switchDeal(item.dealId).then(() => setTab('dashboard'))
          } else if (kind === 'comps') {
            setTab('comps')
          }
        }}
      />

      {datesEditorOpen && (
        <CriticalDatesEditor
          values={formValues}
          onChange={(rows) => handleFieldChange('criticalDates', rows)}
          onClose={() => setDatesEditorOpen(false)}
        />
      )}

      {omWizardOpen && (
        <OmWizard
          schema={schema}
          deals={deals}
          onClose={() => setOmWizardOpen(false)}
          onCreated={handleWizardCreated}
          onDealsChanged={() => void refreshDeals()}
        />
      )}

      <div style={{ display: tab === 'quickscreen' ? 'block' : 'none' }}>
        {sharedFromLink && (
          <div className="mb-4 flex max-w-3xl flex-wrap items-center justify-between gap-2 rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-700">
            <span>
              This link contains a shared {sharedFromLink.mode} Quick Screen. Opening it replaces the napkin saved
              on “{deals.find((d) => d.id === activeDealId)?.name ?? 'this deal'}”.
            </span>
            <span className="flex gap-2">
              <button
                onClick={() => {
                  applySharedScreen(sharedFromLink)
                  setSharedFromLink(null)
                }}
                className="rounded bg-slate-900 px-2 py-1 text-xs text-white hover:bg-slate-700"
              >
                Open shared screen
              </button>
              <button onClick={() => setSharedFromLink(null)} className="px-2 py-1 text-xs underline">
                Keep my saved napkin
              </button>
            </span>
          </div>
        )}
        <QuickScreen
          inputs={quickScreenInputs}
          onInputsChange={setQuickScreenInputs}
          results={quickScreenResults}
          mode={quickScreenMode}
          onModeChange={setQuickScreenMode}
          acquisitionInputs={acquisitionQuickScreenInputs}
          onAcquisitionInputsChange={setAcquisitionQuickScreenInputs}
          onSendToDealInputs={handleSendQuickScreenToDealInputs}
          onSendAcquisitionToDealInputs={handleSendAcquisitionToDealInputs}
          onOpenShared={applySharedScreen}
          dealId={activeDealId}
        />
      </div>

      <div style={{ display: tab === 'documents' ? 'block' : 'none' }}>
        <Documents
          key={dealScope}
          schema={schema}
          currentUnitMix={formValues.unitMix}
          currentCommercialLeases={formValues.commercialLeases}
          onApplyExtraction={(confirmedValues, provenance) => {
            applyFromSource(confirmedValues, provenance)
            setTab('dashboard')
          }}
        />
      </div>

      <div style={{ display: tab === 'setup' ? 'block' : 'none' }}>
        <TemplateUpload
          values={formValues}
          activeTemplate={activeTemplate}
          activeMappingProfileId={activeMappingProfileId}
          onUnsavedChange={setMappingUnsaved}
          onTemplateReady={(template, mappingProfileId) => {
            setActiveTemplate(template)
            setActiveMappingProfileId(mappingProfileId)
            if (activeDealId) {
              updateDeal(activeDealId, {
                activeTemplateId: template?.id ?? null,
                activeMappingProfileId: mappingProfileId,
              }).catch((err) =>
                toastError("Couldn't save which template this deal uses — it may not be remembered next time", err),
              )
            }
          }}
        />
      </div>

      <div style={{ display: tab === 'dashboard' ? 'block' : 'none' }}>
        <FileCabinet dealId={activeDealId} />
        <HistoryDrawer
          schema={schema}
          dealId={activeDealId}
          onRestored={(deal) => {
            applyDealState(schema, deal)
            setDeals((prev) => prev.map((d) => (d.id === deal.id ? deal : d)))
          }}
        />
        <PresetsPanel
          schema={schema}
          values={formValues}
          onApply={(patch, presetName) =>
            applyFromSource(
              patch,
              sameSourceFor(Object.keys(patch), { source: 'preset', label: presetName, at: new Date().toISOString() }),
            )
          }
        />
        <DealInputForm key={`form-${dealScope}`} schema={schema} values={formValues} onFieldChange={handleFieldChange} />
        <GeneratePanel
          key={dealScope}
          schema={schema}
          onReviewMapping={() => setTab('setup')}
          template={activeTemplate}
          mappingProfileId={activeMappingProfileId}
          mappingUnsaved={mappingUnsaved}
          values={formValues}
          onGenerated={results.recordExcel}
          dealId={activeDealId}
          native={results.native}
          nativeStale={nativeStale}
          computing={results.computing}
          failure={results.failure}
          onCompute={computeNow}
        />
      </div>

      <div style={{ display: tab === 'cashflow' ? 'block' : 'none' }}>
        <CashFlowTab
          key={dealScope}
          statement={nativeResponse?.statement ?? null}
          values={formValues}
          onGoToCompute={() => setTab('dashboard')}
          stale={nativeStale}
          onRecompute={computeNow}
        />
      </div>

      <div style={{ display: tab === 'sensitivity' ? 'block' : 'none' }}>
        <SensitivityPanel
          key={dealScope}
          schema={schema}
          template={activeTemplate}
          mappingProfileId={activeMappingProfileId}
          mappingUnsaved={mappingUnsaved}
          baseValues={formValues}
          dealId={activeDealId}
        />
      </div>

      <div style={{ display: tab === 'risk' ? 'block' : 'none' }}>
        <RiskPanel key={dealScope} schema={schema} values={formValues} dealId={activeDealId} />
      </div>

      <div style={{ display: tab === 'scenarios' ? 'block' : 'none' }}>
        <ScenariosPanel
          schema={schema}
          template={activeTemplate}
          mappingProfileId={activeMappingProfileId}
          values={formValues}
          active={tab === 'scenarios'}
          dealId={activeDealId}
          computedOutputs={latestOutputs}
          computedDebt={(nativeResponse?.debt as Record<string, unknown> | null | undefined) ?? null}
          outputsStale={anyStale}
          onLoadScenario={loadScenario}
          onLoadQuickScreenScenario={handleLoadQuickScreenScenario}
        />
      </div>

      <div style={{ display: tab === 'portfolio' ? 'block' : 'none' }}>
        <PortfolioPage active={tab === 'portfolio'} />
      </div>

      <div style={{ display: tab === 'settings' ? 'block' : 'none' }}>
        <SettingsPage active={tab === 'settings'} />
      </div>

      <div style={{ display: tab === 'comps' ? 'block' : 'none' }}>
        <CompsPage dealMarket={typeof formValues.market === 'string' ? formValues.market : ''} />
      </div>
    </Layout>
  )
}

export default App
