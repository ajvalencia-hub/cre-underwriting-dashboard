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
import ScenariosPanel from './pages/ScenariosPanel'
import SensitivityPanel from './pages/SensitivityPanel'
import TemplateUpload from './pages/TemplateUpload'
import {
  createDeal,
  deleteDeal,
  exportDeal,
  fetchDeal,
  fetchDeals,
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
import type { Statement } from './lib/cashflowStatement'
import { formatOutputValue } from './lib/formatValue'
import { flattenFields } from './lib/schemaFields'
import { isVisible } from './lib/visibility'
import {
  QUICK_SCREEN_DEFAULTS,
  QUICK_SCREEN_FULL_MODEL_ONLY_OUTPUT_IDS,
  computeQuickScreen,
  mapQuickScreenToDealInputs,
  mapQuickScreenToOutputMetrics,
  serializeQuickScreenInputs,
  type QuickScreenInputs,
} from './lib/quickScreenMath'
import type { Deal } from './types/deal'
import type { InputSchema } from './types/schema'
import type { TemplateSummary } from './types/template'

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; schema: InputSchema; apiOk: boolean }

type Tab =
  | 'pipeline'
  | 'quickscreen'
  | 'documents'
  | 'setup'
  | 'dashboard'
  | 'cashflow'
  | 'sensitivity'
  | 'scenarios'
  | 'comps'

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
  const [tab, setTab] = useState<Tab>('quickscreen')
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

  const [deals, setDeals] = useState<Deal[]>([])
  const [activeDealId, setActiveDealId] = useState<string | null>(null)
  const [autosaveState, setAutosaveState] = useState<AutosaveState>('idle')
  const [renamingName, setRenamingName] = useState<string | null>(null)
  const [importPreview, setImportPreview] = useState<DealExportBundle | null>(null)
  const [importNotice, setImportNotice] = useState<string | null>(null)
  const importInputRef = useRef<HTMLInputElement>(null)

  const activeDealIdRef = useRef<string | null>(null)
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
  const quickScreenOutputs = useMemo(
    () => mapQuickScreenToOutputMetrics(quickScreenResults, quickScreenInputs),
    [quickScreenResults, quickScreenInputs],
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
    setServerOutputs({})
    setNativeOutputs({})
    setNativeDebt(null)
    setNativeIrrConvention(null)
    setNativeStatement(null)
    setActiveMappingProfileId(deal.activeMappingProfileId)
    if (deal.activeTemplateId) {
      fetchTemplate(deal.activeTemplateId)
        .then(setActiveTemplate)
        .catch(() => setActiveTemplate(null))
    } else {
      setActiveTemplate(null)
    }
    lastPersistedJsonRef.current = hydrated.quickScreenFromUrl
      ? '' // URL override differs from the stored deal — let the autosave sync it in
      : JSON.stringify(serializeDealInputs(hydrated.formValues, hydrated.quickScreen))
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
        // URL quick-screen params only override on first load.
        applyDealState(schema, active, new URLSearchParams(window.location.search))
        setDeals(list)
        setActiveDealId(active.id)
        setState({ status: 'ready', schema, apiOk: health.status === 'ok' })
      })
      .catch((err: Error) => {
        setState({ status: 'error', message: err.message })
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Debounced autosave of the whole working state into the active deal.
  useEffect(() => {
    if (!hydratedRef.current || activeDealId === null) return
    const blob = serializeDealInputs(formValues, quickScreenInputs)
    const json = JSON.stringify(blob)
    if (json === lastPersistedJsonRef.current) return
    lastPersistedJsonRef.current = json
    autosaverRef.current!.schedule({ dealId: activeDealId, inputs: blob })
  }, [formValues, quickScreenInputs, activeDealId])

  // Keep the sharable URL in sync with the quick screen (pre-existing behavior).
  useEffect(() => {
    const handle = setTimeout(() => {
      const params = serializeQuickScreenInputs(quickScreenInputs)
      window.history.replaceState(null, '', `${window.location.pathname}?${params.toString()}`)
    }, 500)
    return () => clearTimeout(handle)
  }, [quickScreenInputs])

  async function switchDeal(dealId: string) {
    if (state.status !== 'ready' || dealId === activeDealId) return
    await autosaverRef.current!.flush()
    const deal = await fetchDeal(dealId)
    localStorage.setItem(ACTIVE_DEAL_STORAGE_KEY, deal.id)
    // Deal switches never re-apply URL params — those are first-load-only.
    applyDealState(state.schema, deal, new URLSearchParams())
    setActiveDealId(deal.id)
    setDeals((prev) => [deal, ...prev.filter((d) => d.id !== deal.id)])
  }

  async function handleNewDeal() {
    if (state.status !== 'ready') return
    await autosaverRef.current!.flush()
    const deal = await createDeal({ name: `Untitled Deal ${deals.length + 1}` })
    setDeals((prev) => [deal, ...prev])
    localStorage.setItem(ACTIVE_DEAL_STORAGE_KEY, deal.id)
    applyDealState(state.schema, deal, new URLSearchParams())
    setActiveDealId(deal.id)
  }

  async function handleRenameDeal(name: string) {
    if (!activeDealId || !name.trim()) {
      setRenamingName(null)
      return
    }
    const updated = await updateDeal(activeDealId, { name: name.trim() })
    setDeals((prev) => prev.map((d) => (d.id === updated.id ? updated : d)))
    setRenamingName(null)
  }

  async function handleDeleteDeal() {
    if (state.status !== 'ready' || !activeDealId) return
    const deal = deals.find((d) => d.id === activeDealId)
    if (!window.confirm(`Delete "${deal?.name ?? 'this deal'}" and all its scenarios?`)) return
    await deleteDeal(activeDealId)
    const remaining = deals.filter((d) => d.id !== activeDealId)
    if (remaining.length === 0) {
      const fresh = await createDeal({ name: 'Default Deal' })
      setDeals([fresh])
      localStorage.setItem(ACTIVE_DEAL_STORAGE_KEY, fresh.id)
      applyDealState(state.schema, fresh, new URLSearchParams())
      setActiveDealId(fresh.id)
      return
    }
    setDeals(remaining)
    localStorage.setItem(ACTIVE_DEAL_STORAGE_KEY, remaining[0].id)
    applyDealState(state.schema, remaining[0], new URLSearchParams())
    setActiveDealId(remaining[0].id)
  }

  async function handleExportDeal() {
    if (!activeDealId) return
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
      localStorage.setItem(ACTIVE_DEAL_STORAGE_KEY, imported.id)
      applyDealState(state.schema, imported, new URLSearchParams())
      setActiveDealId(imported.id)
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

  function handleLoadQuickScreenScenario(inputs: QuickScreenInputs) {
    setQuickScreenInputs(inputs)
    setTab('quickscreen')
  }

  const visibleSections = useMemo(() => {
    if (state.status !== 'ready') return []
    return state.schema.sections.filter((s) => isVisible(s.visibleWhen, formValues))
  }, [state, formValues])

  if (state.status === 'loading') {
    return <div className="p-8 text-slate-500">Loading…</div>
  }

  if (state.status === 'error') {
    return (
      <div className="p-8">
        <div className="rounded-md border border-red-200 bg-red-50 p-4 text-red-700">
          Could not reach the backend API: {state.message}
          <div className="mt-1 text-sm text-red-500">
            Is the FastAPI server running at http://127.0.0.1:8000?
          </div>
        </div>
      </div>
    )
  }

  const { schema, apiOk } = state
  const activeDeal = deals.find((d) => d.id === activeDealId) ?? null

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
          {Array.from(new Set(schema.outputs.map((m) => m.group ?? 'Metrics'))).map((group) => (
            <div key={group} className="mb-4">
              <div className="mb-1.5 text-[11px] font-semibold tracking-wide text-slate-400">
                {group.toUpperCase()}
              </div>
              <ul className="space-y-1.5 text-sm">
                {schema.outputs
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
                      <li key={metric.id} className="flex items-center justify-between text-slate-500">
                        <span>{metric.label}</span>
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
        <button
          onClick={() => void handleNewDeal()}
          className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          New Deal
        </button>
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

      <div className="mb-6 flex gap-1 border-b border-slate-200">
        {(
          [
            ['pipeline', 'Deals'],
            ['quickscreen', '0. Quick Screen'],
            ['documents', '1. Documents'],
            ['setup', '2. Template & Mapping'],
            ['dashboard', '3. Deal Inputs'],
            ['cashflow', '4. Cash Flow'],
            ['sensitivity', '5. Sensitivity'],
            ['scenarios', '6. Scenarios'],
            ['comps', '7. Comps'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            onClick={() => setTab(id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              tab === id
                ? 'border-slate-900 text-slate-900'
                : 'border-transparent text-slate-400 hover:text-slate-600'
            }`}
          >
            {label}
          </button>
        ))}
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
            void updateDeal(dealId, { status }).then((updated) =>
              setDeals((prev) => prev.map((d) => (d.id === dealId ? updated : d))),
            )
          }}
          onNewDeal={() => void handleNewDeal()}
        />
      </div>

      <div style={{ display: tab === 'quickscreen' ? 'block' : 'none' }}>
        <QuickScreen
          inputs={quickScreenInputs}
          onInputsChange={setQuickScreenInputs}
          results={quickScreenResults}
          onSendToDealInputs={handleSendQuickScreenToDealInputs}
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
              void updateDeal(activeDealId, {
                activeTemplateId: template?.id ?? null,
                activeMappingProfileId: mappingProfileId,
              })
            }
          }}
        />
      </div>

      <div style={{ display: tab === 'dashboard' ? 'block' : 'none' }}>
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
        <GeneratePanel
          template={activeTemplate}
          mappingProfileId={activeMappingProfileId}
          values={formValues}
          onGenerated={setServerOutputs}
          onComputedNative={(outputs, debt, irrConvention, statement) => {
            setNativeOutputs(outputs)
            setNativeDebt(debt as Record<string, unknown> | null)
            setNativeIrrConvention(irrConvention ?? null)
            setNativeStatement(statement ?? null)
          }}
        />
      </div>

      <div style={{ display: tab === 'cashflow' ? 'block' : 'none' }}>
        <CashFlowTab
          statement={nativeStatement}
          values={formValues}
          onGoToCompute={() => setTab('dashboard')}
        />
      </div>

      <div style={{ display: tab === 'sensitivity' ? 'block' : 'none' }}>
        <SensitivityPanel
          schema={schema}
          template={activeTemplate}
          mappingProfileId={activeMappingProfileId}
          baseValues={formValues}
          dealId={activeDealId}
        />
      </div>

      <div style={{ display: tab === 'scenarios' ? 'block' : 'none' }}>
        <ScenariosPanel
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

      <div style={{ display: tab === 'comps' ? 'block' : 'none' }}>
        <CompsPage dealMarket={typeof formValues.market === 'string' ? formValues.market : ''} />
      </div>
    </Layout>
  )
}

export default App
