import { useEffect, useMemo, useState } from 'react'
import DealInputForm from './components/DealInputForm'
import GeneratePanel from './components/GeneratePanel'
import Layout from './components/Layout'
import Documents from './pages/Documents'
import QuickScreen from './pages/QuickScreen'
import ScenariosPanel from './pages/ScenariosPanel'
import SensitivityPanel from './pages/SensitivityPanel'
import TemplateUpload from './pages/TemplateUpload'
import { fetchHealth, fetchInputSchema } from './lib/api'
import { formatOutputValue } from './lib/formatValue'
import { flattenFields } from './lib/schemaFields'
import { isVisible } from './lib/visibility'
import {
  QUICK_SCREEN_DEFAULTS,
  QUICK_SCREEN_FULL_MODEL_ONLY_OUTPUT_IDS,
  computeQuickScreen,
  mapQuickScreenToDealInputs,
  mapQuickScreenToOutputMetrics,
  parseQuickScreenInputs,
  serializeQuickScreenInputs,
  type QuickScreenInputs,
} from './lib/quickScreenMath'
import type { InputSchema } from './types/schema'
import type { TemplateSummary } from './types/template'

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; schema: InputSchema; apiOk: boolean }

type Tab = 'quickscreen' | 'documents' | 'setup' | 'dashboard' | 'sensitivity' | 'scenarios'

function defaultValuesFor(schema: InputSchema): Record<string, unknown> {
  const values: Record<string, unknown> = {}
  for (const field of flattenFields(schema)) {
    if (field.default !== undefined) values[field.id] = field.default
  }
  return values
}

function App() {
  const [state, setState] = useState<LoadState>({ status: 'loading' })
  const [tab, setTab] = useState<Tab>('quickscreen')
  const [formValues, setFormValues] = useState<Record<string, unknown>>({})
  const [activeTemplate, setActiveTemplate] = useState<TemplateSummary | null>(null)
  const [activeMappingProfileId, setActiveMappingProfileId] = useState<string | null>(null)
  const [computedOutputs, setComputedOutputs] = useState<Record<string, unknown>>({})
  const [quickScreenInputs, setQuickScreenInputs] = useState<QuickScreenInputs>(
    () => parseQuickScreenInputs(new URLSearchParams(window.location.search)) ?? QUICK_SCREEN_DEFAULTS,
  )
  const quickScreenResults = useMemo(() => computeQuickScreen(quickScreenInputs), [quickScreenInputs])
  const quickScreenOutputs = useMemo(
    () => mapQuickScreenToOutputMetrics(quickScreenResults, quickScreenInputs),
    [quickScreenResults, quickScreenInputs],
  )
  const quickScreenFullModelOnlyIds = useMemo(
    () => new Set<string>(QUICK_SCREEN_FULL_MODEL_ONLY_OUTPUT_IDS),
    [],
  )

  useEffect(() => {
    const handle = setTimeout(() => {
      const params = serializeQuickScreenInputs(quickScreenInputs)
      window.history.replaceState(null, '', `${window.location.pathname}?${params.toString()}`)
    }, 500)
    return () => clearTimeout(handle)
  }, [quickScreenInputs])

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

  useEffect(() => {
    Promise.all([fetchInputSchema(), fetchHealth()])
      .then(([schema, health]) => {
        setState({ status: 'ready', schema, apiOk: health.status === 'ok' })
        setFormValues(defaultValuesFor(schema))
      })
      .catch((err: Error) => {
        setState({ status: 'error', message: err.message })
      })
  }, [])

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
                    // Real computedOutputs values always win — an estimate never
                    // overwrites a real server-recalculated value, and estimates
                    // only ever appear while the Quick Screen tab is active.
                    const real = computedOutputs[metric.id]
                    const estimate = tab === 'quickscreen' ? quickScreenOutputs[metric.id] : undefined
                    const isEstimate = real === undefined && estimate !== undefined
                    const displayValue = real !== undefined ? real : estimate
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
                            real !== undefined
                              ? 'font-medium text-slate-800'
                              : isEstimate
                                ? 'italic text-slate-400'
                                : 'text-slate-400'
                          }
                        >
                          {formatOutputValue(metric, displayValue)}
                          {isEstimate && <span className="ml-1 not-italic text-slate-300">est.</span>}
                        </span>
                      </li>
                    )
                  })}
              </ul>
            </div>
          ))}
          <p className="mt-4 text-xs text-slate-400">
            {tab === 'quickscreen'
              ? 'Bold values are from the last server-side generation; muted italic values marked "est." are Quick Screen approximations.'
              : Object.keys(computedOutputs).length > 0
                ? 'From the most recent server-side recalculated generation.'
                : 'Metrics populate after generating with "Recalculate on server" enabled, and only for output fields mapped in "1. Template & Mapping".'}
          </p>
        </>
      }
    >
      <div className="mb-6 flex gap-1 border-b border-slate-200">
        {(
          [
            ['quickscreen', '0. Quick Screen'],
            ['documents', '1. Documents'],
            ['setup', '2. Template & Mapping'],
            ['dashboard', '3. Deal Inputs'],
            ['sensitivity', '4. Sensitivity'],
            ['scenarios', '5. Scenarios'],
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
      <div style={{ display: tab === 'quickscreen' ? 'block' : 'none' }}>
        <QuickScreen
          inputs={quickScreenInputs}
          onInputsChange={setQuickScreenInputs}
          results={quickScreenResults}
          onSendToDealInputs={handleSendQuickScreenToDealInputs}
        />
      </div>

      <div style={{ display: tab === 'documents' ? 'block' : 'none' }}>
        <Documents
          schema={schema}
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
          }}
        />
      </div>

      <div style={{ display: tab === 'dashboard' ? 'block' : 'none' }}>
        <DealInputForm schema={schema} values={formValues} onFieldChange={handleFieldChange} />
        <GeneratePanel
          template={activeTemplate}
          mappingProfileId={activeMappingProfileId}
          values={formValues}
          onGenerated={setComputedOutputs}
        />
      </div>

      <div style={{ display: tab === 'sensitivity' ? 'block' : 'none' }}>
        <SensitivityPanel
          schema={schema}
          template={activeTemplate}
          mappingProfileId={activeMappingProfileId}
          baseValues={formValues}
        />
      </div>

      <div style={{ display: tab === 'scenarios' ? 'block' : 'none' }}>
        <ScenariosPanel
          schema={schema}
          template={activeTemplate}
          mappingProfileId={activeMappingProfileId}
          values={formValues}
          active={tab === 'scenarios'}
          onLoadScenario={(inputs) => {
            setFormValues(inputs)
            setTab('dashboard')
          }}
          onLoadQuickScreenScenario={handleLoadQuickScreenScenario}
        />
      </div>
    </Layout>
  )
}

export default App
