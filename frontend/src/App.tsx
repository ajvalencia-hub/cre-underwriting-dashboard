import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
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
  ApiError,
  UNAUTHORIZED_EVENT,
  approveAgentProposal,
  archiveDeal,
  cloneDeal,
  createDeal,
  dealConcurrency,
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
  isConflictError,
  updateDeal,
  fetchIc,
  type DealExportBundle,
  type IcSummary,
} from './lib/api'
import {
  ACTIVE_DEAL_STORAGE_KEY,
  createAutosaver,
  hydrateDealState,
  modeToPersist,
  serializeDealInputs,
  type Autosaver,
  type AutosaveState,
  type QuickScreenMode,
  type SaveConflict,
} from './lib/dealPersistence'
import { safeStorage } from './lib/safeStorage'
import { RECENT_DEALS_KEY, loadRecent, recordRecent } from './lib/recentDeals'
import { dealTypeOf } from './lib/dealStages'
import AuthGate from './components/AuthGate'
import PanelBoundary from './components/PanelBoundary'
import ShortcutsDialog from './components/ShortcutsDialog'
import AgentDock from './components/AgentDock'
import ComparePage from './pages/ComparePage'
import AgentPage from './pages/AgentPage'
import type { AgentProposal } from './types/agent'
import { defaultValuesFor, flattenFields } from './lib/schemaFields'
import { isVisible } from './lib/visibility'
import { mapQuickScreenToDealInputs, type QuickScreenInputs } from './lib/quickScreenMath'
import type { Deal } from './types/deal'
import CommandPalette from './components/CommandPalette'
import CriticalDatesEditor from './components/CriticalDatesEditor'
import FileCabinet from './components/FileCabinet'
import { saveOutput } from './lib/saveOutput'
import { showToast, toastError } from './lib/toast'
import { isDesktop, reportUnsavedToShell } from './lib/platform'
import MetricsSidebar from './components/MetricsSidebar'
import ResultsStatus from './components/ResultsStatus'
import { focusUnparsedEntry, goToField } from './lib/goToField'
import { orderSections } from './lib/sectionOrder'
import { describeInputChanges, inputChangesPrompt } from './lib/inputChanges'
import { inputsKey, isStale, latestStamp, pickMetric } from './lib/resultFreshness'
import { useComputeResults } from './lib/useComputeResults'
import { useQuickScreens } from './app/useQuickScreens'
import { parseShareLink, type SharedScreen } from './lib/shareLink'
import GoalSeekModal from './components/GoalSeekModal'
import OmWizard from './components/OmWizard'
import type { DealType } from './lib/dealStages'
import type { InputSchema, OutputMetric } from './types/schema'
import type { TemplateSummary } from './types/template'
import { clearProvenance, recordProvenance, sameSourceFor, type FieldProvenance } from './lib/provenance'
import { MULTI_DEAL_TABS, loadLastTab, rememberTab, tabLabel, type Tab } from './app/navigation'
import ModuleNav from './components/ModuleNav'
import DealHeaderBar from './components/DealHeaderBar'
import DealImportNotices from './components/DealImportNotices'
import UpdateBanner from './components/UpdateBanner'
import { buildPaletteCommands } from './app/paletteCommands'
import { isLockedField } from './lib/icWorkflow'
import { isForSaleDeal } from './lib/headlineMetrics'
import IcApprovalPage from './pages/IcApprovalPage'

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  // The server wants an API token and this browser has no session
  // (never in the desktop app — its launcher token protects the API).
  | { status: 'auth' }
  | { status: 'ready'; schema: InputSchema; apiOk: boolean }

const HEALTH_POLL_MS = 30_000

/** Thrown by the autosave's save function instead of hitting the network
 *  while an edit conflict (412) waits for the user's Reload / Overwrite. */
class SaveParkedError extends Error {
  constructor() {
    super('Save paused: this deal was changed elsewhere')
    this.name = 'SaveParkedError'
  }
}

/** Keys of `a` and `b` whose values differ (JSON comparison). */
function changedKeys(a: Record<string, unknown>, b: Record<string, unknown>): string[] {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)])
  return [...keys].filter((k) => JSON.stringify(a[k]) !== JSON.stringify(b[k]))
}

/** One tab's content. All tabs stay mounted (in-progress state survives
 *  switching) — only visibility toggles. Each sits in its own error
 *  boundary, so one crashing panel doesn't take down the header, the
 *  sidebar or the other tabs. */
