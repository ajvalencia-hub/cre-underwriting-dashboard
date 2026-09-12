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
  UNAUTHORIZED_EVENT,
  archiveDeal,
  cloneDeal,
  createDeal,
  deleteDeal,
  exportDeal,
  fetchAuthStatus,
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
  type QuickScreenMode,
} from './lib/dealPersistence'
import type { Statement } from './lib/cashflowStatement'
import { formatOutputValue } from './lib/formatValue'
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
  serializeAcquisitionQuickScreenInputs,
  serializeQuickScreenInputs,
  type AcquisitionQuickScreenInputs,
  type QuickScreenInputs,
} from './lib/quickScreenMath'
import type { Deal } from './types/deal'
import AuthGate from './components/AuthGate'
import CommandPalette from './components/CommandPalette'
import CriticalDatesEditor from './components/CriticalDatesEditor'
import FileCabinet from './components/FileCabinet'
import GoalSeekModal from './components/GoalSeekModal'
import OmWizard from './components/OmWizard'
import Toasts from './components/Toasts'
import { confirmAction } from './lib/confirmAction'
import { dateStatus, readCriticalDates, sortByDate } from './lib/criticalDates'
import { dealTypeOf, type DealType } from './lib/dealStages'
import { createLatestGuard } from './lib/latest'
import { isOutputVisibleFor } from './lib/outputVisibility'
import { loadRecent, recordRecent } from './lib/recentDeals'
import { safeStorage } from './lib/safeStorage'
import { toastError } from './lib/toast'
import { loadLastTab, loadNewDealTypePref, saveLastTab } from './lib/workflowPrefs'
import type { InputSchema, OutputMetric } from './types/schema'
import type { TemplateSummary } from './types/template'

type LoadState =
  | { status: 'loading' }
  | { status: 'auth' }
  | { status: 'error'; message: string }
  | { status: 'ready'; schema: InputSchema; apiOk: boolean }

/** Workflow tabs in display order; Cmd/Ctrl+1..9 map onto the first nine. */
const TABS = [
  ['pipeline', 'Deals'],
  ['quickscreen', '0. Quick Screen'],
  ['documents', '1. Documents'],
  ['setup', '2. Template & Mapping'],
  ['dashboard', '3. Deal Inputs'],
  ['cashflow', '4. Cash Flow'],
  ['sensitivity', '5. Sensitivity'],
  ['risk', '5b. Risk'],
  ['scenarios', '6. Scenarios'],
  ['comps', '7. Comps'],
  ['portfolio', 'Portfolio'],
  ['settings', '⚙ Settings'],
] as const

type Tab = (typeof TABS)[number][0]

const TAB_IDS: readonly Tab[] = TABS.map(([id]) => id)

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
  error: 'Save failed — retrying on next change',
}

function App() {
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  // F8: boot to the last active tab (per browser).
  const [tab, setTab] = useState<Tab>(() => loadLastTab(safeStorage, TAB_IDS, 'quickscreen'))
  const [formValues, setFormValues] = useState<Record<string, unknown>>({})
  const [activeTemplate, setActiveTemplate] = useState<TemplateSummary | null>(null)
  const [activeMappingProfileId, setActiveMappingProfileId] = useState<string | null>(null)
  // Two provenance tiers of real computed outputs. Display precedence:
  // server-recalc > native engine > quick-screen "est." — a lower tier never
  // overwrites a higher one on screen.
  const [serverOutputs, setServerOutputs] = useState<Record<string, unknown>>({})
  const [nativeOutputs, setNativeOutputs] = useState<Record<string, unknown>>({})
  const [nativeDebt, setNativeDebt] = useState<Record<string, unknown> | null>(null)
  const [nativeIrrConvention, setNativeIrrConvention] = useState<'periodic_monthly' | 'xirr' | null>(null)
  const [nativeStatement, setNativeStatement] = useState<Statement | null>(null)
  const [quickScreenInputs, setQuickScreenInputs] = useState<QuickScreenInputs>(QUICK_SCREEN_DEFAULTS)
  // The acquisition-side napkin (lifted here for URL sharing + sidebar
  // estimates, same as the development inputs above).
  const [acquisitionQuickScreenInputs, setAcquisitionQuickScreenInputs] =
    useState<AcquisitionQuickScreenInputs>(ACQUISITION_QUICK_SCREEN_DEFAULTS)
  const [quickScreenMode, setQuickScreenMode] = useState<QuickScreenMode>('development')
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
  // F2: deal actions popover (duplicate / archive).
  const [moreMenuOpen, setMoreMenuOpen] = useState(false)
  const newDealMenuRef = useRef<HTMLDivElement>(null)
  const moreMenuRef = useRef<HTMLDivElement>(null)
  // F9: recently viewed deal ids, newest first.
  const [recentIds, setRecentIds] = useState<string[]>(() => loadRecent(safeStorage))

  const [deals, setDeals] = useState<Deal[]>([])
  const [activeDealId, setActiveDealId] = useState<string | null>(null)
  const [autosaveState, setAutosaveState] = useState<AutosaveState>('idle')
  const [renamingName, setRenamingName] = useState<string | null>(null)
  const [importPreview, setImportPreview] = useState<DealExportBundle | null>(null)
  const [importNotice, setImportNotice] = useState<string | null>(null)
  const importInputRef = useRef<HTMLInputElement>(null)

  const activeDealIdRef = useRef<string | null>(null)
  const hydratedRef = useRef(false)
  // B5: deal-switch + template-fetch sequencing — a stale resolution never
  // lands on top of a newer one (A→B→C must end on C).
  const switchGuardRef = useRef(createLatestGuard())
  const templateGuardRef = useRef(createLatestGuard())
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
  // B6: sidebar estimates follow the DEAL's type; only an untyped deal falls
  // back to whichever napkin is active on screen.
  const activeDealType = useMemo(() => dealTypeOf({ inputs: formValues }), [formValues])
  const estimateSource: QuickScreenMode = activeDealType ?? quickScreenMode
  const quickScreenOutputs = useMemo(
    () =>
      estimateSource === 'acquisition'
        ? mapAcquisitionQuickScreenToOutputMetrics(
            acquisitionQuickScreenResults, acquisitionQuickScreenInputs,
          )
        : mapQuickScreenToOutputMetrics(quickScreenResults, quickScreenInputs),
    [estimateSource, quickScreenResults, quickScreenInputs,
     acquisitionQuickScreenResults, acquisitionQuickScreenInputs],
  )
  const quickScreenFullModelOnlyIds = useMemo(
    () => new Set<string>(QUICK_SCREEN_FULL_MODEL_ONLY_OUTPUT_IDS),
    [],
  )

  // Cleanup only unsubscribes — never dispose here: StrictMode's simulated
  // remount would permanently kill the ref'd autosaver otherwise.
  useEffect(() => autosaverRef.current!.subscribe(setAutosaveState), [])

  function applyDealState(schema: InputSchema, deal: Deal, urlParams: URLSearchParams) {
    const hydrated = hydrateDealState(defaultValuesFor(schema), deal.inputs, urlParams)
    setFormValues(hydrated.formValues)
    setQuickScreenInputs(hydrated.quickScreen)
    setAcquisitionQuickScreenInputs(hydrated.acquisitionQuickScreen)
    setQuickScreenMode(hydrated.quickScreenMode)
    setServerOutputs({})
    setNativeOutputs({})
    setNativeDebt(null)
    setNativeIrrConvention(null)
    setNativeStatement(null)
    setActiveMappingProfileId(deal.activeMappingProfileId)
    const templateToken = templateGuardRef.current.next()
    if (deal.activeTemplateId) {
      fetchTemplate(deal.activeTemplateId)
        .then((template) => {
          if (templateGuardRef.current.isCurrent(templateToken)) setActiveTemplate(template)
        })
        .catch(() => {
          if (templateGuardRef.current.isCurrent(templateToken)) setActiveTemplate(null)
        })
    } else {
      setActiveTemplate(null)
    }
    lastPersistedJsonRef.current = hydrated.quickScreenFromUrl
      ? '' // URL override differs from the stored deal — let the autosave sync it in
      : JSON.stringify(
          serializeDealInputs(
            hydrated.formValues,
            hydrated.quickScreen,
            hydrated.acquisitionQuickScreen,
            hydrated.quickScreenMode,
          ),
        )
    activeDealIdRef.current = deal.id
    hydratedRef.current = true
  }

  /** Make `deal` the active deal: storage key, hydration, recent list, and
   *  retire any in-flight switch so it cannot land on top of this one. */
  function activateDeal(schema: InputSchema, deal: Deal, urlParams = new URLSearchParams()) {
    switchGuardRef.current.invalidate()
    safeStorage.set(ACTIVE_DEAL_STORAGE_KEY, deal.id)
    applyDealState(schema, deal, urlParams)
    setActiveDealId(deal.id)
    setRecentIds(recordRecent(safeStorage, deal.id))
  }

  async function boot() {
    setState({ status: 'loading' })
    try {
      // F1: a configured token with no session shows the gate instead of a
      // wall of 401s. A failed status probe is not fatal — fall through and
      // let the real fetches decide.
      const auth = await fetchAuthStatus().catch(() => null)
      if (auth && auth.required && !auth.authenticated) {
        setState({ status: 'auth' })
        return
      }
      const [schema, health, dealList] = await Promise.all([
        fetchInputSchema(),
        fetchHealth(),
        fetchDeals(),
      ])
      let list = dealList
      if (list.length === 0) {
        list = [await createDeal({ name: 'Default Deal' })]
      }
      const storedId = safeStorage.get(ACTIVE_DEAL_STORAGE_KEY)
      const active = list.find((d) => d.id === storedId) ?? list[0]
      // URL quick-screen params (both napkins + the active screen) only
      // override on first load; hydrateDealState reads them.
      const urlParams = new URLSearchParams(window.location.search)
      setDeals(list)
      activateDeal(schema, active, urlParams)
      setState({ status: 'ready', schema, apiOk: health.status === 'ok' })
    } catch (err) {
      setState({ status: 'error', message: err instanceof Error ? err.message : String(err) })
    }
  }

  const bootStartedRef = useRef(false)
  useEffect(() => {
    // StrictMode double-invokes effects in dev; without this guard the boot
    // would run twice and could create two "Default Deal" rows.
    if (bootStartedRef.current) return
    bootStartedRef.current = true
    void boot()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // F1: any 401 from the API layer re-raises the gate.
  useEffect(() => {
    const onUnauthorized = () => setState({ status: 'auth' })
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  // F8: remember the last active tab.
  useEffect(() => {
    saveLastTab(safeStorage, tab)
  }, [tab])

  // J13: Cmd/Ctrl+K opens the global search palette; F6: Cmd/Ctrl+1..9 switch
  // workflow tabs and Escape closes the header popovers.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen((v) => !v)
        return
      }
      if ((e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey && /^[1-9]$/.test(e.key)) {
        const entry = TABS[Number(e.key) - 1]
        if (entry) {
          e.preventDefault()
          setTab(entry[0])
        }
        return
      }
      if (e.key === 'Escape') {
        setNewDealMenuOpen(false)
        setMoreMenuOpen(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // F6: outside-click closes the header popovers.
  useEffect(() => {
    if (!newDealMenuOpen && !moreMenuOpen) return
    function onPointerDown(e: MouseEvent) {
      const target = e.target as Node
      if (newDealMenuRef.current && !newDealMenuRef.current.contains(target)) setNewDealMenuOpen(false)
      if (moreMenuRef.current && !moreMenuRef.current.contains(target)) setMoreMenuOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [newDealMenuOpen, moreMenuOpen])

  // F5: warn before leaving with an unsaved autosave; flush when the tab hides.
  useEffect(() => {
    function onBeforeUnload(e: BeforeUnloadEvent) {
      const s = autosaverRef.current!.getState()
      if (s === 'pending' || s === 'saving' || s === 'error') {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    function onVisibility() {
      if (document.visibilityState === 'hidden') void autosaverRef.current!.flush()
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [])

  // Debounced autosave of the whole working state into the active deal.
  useEffect(() => {
    if (!hydratedRef.current || activeDealId === null) return
    const blob = serializeDealInputs(
      formValues,
      quickScreenInputs,
      acquisitionQuickScreenInputs,
      quickScreenMode,
    )
    const json = JSON.stringify(blob)
    if (json === lastPersistedJsonRef.current) return
    lastPersistedJsonRef.current = json
    autosaverRef.current!.schedule({ dealId: activeDealId, inputs: blob })
  }, [formValues, quickScreenInputs, acquisitionQuickScreenInputs, quickScreenMode, activeDealId])

  // Keep the sharable URL in sync with BOTH napkins + the active screen.
  // B2: never before boot resolves and the deal is hydrated — otherwise the
  // defaults land in the URL, boot reads them as a shared link, and the
  // autosave overwrites the deal's saved quick screen with defaults.
  useEffect(() => {
    if (state.status !== 'ready' || !hydratedRef.current) return
    const handle = setTimeout(() => {
      const params = serializeQuickScreenInputs(quickScreenInputs)
      serializeAcquisitionQuickScreenInputs(acquisitionQuickScreenInputs, params)
      if (quickScreenMode === 'acquisition') params.set('screen', 'acquisition')
      window.history.replaceState(null, '', `${window.location.pathname}?${params.toString()}`)
    }, 500)
    return () => clearTimeout(handle)
  }, [quickScreenInputs, acquisitionQuickScreenInputs, quickScreenMode, state.status])

  async function switchDeal(dealId: string) {
    if (state.status !== 'ready' || dealId === activeDealId) return
    // B5: only the newest switch may land.
    const token = switchGuardRef.current.next()
    try {
      await autosaverRef.current!.flush()
      const deal = await fetchDeal(dealId)
      if (!switchGuardRef.current.isCurrent(token)) return
      // Deal switches never re-apply URL params — those are first-load-only.
      activateDeal(state.schema, deal)
      setDeals((prev) => [deal, ...prev.filter((d) => d.id !== deal.id)])
    } catch (err) {
      if (switchGuardRef.current.isCurrent(token)) toastError(err, 'Could not open that deal.')
    }
  }

  // Typed creation: every new deal carries its dealflow (acquisition |
  // development) in inputs from birth, so server-side surfaces (share, deck,
  // portfolio, hold-sweep) agree with the form instead of splitting between
  // "missing dealType" and a silent acquisition default.
  async function handleNewDeal(type: DealType) {
    if (state.status !== 'ready') return
    setNewDealMenuOpen(false)
    try {
      await autosaverRef.current!.flush()
      const label = type === 'development' ? 'Development' : 'Acquisition'
      const deal = await createDeal({
        name: `Untitled ${label} ${deals.length + 1}`,
        inputs: { dealType: type },
      })
      // A stale rename box must never apply to the new deal; open a fresh
      // one so the placeholder name can be replaced immediately.
      setRenamingName('')
      setDeals((prev) => [deal, ...prev])
      activateDeal(state.schema, deal)
    } catch (err) {
      toastError(err, 'Could not create the deal.')
    }
  }

  /** Header "New Deal": F8 default type from Settings > Workflow, or ask. */
  function handleNewDealClick() {
    const pref = loadNewDealTypePref(safeStorage)
    if (pref === 'ask') {
      setMoreMenuOpen(false)
      setNewDealMenuOpen((v) => !v)
      return
    }
    void handleNewDeal(pref)
  }

  // Assign a dealflow to an untyped (legacy) deal. The active deal routes
  // through the normal field-change path so autosave/history record it; an
  // inactive deal merges server-side directly.
  async function handleSetDealType(dealId: string, type: DealType) {
    if (dealId === activeDealId) {
      handleFieldChange('dealType', type)
      return
    }
    const deal = deals.find((d) => d.id === dealId)
    if (!deal) return
    try {
      const updated = await updateDeal(dealId, {
        inputs: { ...deal.inputs, dealType: type },
      })
      setDeals((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
    } catch (err) {
      toastError(err, 'Could not set the deal type.')
    }
  }

  async function refreshDeals() {
    try {
      const list = await fetchDeals()
      setDeals(list)
    } catch (err) {
      toastError(err, 'Could not refresh the deal list.')
    }
  }

  // J10: the wizard finalized a deal — adopt it as the active deal.
  function handleWizardCreated(deal: Deal) {
    if (state.status !== 'ready') return
    setOmWizardOpen(false)
    setDeals((prev) => [deal, ...prev.filter((d) => d.id !== deal.id)])
    activateDeal(state.schema, deal)
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
    } catch (err) {
      toastError(err, 'Rename failed.')
    } finally {
      setRenamingName(null)
    }
  }

  /** After the active deal is gone (deleted/archived): open the next one, or
   *  seed a fresh default so the app is never dealless. */
  async function activateNextAfterRemoval(schema: InputSchema, removedId: string) {
    const remaining = deals.filter((d) => d.id !== removedId)
    if (remaining.length === 0) {
      const fresh = await createDeal({ name: 'Default Deal' })
      setDeals([fresh])
      activateDeal(schema, fresh)
      return
    }
    setDeals(remaining)
    activateDeal(schema, remaining[0])
  }

  async function handleDeleteDeal() {
    if (state.status !== 'ready' || !activeDealId) return
    const deal = deals.find((d) => d.id === activeDealId)
    if (!confirmAction(`Delete "${deal?.name ?? 'this deal'}" and all its scenarios?`)) return
    // B12: a pending autosave for this id would PUT to a deleted deal and
    // surface "Save failed" on whichever deal comes next.
    autosaverRef.current!.cancel()
    try {
      await deleteDeal(activeDealId)
      await activateNextAfterRemoval(state.schema, activeDealId)
    } catch (err) {
      toastError(err, 'Delete failed.')
    }
  }

  // F2: archive keeps the deal (restorable from Deals › Show archived) but
  // removes it from the working list exactly like delete does.
  async function handleArchiveDeal() {
    if (state.status !== 'ready' || !activeDealId) return
    setMoreMenuOpen(false)
    const deal = deals.find((d) => d.id === activeDealId)
    if (
      !confirmAction(
        `Archive "${deal?.name ?? 'this deal'}"? It leaves the pipeline, portfolio and search; restore it any time from Deals › Show archived.`,
      )
    ) {
      return
    }
    try {
      await autosaverRef.current!.flush()
      await archiveDeal(activeDealId)
      await activateNextAfterRemoval(state.schema, activeDealId)
    } catch (err) {
      toastError(err, 'Archive failed.')
    }
  }

  // F2: duplicate the active deal (server-side clone) and switch to the copy.
  async function handleCloneDeal() {
    if (state.status !== 'ready' || !activeDealId) return
    setMoreMenuOpen(false)
    const deal = deals.find((d) => d.id === activeDealId)
    const proposed = window.prompt('Name for the copy', `Copy of ${deal?.name ?? 'deal'}`)
    if (proposed === null) return
    try {
      await autosaverRef.current!.flush()
      const clone = await cloneDeal(activeDealId, proposed.trim() || undefined)
      setDeals((prev) => [clone, ...prev.filter((d) => d.id !== clone.id)])
      activateDeal(state.schema, clone)
    } catch (err) {
      toastError(err, 'Duplicate failed.')
    }
  }

  async function handleExportDeal() {
    if (!activeDealId) return
    try {
      await autosaverRef.current!.flush()
      const bundle = await exportDeal(activeDealId)
      const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${bundle.deal.name.replace(/[^\w\- ]+/g, '')}.deal.json`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      toastError(err, 'Export failed.')
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
    try {
      const imported = await importDeal(importPreview)
      setImportPreview(null)
      setImportNotice(
        imported.importWarnings.length > 0
          ? `Imported with ${imported.importWarnings.length} note(s): ${imported.importWarnings[0]}`
          : `Imported "${imported.name}" with ${imported.importedScenarios} scenario(s).`,
      )
      setDeals((prev) => [imported, ...prev])
      activateDeal(state.schema, imported)
    } catch (err) {
      setImportNotice(err instanceof Error ? err.message : 'Import failed')
      setImportPreview(null)
    }
  }

  function handleSendQuickScreenToDealInputs() {
    setFormValues((prev) => ({
      ...prev,
      ...mapQuickScreenToDealInputs(quickScreenInputs, quickScreenResults),
    }))
    setTab('dashboard')
  }

  // Acquisition-side quick screen send (the mapped values arrive already
  // shaped by mapAcquisitionQuickScreenToDealInputs, incl. dealType).
  function handleSendAcquisitionToDealInputs(values: Record<string, unknown>) {
    setFormValues((prev) => ({ ...prev, ...values }))
    setTab('dashboard')
  }

  function handleLoadQuickScreenScenario(inputs: QuickScreenInputs) {
    setQuickScreenInputs(inputs)
    // B10: a saved quick-screen scenario is development-shaped — show that napkin.
    setQuickScreenMode('development')
    setTab('quickscreen')
  }

  const visibleSections = useMemo(() => {
    if (state.status !== 'ready') return []
    return state.schema.sections.filter((s) => isVisible(s.visibleWhen, formValues))
  }, [state, formValues])

  // P1: sidebar metrics for this dealflow (untyped deals see everything).
  const visibleMetrics = useMemo(
    () =>
      state.status === 'ready'
        ? state.schema.outputs.filter((m) => isOutputVisibleFor(m.id, activeDealType))
        : [],
    [state, activeDealType],
  )

  if (state.status === 'loading') {
    return <div className="p-8 text-slate-500">Loading…</div>
  }

  if (state.status === 'auth') {
    return <AuthGate onAuthenticated={() => void boot()} />
  }

  if (state.status === 'error') {
    return (
      <div className="p-8">
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-red-700">
          Could not reach the backend API: {state.message}
          <div className="mt-1 text-sm text-red-500">
            Is the FastAPI server running at http://127.0.0.1:8000?
          </div>
          <button
            onClick={() => void boot()}
            className="mt-3 rounded bg-red-600 px-3 py-1 text-sm text-white hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  const { schema, apiOk } = state
  const activeDeal = deals.find((d) => d.id === activeDealId) ?? null
  const recentDeals = recentIds
    .map((id) => deals.find((d) => d.id === id))
    .filter((d): d is Deal => d !== undefined)
    .map((d) => ({ id: d.id, name: d.name, dealType: dealTypeOf(d) }))

  function handleFieldChange(fieldId: string, value: unknown) {
    setFormValues((prev) => ({ ...prev, [fieldId]: value }))
  }

  function goToSection(sectionId: string) {
    setTab('dashboard')
    requestAnimationFrame(() => {
      document.getElementById(`section-${sectionId}`)?.scrollIntoView({ behavior: 'smooth' })
    })
  }

  return (
    <Layout
      nav={
        <ul className="space-y-1">
          {visibleSections.map((section) => (
            <li key={section.id}>
              <button
                onClick={() => goToSection(section.id)}
                className="w-full rounded px-2 py-1.5 text-left text-sm text-slate-600 hover:bg-slate-100"
              >
                {section.label}
              </button>
            </li>
          ))}
        </ul>
      }
      summary={
        <>
          <div
            className={`mb-3 rounded px-2 py-1 text-xs ${
              apiOk ? 'text-emerald-600' : 'text-amber-600'
            }`}
          >
            API {apiOk ? 'connected' : 'unreachable'}
          </div>
          {Array.from(new Set(visibleMetrics.map((m) => m.group ?? 'Metrics'))).map((group) => (
            <div key={group} className="mb-4">
              <div className="mb-1.5 text-[11px] font-semibold tracking-wide text-slate-400">
                {group.toUpperCase()}
              </div>
              <ul className="space-y-1.5 text-sm">
                {visibleMetrics
                  .filter((m) => (m.group ?? 'Metrics') === group)
                  .map((metric) => {
                    // Provenance ladder: server-recalc > native engine >
                    // quick-screen estimate. A lower tier never overwrites a
                    // higher one, and estimates only ever appear while the
                    // Quick Screen tab is active.
                    const server = serverOutputs[metric.id]
                    const native = nativeOutputs[metric.id]
                    const estimate = tab === 'quickscreen' ? quickScreenOutputs[metric.id] : undefined
                    const displayValue = server !== undefined ? server : native !== undefined ? native : estimate
                    const provenance =
                      server !== undefined
                        ? 'server'
                        : native !== undefined
                          ? 'native'
                          : estimate !== undefined
                            ? 'estimate'
                            : 'none'
                    const isFullModelOnly =
                      tab === 'quickscreen' && displayValue === undefined && quickScreenFullModelOnlyIds.has(metric.id)
                    return (
                      <li key={metric.id} className="group flex items-center justify-between text-slate-500">
                        <span>
                          {metric.label}
                          {metric.type !== ('text' as string) && (
                            <button
                              onClick={() => setGoalSeekMetric(metric)}
                              title={`Goal-seek ${metric.label}`}
                              className="ml-1 hidden text-[10px] text-sky-500 hover:text-sky-700 group-hover:inline"
                            >
                              ◎
                            </button>
                          )}
                        </span>
                        <span
                          title={
                            isFullModelOnly ? 'Requires full underwriting — map a template and generate.' : undefined
                          }
                          className={
                            provenance === 'server'
                              ? 'font-medium text-slate-800'
                              : provenance === 'native'
                                ? 'font-medium text-slate-700'
                                : provenance === 'estimate'
                                  ? 'italic text-slate-400'
                                  : 'text-slate-400'
                          }
                        >
                          {formatOutputValue(metric, displayValue)}
                          {provenance === 'native' && (
                            <span className="ml-1 text-[10px] font-normal text-sky-500">native</span>
                          )}
                          {provenance === 'estimate' && (
                            <span className="ml-1 not-italic text-slate-300">est.</span>
                          )}
                        </span>
                      </li>
                    )
                  })}
              </ul>
              {group === 'Returns' && nativeIrrConvention && (
                <p className="mt-1 text-[10px] text-slate-400">
                  IRRs:{' '}
                  {nativeIrrConvention === 'xirr'
                    ? 'date-based XIRR (Actual/365)'
                    : 'periodic monthly, annualized'}
                </p>
              )}
            </div>
          ))}
          <p className="mt-4 text-xs text-slate-400">
            {tab === 'quickscreen'
              ? 'Bold values come from a server generation or the native engine; muted italic values marked "est." are Quick Screen approximations.'
              : Object.keys(serverOutputs).length > 0 || Object.keys(nativeOutputs).length > 0
                ? 'Bold slate values are from the last server-side recalculated generation; values tagged "native" are from the built-in pro-forma engine.'
                : 'Metrics populate after "Compute (native)" or generating with "Recalculate on server" enabled.'}
          </p>
        </>
      }
    >
      {goalSeekMetric && (
        <GoalSeekModal
          schema={schema}
          metric={goalSeekMetric}
          values={formValues}
          onApply={(fieldId, value) => handleFieldChange(fieldId, value)}
          onClose={() => setGoalSeekMetric(null)}
        />
      )}
      {/* The deal header + workflow tabs stay pinned while tab content
          scrolls (main is the scroll container). Negative margins span
          main's px-8/pt-6 padding so scrolled content never peeks around
          the bar; z-30 sits above the statement's sticky cells (z-10) and
          below modals (z-50). */}
      <div className="sticky -top-6 z-30 -mx-8 -mt-6 bg-slate-50 px-8 pt-6">
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
            aria-label="Deal name"
            value={renamingName}
            onChange={(e) => setRenamingName(e.target.value)}
            // B14: read the live DOM value — the `renamingName` closure can be
            // one keystroke stale when blur follows input in the same tick.
            onBlur={(e) => void handleRenameDeal(e.currentTarget.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void handleRenameDeal(e.currentTarget.value)
              if (e.key === 'Escape') setRenamingName(null)
            }}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          />
        )}
        {/* Type badge: which dealflow the active deal belongs to. B3: an
            untyped deal gets an explicit set-type affordance instead of a
            silent blank — the engine cannot compute without one. */}
        {activeDealType ? (
          <span
            className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
              activeDealType === 'development'
                ? 'bg-orange-100 text-orange-700'
                : 'bg-sky-100 text-sky-700'
            }`}
          >
            {activeDealType === 'development' ? 'DEV' : 'ACQ'}
          </span>
        ) : (
          activeDealId && (
            <span
              role="group"
              aria-label="Set deal type"
              className="flex items-center gap-1 rounded border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700"
            >
              Untyped — set type:
              <button
                onClick={() => void handleSetDealType(activeDealId, 'acquisition')}
                className="rounded border border-sky-400 bg-white px-1.5 py-0.5 text-sky-700 hover:bg-sky-50"
              >
                Acquisition
              </button>
              <button
                onClick={() => void handleSetDealType(activeDealId, 'development')}
                className="rounded border border-orange-400 bg-white px-1.5 py-0.5 text-orange-700 hover:bg-orange-50"
              >
                Development
              </button>
            </span>
          )
        )}
        <div className="relative" ref={newDealMenuRef}>
          <button
            onClick={handleNewDealClick}
            aria-haspopup="menu"
            aria-expanded={newDealMenuOpen}
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            New Deal ▾
          </button>
          {newDealMenuOpen && (
            <div
              role="menu"
              className="absolute left-0 top-full z-40 mt-1 w-36 rounded border border-slate-200 bg-white py-1 shadow-lg"
            >
              <button
                role="menuitem"
                onClick={() => void handleNewDeal('acquisition')}
                className="block w-full px-3 py-1.5 text-left text-xs text-slate-700 hover:bg-sky-50"
              >
                Acquisition
              </button>
              <button
                role="menuitem"
                onClick={() => void handleNewDeal('development')}
                className="block w-full px-3 py-1.5 text-left text-xs text-slate-700 hover:bg-orange-50"
              >
                Development
              </button>
            </div>
          )}
        </div>
        <div className="relative" ref={moreMenuRef}>
          <button
            onClick={() => {
              setNewDealMenuOpen(false)
              setMoreMenuOpen((v) => !v)
            }}
            aria-haspopup="menu"
            aria-expanded={moreMenuOpen}
            aria-label="More deal actions"
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
          >
            More ▾
          </button>
          {moreMenuOpen && (
            <div
              role="menu"
              className="absolute left-0 top-full z-40 mt-1 w-40 rounded border border-slate-200 bg-white py-1 shadow-lg"
            >
              <button
                role="menuitem"
                onClick={() => void handleCloneDeal()}
                className="block w-full px-3 py-1.5 text-left text-xs text-slate-700 hover:bg-slate-50"
              >
                Duplicate deal…
              </button>
              <button
                role="menuitem"
                onClick={() => void handleArchiveDeal()}
                className="block w-full px-3 py-1.5 text-left text-xs text-slate-700 hover:bg-slate-50"
              >
                Archive deal
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
          onClick={() => importInputRef.current?.click()}
          className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          Import
        </button>
        <input
          ref={importInputRef}
          type="file"
          accept="application/json,.json"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) handleImportFile(file)
            e.target.value = ''
          }}
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
        <span
          className={`ml-auto text-xs ${
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

      <nav
        aria-label="Workflow steps"
        className="mb-6 flex gap-1 overflow-x-auto border-b border-slate-200"
      >
        {TABS.map(([id, label], index) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            aria-current={tab === id ? 'page' : undefined}
            title={index < 9 ? `Ctrl/Cmd+${index + 1}` : undefined}
            className={`-mb-px shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium ${
              tab === id
                ? 'border-slate-900 text-slate-900'
                : 'border-transparent text-slate-400 hover:text-slate-600'
            }`}
          >
            {label}
          </button>
        ))}
      </nav>
      </div>

      {/* All tabs stay mounted so in-progress state (unsaved mapping edits, form
          values) survives switching tabs — only visibility toggles. */}
      <div style={{ display: tab === 'pipeline' ? 'block' : 'none' }}>
        <PipelinePage
          deals={deals}
          activeDealId={activeDealId}
          onOpenDeal={(dealId) => {
            void switchDeal(dealId).then(() => setTab('dashboard'))
          }}
          onStatusChange={(dealId, status) => {
            updateDeal(dealId, { status })
              .then((updated) =>
                setDeals((prev) => prev.map((d) => (d.id === dealId ? updated : d))),
              )
              .catch((err) => toastError(err, 'Could not change the stage.'))
          }}
          onBulkStatus={async (dealIds, status) => {
            const { updated } = await bulkUpdateDealStatus(dealIds, status)
            const byId = new Map(updated.map((d) => [d.id, d]))
            setDeals((prev) => prev.map((d) => byId.get(d.id) ?? d))
          }}
          onNewDeal={(type) => void handleNewDeal(type)}
          onNewDealFromDocuments={() => setOmWizardOpen(true)}
          onSetDealType={(dealId, type) => void handleSetDealType(dealId, type)}
          onDealsChanged={() => void refreshDeals()}
        />
      </div>

      <Toasts />

      <CommandPalette
        open={paletteOpen}
        recent={recentDeals}
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
          dealId={activeDealId}
        />
      </div>

      <div style={{ display: tab === 'documents' ? 'block' : 'none' }}>
        <Documents
          schema={schema}
          currentUnitMix={formValues.unitMix}
          currentCommercialLeases={formValues.commercialLeases}
          onApplyExtraction={(confirmedValues) => {
            setFormValues((prev) => ({ ...prev, ...confirmedValues }))
            setTab('dashboard')
          }}
        />
      </div>

      <div style={{ display: tab === 'setup' ? 'block' : 'none' }}>
        <TemplateUpload
          onTemplateReady={(template, mappingProfileId) => {
            setActiveTemplate(template)
            setActiveMappingProfileId(mappingProfileId)
            if (activeDealId) {
              updateDeal(activeDealId, {
                activeTemplateId: template?.id ?? null,
                activeMappingProfileId: mappingProfileId,
              }).catch((err) => toastError(err, 'Could not save the template selection.'))
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
            applyDealState(schema, deal, new URLSearchParams())
            setDeals((prev) => prev.map((d) => (d.id === deal.id ? deal : d)))
          }}
        />
        <PresetsPanel
          schema={schema}
          values={formValues}
          onApply={(patch) => setFormValues((prev) => ({ ...prev, ...patch }))}
        />
        <DealInputForm schema={schema} values={formValues} onFieldChange={handleFieldChange} />
        {/* B4: per-deal panels remount on switch so results never leak across
            deals; a compute that resolves after a switch is dropped because
            the closure's deal id no longer matches the active one. */}
        <GeneratePanel
          key={activeDealId ?? 'none'}
          template={activeTemplate}
          mappingProfileId={activeMappingProfileId}
          values={formValues}
          onGenerated={(outputs) => {
            if (activeDealIdRef.current !== activeDealId) return
            setServerOutputs(outputs)
          }}
          onComputedNative={(outputs, debt, irrConvention, statement) => {
            if (activeDealIdRef.current !== activeDealId) return
            setNativeOutputs(outputs)
            setNativeDebt(debt as Record<string, unknown> | null)
            setNativeIrrConvention(irrConvention ?? null)
            setNativeStatement(statement ?? null)
          }}
        />
      </div>

      <div style={{ display: tab === 'cashflow' ? 'block' : 'none' }}>
        <CashFlowTab
          key={activeDealId ?? 'none'}
          statement={nativeStatement}
          values={formValues}
          onGoToCompute={() => setTab('dashboard')}
        />
      </div>

      <div style={{ display: tab === 'sensitivity' ? 'block' : 'none' }}>
        <SensitivityPanel
          key={activeDealId ?? 'none'}
          schema={schema}
          template={activeTemplate}
          mappingProfileId={activeMappingProfileId}
          baseValues={formValues}
          dealId={activeDealId}
        />
      </div>

      <div style={{ display: tab === 'risk' ? 'block' : 'none' }}>
        <RiskPanel
          key={activeDealId ?? 'none'}
          schema={schema}
          values={formValues}
          dealId={activeDealId}
        />
      </div>

      <div style={{ display: tab === 'scenarios' ? 'block' : 'none' }}>
        <ScenariosPanel
          key={activeDealId ?? 'none'}
          schema={schema}
          template={activeTemplate}
          mappingProfileId={activeMappingProfileId}
          values={formValues}
          active={tab === 'scenarios'}
          dealId={activeDealId}
          computedOutputs={{ ...nativeOutputs, ...serverOutputs }}
          computedDebt={nativeDebt}
          onLoadScenario={(inputs) => {
            setFormValues(inputs)
            setTab('dashboard')
          }}
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