function TabPane({ id, current, children }: { id: Tab; current: Tab; children: ReactNode }) {
  return (
    <div style={{ display: current === id ? 'block' : 'none' }}>
      <PanelBoundary name={tabLabel(id)}>{children}</PanelBoundary>
    </div>
  )
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

function App() {
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [tab, setTab] = useState<Tab>(loadLastTab)
  useEffect(() => rememberTab(tab), [tab])
  const [formValues, setFormValues] = useState<Record<string, unknown>>({})
  const [activeTemplate, setActiveTemplate] = useState<TemplateSummary | null>(null)
  const [activeMappingProfileId, setActiveMappingProfileId] = useState<string | null>(null)
  const [mappingUnsaved, setMappingUnsaved] = useState(false)
  const quickScreens = useQuickScreens()
  // A Quick Screen link the app was opened with, waiting for the user to
  // open it (it replaces this deal's napkin) or dismiss it.
  const [sharedFromLink, setSharedFromLink] = useState<SharedScreen | null>(null)
  // The saved scenario the working inputs were loaded from (header chip).
  const [loadedScenario, setLoadedScenario] = useState<{ name: string; key: string } | null>(null)
  // Roadmap #28: the active deal's investment-committee record. While it's
  // locked the server refuses underwriting-input changes, so the UI doesn't
  // make any (an autosave it refused would retry forever).
  const [ic, setIc] = useState<IcSummary | null>(null)
  const icLocked = ic?.locked ?? false
  // J7: which sidebar metric the Goal Seek modal is open for.
  const [goalSeekMetric, setGoalSeekMetric] = useState<OutputMetric | null>(null)
  // J10: OM-to-deal wizard visibility.
  const [omWizardOpen, setOmWizardOpen] = useState(false)
  // J11: critical-dates editor visibility.
  const [datesEditorOpen, setDatesEditorOpen] = useState(false)
  // J13: Cmd+K command palette.
  const [paletteOpen, setPaletteOpen] = useState(false)

  const [deals, setDeals] = useState<Deal[]>([])
  const [activeDealId, setActiveDealId] = useState<string | null>(null)
  const [autosaveState, setAutosaveState] = useState<AutosaveState>('idle')
  const [importPreview, setImportPreview] = useState<DealExportBundle | null>(null)
  const [importNotice, setImportNotice] = useState<string | null>(null)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  // Recently opened deal ids, newest first (the palette's "Recent deals").
  const [recentIds, setRecentIds] = useState<string[]>(() => loadRecent(safeStorage))
  // A 412 on autosave (browser mode): this deal changed in another tab.
  const [conflict, setConflict] = useState<SaveConflict<Deal> | null>(() => dealConcurrency.conflict())
  useEffect(() => dealConcurrency.subscribe(setConflict), [])

  const activeDealIdRef = useRef<string | null>(null)
  // Computed results (engine + Excel read-back), each stamped with the deal
  // and inputs it came from — see lib/resultFreshness.ts.
  const results = useComputeResults(activeDealIdRef)
  const hydratedRef = useRef(false)
  // JSON of the state as last hydrated/saved — suppresses the no-op autosave
  // that hydration itself would otherwise trigger.
  const lastPersistedJsonRef = useRef('')
  // The Quick Screen mode as the server stores it for the active deal (null:
  // never stored) — see modeToPersist.
  const storedModeRef = useRef<QuickScreenMode | null>(null)
  const autosaverRef = useRef<Autosaver<{ dealId: string; inputs: Record<string, unknown> }> | null>(null)
  if (autosaverRef.current === null) {
    autosaverRef.current = createAutosaver(
      async ({ dealId, inputs }) => {
        // A parked conflict must not hit the network until the user picks
        // Reload or Overwrite.
        if (dealConcurrency.isBlocked(dealId)) throw new SaveParkedError()
        try {
          // If-Match (browser only — updateDeal drops it in the desktop app).
          const updated = await updateDeal(dealId, { inputs }, { ifMatch: dealConcurrency.ifMatchFor(dealId) })
          // Keep the list's copy current (the header's untyped chip and the
          // pipeline read it).
          setDeals((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
        } catch (err) {
          if (isConflictError(err)) dealConcurrency.markConflict({ dealId, current: err.current, etag: err.etag })
          throw err
        }
      },
      2000,
      // A 412 (or a parked save) never enters the retry loop: retrying can't fix it.
      { shouldRetry: (err) => !(isConflictError(err) || err instanceof SaveParkedError) },
    )
  }


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
  const hasUnsavedWork =
    autosaveState === 'pending' || autosaveState === 'saving' || autosaveState === 'error' || autosaveState === 'blocked'
  useEffect(() => {
    reportUnsavedToShell(hasUnsavedWork)
    if (!hasUnsavedWork) return
    function onBeforeUnload(e: BeforeUnloadEvent) {
      e.preventDefault()
      // Kick off the save; if it lands before the user answers, nothing is lost.
      void autosaverRef.current!.flush()
    }
    // The tab went to the background (switched away, minimized, a phone
    // locking): save now rather than after the debounce — a hidden tab may
    // be discarded without a beforeunload.
    function onVisibilityChange() {
      if (document.visibilityState === 'hidden') void autosaverRef.current!.flush()
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => {
      window.removeEventListener('beforeunload', onBeforeUnload)
      document.removeEventListener('visibilitychange', onVisibilityChange)
    }
  }, [hasUnsavedWork])

  function applyDealState(schema: InputSchema, deal: Deal) {
    const hydrated = hydrateDealState(defaultValuesFor(schema), deal.inputs)
    setFormValues(hydrated.formValues)
    quickScreens.setDevelopment(hydrated.quickScreen)
    quickScreens.setAcquisition(hydrated.acquisitionQuickScreen)
    // The napkin the deal was last left on (development when never chosen).
    quickScreens.setMode(hydrated.quickScreenMode ?? 'development')
    storedModeRef.current = hydrated.quickScreenMode
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

  /** Make `deal` the active deal: remember it (storage + recent list),
   *  hydrate the form from it and drop any edit conflict left on another
   *  deal. Every path that opens a deal goes through here. */
  function activateDeal(schema: InputSchema, deal: Deal) {
    const parked = dealConcurrency.conflict()
    if (parked && parked.dealId !== deal.id) dealConcurrency.forget(parked.dealId)
    safeStorage.set(ACTIVE_DEAL_STORAGE_KEY, deal.id)
    setRecentIds(recordRecent(safeStorage, deal.id))
    applyDealState(schema, deal)
    setActiveDealId(deal.id)
  }

  // Where the app was when a 401 raised the token gate mid-session: signing
  // in again resumes it (unsaved edits intact) instead of re-booting.
  const resumeAfterAuthRef = useRef<LoadState | null>(null)

  async function boot() {
    setState({ status: 'loading' })
    try {
      // Browser/Docker mode with CRE_API_TOKEN set: ask for the token first.
      // Never in the desktop app (its launcher token protects the API).
      if (!isDesktop()) {
        const auth = await fetchAuthStatus().catch(() => null)
        if (auth?.required && !auth.authenticated) {
          setState({ status: 'auth' })
          return
        }
      }
      const [schema, health, dealList] = await Promise.all([fetchInputSchema(), fetchHealth(), fetchDeals()])
      let list = dealList
      if (list.length === 0) {
        list = [await createDeal({ name: 'Default Deal' })]
      }
      const storedId = safeStorage.get(ACTIVE_DEAL_STORAGE_KEY)
      let active = list.find((d) => d.id === storedId) ?? list[0]
      // A single-deal read records the deal's ETag, so the first autosave
      // is already guarded (the list response carries none).
      active = await fetchDeal(active.id).catch(() => active)
      activateDeal(schema, active)
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
          quickScreens.setMode(shared.mode)
        }
      }
      const fresh = active
      setDeals(list.map((d) => (d.id === fresh.id ? fresh : d)))
      setState({ status: 'ready', schema, apiOk: health.status === 'ok' })
    } catch (err) {
      // A 401 already raised the token gate (UNAUTHORIZED_EVENT); keep it.
      if (err instanceof ApiError && err.status === 401 && !isDesktop()) {
        setState({ status: 'auth' })
        return
      }
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

  // Any 401 (session expired, token rotated) shows the token gate. Browser
  // mode only — apiError() never fires the event in the desktop app.
  useEffect(() => {
    function onUnauthorized() {
      setState((prev) => {
        if (prev.status === 'auth') return prev
        if (prev.status === 'ready') resumeAfterAuthRef.current = prev
        return { status: 'auth' }
      })
    }
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  function handleAuthenticated() {
    const resume = resumeAfterAuthRef.current
    resumeAfterAuthRef.current = null
    if (resume) {
      // Back where we were; push whatever didn't save while signed out.
      setState(resume)
      void autosaverRef.current!.flush()
    } else {
      void boot()
    }
  }

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
    const mode = modeToPersist(storedModeRef.current, quickScreens.mode, icLocked)
    const blob = serializeDealInputs(formValues, quickScreens.development, quickScreens.acquisition, mode)
    const json = JSON.stringify(blob)
    if (json === lastPersistedJsonRef.current) return
    lastPersistedJsonRef.current = json
    storedModeRef.current = mode
    autosaverRef.current!.schedule({ dealId: activeDealId, inputs: blob })
  }, [formValues, quickScreens.development, quickScreens.acquisition, quickScreens.mode, icLocked, activeDealId])

  /** The Deal.inputs blob for what's on screen now (explicit saves). */
  function currentInputsBlob(overrides: Record<string, unknown> = {}): Record<string, unknown> {
    const mode = modeToPersist(storedModeRef.current, quickScreens.mode, icLocked)
    return serializeDealInputs(
      { ...formValuesRef.current, ...overrides },
      quickScreens.development,
      quickScreens.acquisition,
      mode,
    )
  }


  /** Before leaving the current deal: make sure its edits reached the
   *  server. If they didn't, stay put — otherwise the retry would be
   *  superseded by the next deal's saves and the edits silently lost. */
  async function ensureSaved(): Promise<boolean> {
    const ok = await autosaverRef.current!.flush()
    if (!ok && autosaverRef.current!.getState() === 'blocked') {
      showToast({
        kind: 'error',
        message: "This deal's latest changes haven't been saved, so you're staying on it",
        detail: 'It was changed in another tab or window — choose Reload or Overwrite in the banner first.',
      })
    } else if (!ok) {
      toastError(
        "This deal's latest changes haven't been saved yet, so you're staying on it",
        'The server did not accept the save. The app keeps retrying — try again in a moment.',
      )
    }
    return ok
  }

  useEffect(() => {
    setIc(null)
    if (!activeDealId) return
    let current = true
    fetchIc(activeDealId)
      .then((summary) => {
        if (current) setIc(summary)
      })
      .catch((err) => toastError("Couldn't load this deal's investment-committee record", err))
    return () => {
      current = false
    }
  }, [activeDealId])

  /** True (after saying why) when a change would touch underwriting inputs
   *  the investment committee has locked. */
  function blockedByIcLock(fieldIds: string[]): boolean {
    if (!icLocked || !fieldIds.some(isLockedField)) return false
    showToast({
      kind: 'error',
      message: 'Inputs are locked for the investment committee',
      detail: 'Reopen the deal with a reason on the IC Approval tab to change them.',
    })
    return true
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
      // Deal switches never re-apply URL params — those are first-load-only.
      activateDeal(state.schema, deal)
      setDeals((prev) => [deal, ...prev.filter((d) => d.id !== deal.id)])
    } catch (err) {
      toastError("Couldn't open that deal — you're still on the current one", err)
    }
  }

  // Typed creation: every new deal carries its dealflow (acquisition |
  // development) in inputs from birth, so server-side surfaces (share, deck,
  // portfolio, hold-sweep) agree with the form instead of splitting between
  // "missing dealType" and a silent acquisition default.
  async function handleNewDeal(type: DealType): Promise<boolean> {
    if (state.status !== 'ready') return false
    if (!(await ensureSaved())) return false
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
      activateDeal(state.schema, deal)
    } catch (err) {
      toastError("Couldn't create the deal", err)
    }
    return true
  }

  // Assign a dealflow to an untyped (legacy) deal. The active deal routes
  // through the normal field-change path so autosave/history record it; an
  // inactive deal merges server-side directly.
  async function handleSetDealType(dealId: string, type: DealType) {
    if (dealId === activeDealId) {
      // dealType is an underwriting input: an IC-locked deal refuses it
      // (scheduling the save anyway would just retry a 409 forever).
      if (blockedByIcLock(['dealType'])) return
      handleFieldChange('dealType', type)
      // Save it explicitly: the form may already show this type as its
      // default, in which case the change is a no-op for autosave and the
      // deal would stay untyped on the server. And update the pipeline's
      // deal list, which the form change alone doesn't touch — otherwise the
      // deal stayed under "untyped" and the click looked like it did nothing.
      autosaverRef.current!.schedule({ dealId, inputs: currentInputsBlob({ dealType: type }) })
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
    activateDeal(state.schema, deal)
    setTab('dashboard')
  }

  async function handleRenameDeal(name: string): Promise<boolean> {
    if (!activeDealId) return true
    try {
      // Let a save in progress land first: this write moves the deal's
      // ETag, and an overlapping autosave would 412 against it.
      await autosaverRef.current!.flush()
      const updated = await updateDeal(activeDealId, { name })
      setDeals((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
      return true
    } catch (err) {
      toastError("Couldn't rename the deal", err)
      return false
    }
  }

  /** After the active deal is gone (deleted / archived): open the next one,
   *  or seed a fresh default so the app is never dealless. */
  async function activateNextAfterRemoval(schema: InputSchema, removedId: string, what: string) {
    dealConcurrency.forget(removedId)
    setRecentIds((prev) => {
      const next = prev.filter((id) => id !== removedId)
      safeStorage.set(RECENT_DEALS_KEY, JSON.stringify(next))
      return next
    })
    try {
      const remaining = deals.filter((d) => d.id !== removedId)
      if (remaining.length === 0) {
        const fresh = await createDeal({ name: 'Default Deal' })
        setDeals([fresh])
        activateDeal(schema, fresh)
        return
      }
      const next = await fetchDeal(remaining[0].id)
      setDeals(remaining.map((d) => (d.id === next.id ? next : d)))
      activateDeal(schema, next)
    } catch (err) {
      toastError(`The deal was ${what}, but the next one could not be opened — reopen the app`, err)
    }
  }

  async function handleDeleteDeal() {
    if (state.status !== 'ready' || !activeDealId) return
    const dealId = activeDealId
    const deal = deals.find((d) => d.id === dealId)
    if (!window.confirm(`Delete "${deal?.name ?? 'this deal'}" and all its scenarios?\n\nThis cannot be undone.`)) return
    // A pending autosave would PUT to a deal that no longer exists (404,
    // retried forever): drop it — and its retry timer — first.
    const unsaved = autosaverRef.current!.hasUnsaved() ? currentInputsBlob() : null
    autosaverRef.current!.cancel()
    try {
      await deleteDeal(dealId)
    } catch (err) {
      // Nothing was removed: put the unsaved edits back in the queue.
      if (unsaved) autosaverRef.current!.schedule({ dealId, inputs: unsaved })
      toastError("Couldn't delete the deal — nothing was removed", err)
      return
    }
    await activateNextAfterRemoval(state.schema, dealId, 'deleted')
  }

  /** More ▾ → Duplicate…: copy the active deal (inputs, stage, tags,
   *  template, scenarios — not its IC record) and open the copy. */
  async function handleDuplicateDeal() {
    if (state.status !== 'ready' || !activeDealId) return
    const source = deals.find((d) => d.id === activeDealId)
    const name = window.prompt('Name for the copy', `${source?.name ?? 'Deal'} (copy)`)
    if (name === null) return
    if (!(await ensureSaved())) return
    try {
      const copy = await cloneDeal(activeDealId, name.trim() || undefined)
      setDeals((prev) => [copy, ...prev])
      activateDeal(state.schema, copy)
      showToast({ kind: 'success', message: `Opened the copy "${copy.name}"` })
    } catch (err) {
      toastError("Couldn't duplicate the deal", err)
    }
  }

  /** More ▾ → Archive: hide the deal from the working list (reversible from
   *  the pipeline's archived view) and open the next one. */
  async function handleArchiveDeal() {
    if (state.status !== 'ready' || !activeDealId) return
    const dealId = activeDealId
    const deal = deals.find((d) => d.id === dealId)
    if (
      !window.confirm(
        `Archive "${deal?.name ?? 'this deal'}"?\n\nIt leaves the deal list and pipeline; you can unarchive it from the Deals tab.`,
      )
    )
      return
    if (!(await ensureSaved())) return
    try {
      await archiveDeal(dealId)
    } catch (err) {
      toastError("Couldn't archive the deal", err)
      return
    }
    autosaverRef.current!.cancel()
    await activateNextAfterRemoval(state.schema, dealId, 'archived')
  }

  /** The header's tag chips. Tags aren't deal inputs, so this is allowed
   *  while IC-locked. Resolves false when the save failed. */
  async function handleTagsChange(tags: string[]): Promise<boolean> {
    if (!activeDealId) return false
    const dealId = activeDealId
    // Pending edits land first (this write moves the deal's ETag).
    if (!(await ensureSaved())) return false
    try {
      const updated = await updateDeal(dealId, { tags }, { ifMatch: dealConcurrency.ifMatchFor(dealId) })
      setDeals((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
      return true
    } catch (err) {
      if (isConflictError(err)) {
        dealConcurrency.markConflict({ dealId, current: err.current, etag: err.etag })
        return false
      }
      toastError("Couldn't save the tags", err)
      return false
    }
  }

  /** Conflict banner → Reload: adopt the server's copy, dropping this
   *  tab's unsaved edits. */
  function handleConflictReload() {
    if (state.status !== 'ready') return
    const resolved = dealConcurrency.chooseReload()
    if (!resolved) return
    autosaverRef.current!.cancel()
    setDeals((prev) => prev.map((d) => (d.id === resolved.dealId ? resolved.current : d)))
    if (resolved.dealId === activeDealIdRef.current) {
      applyDealState(state.schema, resolved.current)
      // The other tab may have changed the IC state too.
      fetchIc(resolved.dealId)
        .then((summary) => {
          if (activeDealIdRef.current === resolved.dealId) setIc(summary)
        })
        .catch(() => {})
    }
  }

  /** Conflict banner → Overwrite: save this tab's version without If-Match.
   *  Refused when the other tab has since locked the deal for the IC and
   *  the overwrite would change locked inputs. */
  async function handleConflictOverwrite() {
    const pending = dealConcurrency.conflict()
    if (!pending) return
    try {
      const summary = await fetchIc(pending.dealId)
      if (pending.dealId === activeDealIdRef.current) setIc(summary)
      const differing = changedKeys(currentInputsBlob(), pending.current.inputs)
      if (summary.locked && differing.some(isLockedField)) {
        showToast({
          kind: 'error',
          message: 'Inputs are locked for the investment committee',
          detail: "The deal was submitted to the IC elsewhere, so your version can't overwrite it. Choose Reload.",
        })
        return
      }
    } catch (err) {
      toastError("Couldn't check the deal's IC lock — nothing was overwritten", err)
      return
    }
    if (dealConcurrency.chooseOverwrite() === null) return
    if (!(await autosaverRef.current!.flush())) {
      toastError("Couldn't overwrite the deal", 'The save will keep retrying.')
    }
  }

  /** Agent proposal approval (AgentPage / AgentDock). Respects the IC lock,
   *  saves pending edits first, lets the server apply the changes (history
   *  kind "agent"), then adopts the returned deal and marks the changed
   *  fields as agent-filled. Resolves true when applied. */
  async function handleApproveProposal(
    proposal: Pick<AgentProposal, 'id' | 'changes'>,
    overrideChanges?: Record<string, unknown>,
  ): Promise<boolean> {
    if (state.status !== 'ready') return false
    const changes = overrideChanges ?? proposal.changes
    if (blockedByIcLock(Object.keys(changes))) return false
    if (!(await ensureSaved())) return false
    try {
      const { deal } = await approveAgentProposal(proposal.id, overrideChanges)
      setDeals((prev) => prev.map((d) => (d.id === deal.id ? deal : d)))
      if (deal.id === activeDealIdRef.current) {
        applyDealState(state.schema, deal)
        setFormValues((prev) =>
          recordProvenance(
            prev,
            sameSourceFor(Object.keys(changes), { source: 'agent', label: 'Underwriting Agent', at: new Date().toISOString() }),
          ),
        )
      }
      return true
    } catch (err) {
      toastError("Couldn't apply the agent's proposal", err)
      return false
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
      activateDeal(state.schema, imported)
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
    const lines = describeInputChanges(state.schema, formValues, next, replaceAll)
    return lines.length === 0 || window.confirm(inputChangesPrompt(what, lines))
  }

  /** Apply napkin values to the full form — after confirming any field that
   *  already holds a different value (it used to be overwritten silently). */
  function sendToDealInputs(patch: Record<string, unknown>) {
    if (blockedByIcLock(Object.keys(patch))) return
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
    if (blockedByIcLock(Object.keys(next))) return
    if (!confirmInputChanges(next, `Loading scenario "${name}"`, true)) return
    setFormValues(next)
    setLoadedScenario({ name, key: inputsKey(next) })
    setTab('dashboard')
  }

  function handleSendQuickScreenToDealInputs() {
    sendToDealInputs(mapQuickScreenToDealInputs(quickScreens.development, quickScreens.developmentResults))
  }

  // Acquisition-side quick screen send (the mapped values arrive already
  // shaped by mapAcquisitionQuickScreenToDealInputs, incl. dealType).
  function handleSendAcquisitionToDealInputs(values: Record<string, unknown>) {
    sendToDealInputs(values)
  }

  function handleLoadQuickScreenScenario(inputs: QuickScreenInputs) {
    quickScreens.setDevelopment(inputs)
    // A quick-screen scenario is a development napkin: show that one.
    quickScreens.setMode('development')
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

  if (state.status === 'auth') {
    return <AuthGate onAuthenticated={handleAuthenticated} />
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

  /** A user edit: the value is now theirs, so any "filled by the app"
   *  marker on the field goes. */
  function handleFieldChange(fieldId: string, value: unknown) {
    if (blockedByIcLock([fieldId])) return
    setFormValues((prev) => clearProvenance({ ...prev, [fieldId]: value }, fieldId))
  }

  /** Values the app filled in — recorded so the form can say where each
   *  came from (roadmap #14). */
  function applyFromSource(patch: Record<string, unknown>, entries: Record<string, FieldProvenance>) {
    if (blockedByIcLock(Object.keys(patch))) return
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

  const activeDeal = deals.find((d) => d.id === activeDealId) ?? null
  const recentDeals = recentIds
    .filter((id) => id !== activeDealId)
    .map((id) => deals.find((d) => d.id === id))
    .filter((d): d is Deal => d !== undefined)
  const agentSurface = {
    dealId: activeDealId,
    schema,
    currentValues: formValues,
    icLocked,
    onApproveProposal: handleApproveProposal,
  }

  return (
    <>
    <Layout
      nav={
        <ModuleNav tab={tab} onSelect={setTab} sections={visibleSections} onGoToSection={goToSection} />
      }
      summary={
        // The one-deal summary and Compute button don't apply on views that
        // span many deals; their tables get the width instead.
        MULTI_DEAL_TABS.has(tab) ? null : (
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
              const estimate = tab === 'quickscreen' ? quickScreens.outputs[metric.id] : undefined
              const picked = estimate === undefined ? pickMetric(metric.id, resultSets) : null
              const value = picked ? picked.value : estimate
              return {
                value,
                provenance: picked ? picked.stamp.source : estimate !== undefined ? 'estimate' : 'none',
                stale: picked ? isStale(picked.stamp, currentInputsKey, activeDealId) : false,
                fullModelOnly:
                  tab === 'quickscreen' && value === undefined && quickScreens.fullModelOnlyIds.has(metric.id),
              }
            }}
            dealType={tab === 'quickscreen' ? quickScreens.mode : formValues.dealType}
            forSale={tab !== 'quickscreen' && isForSaleDeal(formValues)}
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
        )
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
        {isDesktop() && <UpdateBanner />}
        <DealHeaderBar
          deals={deals}
          activeDealId={activeDealId}
          values={formValues}
          loadedScenario={
            loadedScenario && { name: loadedScenario.name, modified: currentInputsKey !== loadedScenario.key }
          }
          autosaveState={autosaveState}
          icState={ic?.state ?? null}
          onOpenIc={() => setTab('approval')}
          onSwitchDeal={(dealId) => void switchDeal(dealId)}
          onRename={handleRenameDeal}
          onNewDeal={handleNewDeal}
          onDelete={() => void handleDeleteDeal()}
          onExport={() => void handleExportDeal()}
          onImportFile={handleImportFile}
          onOpenDates={() => setDatesEditorOpen(true)}
          untyped={activeDeal !== null && dealTypeOf(activeDeal) === null}
          onSetType={(type) => {
            if (activeDealId) void handleSetDealType(activeDealId, type)
          }}
          onDuplicate={() => void handleDuplicateDeal()}
          onArchive={() => void handleArchiveDeal()}
          onTagsChange={handleTagsChange}
        >
          {conflict && conflict.dealId === activeDealId && (
            <div
              role="alert"
              className="mt-2 flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
            >
              <span>
                This deal was changed in another tab or window, so your latest edits weren't saved.
              </span>
              <span className="flex gap-2">
                <button
                  onClick={handleConflictReload}
                  className="rounded bg-slate-900 px-2 py-1 text-xs text-white hover:bg-slate-700"
                  title="Load the other version; your unsaved edits here are discarded"
                >
                  Reload
                </button>
                <button
                  onClick={() => void handleConflictOverwrite()}
                  className="rounded border border-amber-400 px-2 py-1 text-xs hover:bg-amber-100"
                  title="Save your version over the other one"
                >
                  Overwrite
                </button>
              </span>
            </div>
          )}
        </DealHeaderBar>

        <DealImportNotices
          notice={importNotice}
          preview={importPreview}
          onConfirm={() => void handleConfirmImport()}
          onCancel={() => setImportPreview(null)}
        />

      </div>

      {/* All tabs stay mounted so in-progress state (unsaved mapping edits, form
          values) survives switching tabs — only visibility toggles. */}
      <TabPane id="pipeline" current={tab}>
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
      </TabPane>

      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        commands={
          // Built only while open: every field of the schema, on every render.
          paletteOpen
            ? buildPaletteCommands(
                schema,
                formValues,
                setTab,
                (fieldId) => {
                  setTab('dashboard')
                  requestAnimationFrame(() => goToField(fieldId))
                },
                {
                  compute: computeNow,
                  newDeal: (type) => void handleNewDeal(type),
                  newDealFromDocuments: () => setOmWizardOpen(true),
                  exportDeal: () => void handleExportDeal(),
                  openDates: () => setDatesEditorOpen(true),
                  showShortcuts: () => setShortcutsOpen(true),
                },
                { deals: recentDeals, openDeal: (dealId) => void switchDeal(dealId) },
              )
            : []
        }
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

      {shortcutsOpen && <ShortcutsDialog onClose={() => setShortcutsOpen(false)} />}

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

      <TabPane id="quickscreen" current={tab}>
        {sharedFromLink && (
          <div className="mb-4 flex max-w-3xl flex-wrap items-center justify-between gap-2 rounded-md border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-sky-700">
            <span>
              This link contains a shared {sharedFromLink.mode} Quick Screen. Opening it replaces the napkin saved
              on “{deals.find((d) => d.id === activeDealId)?.name ?? 'this deal'}”.
            </span>
            <span className="flex gap-2">
              <button
                onClick={() => {
                  quickScreens.applyShared(sharedFromLink)
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
          inputs={quickScreens.development}
          onInputsChange={quickScreens.setDevelopment}
          results={quickScreens.developmentResults}
          mode={quickScreens.mode}
          onModeChange={quickScreens.setMode}
          acquisitionInputs={quickScreens.acquisition}
          onAcquisitionInputsChange={quickScreens.setAcquisition}
          onSendToDealInputs={handleSendQuickScreenToDealInputs}
          onSendAcquisitionToDealInputs={handleSendAcquisitionToDealInputs}
          onOpenShared={quickScreens.applyShared}
          dealId={activeDealId}
        />
      </TabPane>

      <TabPane id="documents" current={tab}>
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
      </TabPane>

      <TabPane id="setup" current={tab}>
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
      </TabPane>

      <TabPane id="dashboard" current={tab}>
        <FileCabinet dealId={activeDealId} />
        <HistoryDrawer
          schema={schema}
          dealId={activeDealId}
          onRestored={(deal) => {
            applyDealState(schema, deal)
            setDeals((prev) => prev.map((d) => (d.id === deal.id ? deal : d)))
          }}
        />
        {icLocked && ic && (
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            <span>
              {ic.state === 'approved'
                ? 'Approved by the investment committee'
                : ic.state === 'rejected'
                  ? 'Rejected by the investment committee'
                  : 'With the investment committee'}
              {' '}— these inputs are locked so they match the version the committee saw.
            </span>
            <button onClick={() => setTab('approval')} className="text-xs font-medium underline">
              Open IC Approval
            </button>
          </div>
        )}
        {/* A disabled fieldset makes every control inside read-only. */}
        <fieldset disabled={icLocked} className="min-w-0">
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
        </fieldset>
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
      </TabPane>

      <TabPane id="cashflow" current={tab}>
        <CashFlowTab
          key={dealScope}
          statement={nativeResponse?.statement ?? null}
          values={formValues}
          onGoToCompute={() => setTab('dashboard')}
          stale={nativeStale}
          onRecompute={computeNow}
        />
      </TabPane>

      <TabPane id="sensitivity" current={tab}>
        <SensitivityPanel
          key={dealScope}
          schema={schema}
          template={activeTemplate}
          mappingProfileId={activeMappingProfileId}
          mappingUnsaved={mappingUnsaved}
          baseValues={formValues}
          dealId={activeDealId}
        />
      </TabPane>

      <TabPane id="risk" current={tab}>
        <RiskPanel key={dealScope} schema={schema} values={formValues} dealId={activeDealId} />
      </TabPane>

      <TabPane id="scenarios" current={tab}>
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
      </TabPane>

      <TabPane id="approval" current={tab}>
        <IcApprovalPage
          dealId={activeDealId}
          schema={schema}
          values={formValues}
          currentOutputs={latestOutputs}
          summary={ic}
          onBeforeStep={ensureSaved}
          onSummary={setIc}
        />
      </TabPane>

      <TabPane id="portfolio" current={tab}>
        <PortfolioPage active={tab === 'portfolio'} />
      </TabPane>

      <TabPane id="settings" current={tab}>
        <SettingsPage active={tab === 'settings'} />
      </TabPane>

      <TabPane id="comps" current={tab}>
        <CompsPage dealMarket={typeof formValues.market === 'string' ? formValues.market : ''} />
      </TabPane>

      <TabPane id="compare" current={tab}>
        <ComparePage
          schema={schema}
          deals={deals}
          active={tab === 'compare'}
          onOpenDeal={(dealId) => switchDeal(dealId).then(() => setTab('dashboard'))}
        />
      </TabPane>

      <TabPane id="agent" current={tab}>
        <AgentPage key={dealScope} {...agentSurface} />
      </TabPane>
    </Layout>

    {/* The agent dock floats outside Layout's columns so it survives every
        tab switch; rendered only past boot and the token gate. */}
    <AgentDock {...agentSurface} hidden={tab === 'agent'} />
    </>
  )
}

export default App
