import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  deleteScenario,
  fetchScenarios,
  fetchTornado,
  generateMemo,
  saveScenario,
  updateScenario,
  type TornadoResponse,
} from '../lib/api'
import { formatOutputValue, formatValue } from '../lib/formatValue'
import { flattenFields } from '../lib/schemaFields'
import {
  bestValueIndex,
  buildComparisonRows,
  tornadoGeometry,
} from '../lib/scenarioComparison'
import type { QuickScreenInputs } from '../lib/quickScreenMath'
import type { InputSchema } from '../types/schema'
import type { Scenario } from '../types/scenario'
import type { TemplateSummary } from '../types/template'

interface ScenariosPanelProps {
  schema: InputSchema
  template: TemplateSummary | null
  mappingProfileId: string | null
  values: Record<string, unknown>
  active: boolean
  dealId: string | null
  /** Latest computed metrics (native/server) — snapshotted into the scenario
   *  on save so the IC memo has a stored fallback. */
  computedOutputs?: Record<string, unknown>
  computedDebt?: Record<string, unknown> | null
  onLoadScenario: (inputs: Record<string, unknown>) => void
  onLoadQuickScreenScenario: (inputs: QuickScreenInputs) => void
}

const MAX_COMPARE = 4

export default function ScenariosPanel({
  schema,
  template,
  mappingProfileId,
  values,
  active,
  dealId,
  computedOutputs,
  computedDebt,
  onLoadScenario,
  onLoadQuickScreenScenario,
}: ScenariosPanelProps) {
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [scenarioName, setScenarioName] = useState('Base Case')
  const [saving, setSaving] = useState(false)
  const [compareIds, setCompareIds] = useState<string[]>([])

  const [quickScreenScenarios, setQuickScreenScenarios] = useState<Scenario[]>([])
  const [quickScreenLoading, setQuickScreenLoading] = useState(false)

  const fields = flattenFields(schema)
  const fieldById = new Map(fields.map((f) => [f.id, f]))

  // All tabs stay mounted (see App.tsx), so re-fetch whenever this tab becomes
  // active rather than only once on mount — otherwise a scenario saved from the
  // Quick Screen tab would never show up here without a full page reload.
  useEffect(() => {
    if (!active) return
    if (!template || !dealId) {
      setScenarios([])
      return
    }
    setLoading(true)
    fetchScenarios({ templateId: template.id, kind: 'full', dealId })
      .then(setScenarios)
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load scenarios'))
      .finally(() => setLoading(false))
  }, [template, active, dealId])

  useEffect(() => {
    if (!active || !dealId) return
    setQuickScreenLoading(true)
    fetchScenarios({ kind: 'quickscreen', dealId })
      .then(setQuickScreenScenarios)
      .catch((err) => setError(err instanceof Error ? err.message : 'Could not load Quick Screen scenarios'))
      .finally(() => setQuickScreenLoading(false))
  }, [active, dealId])

  async function handleSave() {
    if (!template || !mappingProfileId) return
    setSaving(true)
    setError(null)
    try {
      const outputsSnapshot =
        computedOutputs && Object.keys(computedOutputs).length > 0
          ? { metrics: computedOutputs, ...(computedDebt ? { debt: computedDebt } : {}) }
          : undefined
      const existing = scenarios.find((s) => s.scenarioName === scenarioName)
      const saved = existing
        ? await updateScenario(existing.id, {
            scenarioName,
            dealId,
            templateId: template.id,
            mappingProfileId,
            inputs: values,
            outputs: outputsSnapshot,
          })
        : await saveScenario({
            scenarioName,
            kind: 'full',
            dealId,
            templateId: template.id,
            mappingProfileId,
            inputs: values,
            outputs: outputsSnapshot,
          })
      setScenarios((prev) => [saved, ...prev.filter((s) => s.id !== saved.id)])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save scenario')
    } finally {
      setSaving(false)
    }
  }

  const [memoBusyId, setMemoBusyId] = useState<string | null>(null)

  async function handleGenerateMemo(scenarioId: string, format: 'docx' | 'pdf' = 'docx') {
    setMemoBusyId(scenarioId)
    setError(null)
    try {
      const { blob, filename } = await generateMemo(scenarioId, format)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not generate the IC memo')
    } finally {
      setMemoBusyId(null)
    }
  }

  async function handleDelete(id: string) {
    try {
      await deleteScenario(id)
      setScenarios((prev) => prev.filter((s) => s.id !== id))
      setQuickScreenScenarios((prev) => prev.filter((s) => s.id !== id))
      setCompareIds((prev) => prev.filter((cid) => cid !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete scenario')
    }
  }

  function toggleCompare(id: string) {
    setCompareIds((prev) => {
      if (prev.includes(id)) return prev.filter((cid) => cid !== id)
      if (prev.length >= MAX_COMPARE) return prev
      return [...prev, id]
    })
  }

  const compared = scenarios.filter((s) => compareIds.includes(s.id))
  const [showIdentical, setShowIdentical] = useState(false)
  const comparisonRows = useMemo(
    () => (compared.length >= 2 ? buildComparisonRows(schema, compared) : []),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [schema, compareIds.join(','), scenarios],
  )

  // ---- tornado ----
  const [tornadoScenarioId, setTornadoScenarioId] = useState('')
  const [tornadoMetric, setTornadoMetric] = useState('leveredIrr')
  const [tornado, setTornado] = useState<TornadoResponse | null>(null)
  const [tornadoBusy, setTornadoBusy] = useState(false)
  const [tornadoError, setTornadoError] = useState<string | null>(null)

  async function handleRunTornado() {
    const scenario = scenarios.find((s) => s.id === tornadoScenarioId)
    if (!scenario) return
    setTornadoBusy(true)
    setTornadoError(null)
    setTornado(null)
    try {
      setTornado(await fetchTornado(scenario.inputs, tornadoMetric))
    } catch (err) {
      setTornadoError(err instanceof Error ? err.message : 'Tornado analysis failed')
    } finally {
      setTornadoBusy(false)
    }
  }

  function TornadoChart({
    tornado,
    format,
  }: {
    tornado: TornadoResponse
    format: (v: number) => string
  }) {
    const width = 640
    const rowHeight = 28
    const labelWidth = 190
    const chartWidth = width - labelWidth - 70
    const bars = tornadoGeometry(tornado.bars, tornado.base, format)
    const height = bars.length * rowHeight + 24
    return (
      <div className="mt-3 overflow-x-auto rounded border border-slate-200 bg-white p-3">
        <div className="mb-1 text-xs text-slate-500">
          Base {format(tornado.base)} — bar ends show the metric at the down/up perturbation.
        </div>
        <svg width={width} height={height} role="img" aria-label="Tornado chart">
          {/* base line */}
          <line
            x1={labelWidth + chartWidth / 2}
            y1={4}
            x2={labelWidth + chartWidth / 2}
            y2={height - 20}
            stroke="#cbd5e1"
            strokeDasharray="3 3"
          />
          {bars.map((bar, i) => {
            const y = i * rowHeight + 8
            const x0 = labelWidth + bar.x0 * chartWidth
            const x1 = labelWidth + bar.x1 * chartWidth
            return (
              <g key={bar.key}>
                <text x={0} y={y + 13} fontSize={11} fill="#475569">
                  {bar.label}
                </text>
                <rect
                  x={Math.min(x0, x1)}
                  y={y}
                  width={Math.max(2, Math.abs(x1 - x0))}
                  height={16}
                  rx={2}
                  fill="#7dd3fc"
                  stroke="#0284c7"
                  strokeWidth={0.5}
                />
                {(() => {
                  const lowPx = labelWidth + bar.lowX * chartWidth
                  const highPx = labelWidth + bar.highX * chartWidth
                  const lowOnLeft = lowPx <= highPx
                  return (
                    <>
                      <text
                        x={lowOnLeft ? Math.min(x0, x1) - 4 : Math.max(x0, x1) + 4}
                        y={y + 12}
                        fontSize={9}
                        fill="#94a3b8"
                        textAnchor={lowOnLeft ? 'end' : 'start'}
                      >
                        ↓ {bar.lowLabel}
                      </text>
                      <text
                        x={lowOnLeft ? Math.max(x0, x1) + 4 : Math.min(x0, x1) - 4}
                        y={y + 12}
                        fontSize={9}
                        fill="#94a3b8"
                        textAnchor={lowOnLeft ? 'start' : 'end'}
                      >
                        ↑ {bar.highLabel}
                      </text>
                    </>
                  )
                })()}
              </g>
            )
          })}
        </svg>
      </div>
    )
  }

  return (
    <div className="max-w-4xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Scenarios</h1>
        <p className="mt-1 text-slate-500">
          Save the current deal inputs as a named scenario, reload one later, or compare a few
          side by side.
        </p>
      </div>

      {error && <div className="text-sm text-red-600">{error}</div>}

      <section>
        <h2 className="text-sm font-semibold tracking-wide text-slate-500">
          QUICK SCREEN SCENARIOS ({quickScreenScenarios.length})
        </h2>
        {quickScreenLoading && <div className="mt-2 text-sm text-slate-400">Loading…</div>}
        {!quickScreenLoading && quickScreenScenarios.length === 0 && (
          <div className="mt-2 text-sm text-slate-400">
            No Quick Screen scenarios saved yet — use "Save as Scenario" on the Quick Screen tab.
          </div>
        )}
        <ul className="mt-2 divide-y divide-slate-100 rounded border border-slate-200 bg-white">
          {quickScreenScenarios.map((s) => (
            <li key={s.id} className="flex items-center justify-between px-3 py-2 text-sm">
              <div className="flex items-center gap-2">
                <span className="font-medium">{s.scenarioName}</span>
                <span className="text-xs text-slate-400">{new Date(s.updatedAt).toLocaleString()}</span>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => onLoadQuickScreenScenario(s.inputs as unknown as QuickScreenInputs)}
                  className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50"
                >
                  Load in Quick Screen
                </button>
                <button
                  onClick={() => handleDelete(s.id)}
                  className="rounded border border-slate-300 px-2 py-0.5 text-xs text-red-500 hover:bg-red-50"
                >
                  Delete
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      {!template ? (
        <div className="text-sm text-slate-500">
          Upload a template under "1. Template &amp; Mapping" to save and compare full Deal Inputs
          scenarios.
        </div>
      ) : (
        <>
          <div className="flex items-center gap-2">
            <input
              value={scenarioName}
              onChange={(e) => setScenarioName(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1 text-sm"
              placeholder="Scenario name"
            />
            <button
              onClick={handleSave}
              disabled={saving || !mappingProfileId || !scenarioName.trim()}
              className="rounded bg-emerald-600 px-3 py-1 text-sm text-white hover:bg-emerald-700 disabled:opacity-40"
            >
              {saving ? 'Saving…' : 'Save current inputs as scenario'}
            </button>
            {!mappingProfileId && (
              <span className="text-xs text-slate-400">
                Save a mapping profile first to enable scenarios.
              </span>
            )}
          </div>

          <section>
            <h2 className="text-sm font-semibold tracking-wide text-slate-500">
              SAVED SCENARIOS ({scenarios.length})
            </h2>
            {loading && <div className="mt-2 text-sm text-slate-400">Loading…</div>}
            {!loading && scenarios.length === 0 && (
              <div className="mt-2 text-sm text-slate-400">No scenarios saved yet.</div>
            )}
            <ul className="mt-2 divide-y divide-slate-100 rounded border border-slate-200 bg-white">
              {scenarios.map((s) => (
                <li key={s.id} className="flex items-center justify-between px-3 py-2 text-sm">
                  <label className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={compareIds.includes(s.id)}
                      onChange={() => toggleCompare(s.id)}
                      disabled={!compareIds.includes(s.id) && compareIds.length >= MAX_COMPARE}
                    />
                    <span className="font-medium">{s.scenarioName}</span>
                    <span className="text-xs text-slate-400">
                      {new Date(s.updatedAt).toLocaleString()}
                    </span>
                  </label>
                  <div className="flex gap-2">
                    <button
                      onClick={() => onLoadScenario(s.inputs)}
                      className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50"
                    >
                      Load
                    </button>
                    <button
                      onClick={() => handleGenerateMemo(s.id)}
                      disabled={memoBusyId === s.id}
                      title="Renders a .docx IC memo from this scenario's inputs and computed outputs."
                      className="rounded border border-sky-300 px-2 py-0.5 text-xs text-sky-700 hover:bg-sky-50 disabled:opacity-40"
                    >
                      {memoBusyId === s.id ? 'Generating…' : 'Generate IC Memo'}
                    </button>
                    <button
                      onClick={() => handleGenerateMemo(s.id, 'pdf')}
                      disabled={memoBusyId === s.id}
                      title="PDF variant — converted server-side via LibreOffice."
                      className="rounded border border-sky-300 px-2 py-0.5 text-xs text-sky-700 hover:bg-sky-50 disabled:opacity-40"
                    >
                      PDF
                    </button>
                    <button
                      onClick={() => handleDelete(s.id)}
                      className="rounded border border-slate-300 px-2 py-0.5 text-xs text-red-500 hover:bg-red-50"
                    >
                      Delete
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          </section>

          {compared.length >= 2 && (
            <section>
              <h2 className="text-sm font-semibold tracking-wide text-slate-500">
                COMPARISON ({compared.length} of {MAX_COMPARE})
              </h2>
              <label className="mt-1 flex items-center gap-1 text-xs text-slate-400">
                <input
                  type="checkbox"
                  checked={showIdentical}
                  onChange={(e) => setShowIdentical(e.target.checked)}
                />
                Show identical inputs
              </label>

              <div className="mt-2 overflow-x-auto rounded border border-slate-200 bg-white">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left">
                      <th className="px-3 py-2 font-medium text-slate-500">Input</th>
                      {compared.map((s) => (
                        <th key={s.id} className="px-3 py-2 font-medium text-slate-700">
                          {s.scenarioName}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {(() => {
                      const visible = comparisonRows.filter((r) => r.differs || showIdentical)
                      if (visible.length === 0) {
                        return (
                          <tr>
                            <td colSpan={compared.length + 1} className="px-3 py-2 text-slate-400">
                              No differing inputs — these scenarios share every value.
                            </td>
                          </tr>
                        )
                      }
                      const output: ReactNode[] = []
                      let lastSection = ''
                      for (const row of visible) {
                        if (row.sectionLabel !== lastSection) {
                          lastSection = row.sectionLabel
                          output.push(
                            <tr key={`sec-${row.sectionLabel}`} className="bg-slate-50">
                              <td
                                colSpan={compared.length + 1}
                                className="px-3 py-1 text-[10px] font-semibold tracking-wide text-slate-400"
                              >
                                {row.sectionLabel.toUpperCase()}
                              </td>
                            </tr>,
                          )
                        }
                        output.push(
                          <tr
                            key={row.fieldId}
                            className={`border-b border-slate-50 ${row.differs ? '' : 'text-slate-400'}`}
                          >
                            <td className="px-3 py-1.5 text-slate-500">{row.label}</td>
                            {row.values.map((value, i) => (
                              <td key={i} className={`px-3 py-1.5 ${row.differs ? 'font-medium' : ''}`}>
                                {formatValue(fieldById.get(row.fieldId), value)}
                              </td>
                            ))}
                          </tr>,
                        )
                      }
                      return output
                    })()}
                  </tbody>
                </table>
              </div>

              <h3 className="mt-4 text-xs font-semibold tracking-wide text-slate-500">
                OUTPUTS — best value highlighted where direction is unambiguous
              </h3>
              <div className="mt-1 overflow-x-auto rounded border border-slate-200 bg-white">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 text-left">
                      <th className="px-3 py-2 font-medium text-slate-500">Metric</th>
                      {compared.map((s) => (
                        <th key={s.id} className="px-3 py-2 font-medium text-slate-700">
                          {s.scenarioName}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {schema.outputs.map((metric) => {
                      const values = compared.map((s) => {
                        const metrics = (s.outputs as { metrics?: Record<string, unknown> })?.metrics
                        const v = metrics?.[metric.id]
                        return typeof v === 'number' ? v : null
                      })
                      if (values.every((v) => v === null)) return null
                      const best = bestValueIndex(metric.id, values)
                      return (
                        <tr key={metric.id} className="border-b border-slate-50">
                          <td className="px-3 py-1.5 text-slate-500">{metric.label}</td>
                          {values.map((v, i) => (
                            <td
                              key={i}
                              className={`px-3 py-1.5 tabular-nums ${
                                best === i ? 'bg-emerald-50 font-semibold text-emerald-700' : ''
                              }`}
                            >
                              {v === null ? '—' : formatOutputValue(metric, v)}
                            </td>
                          ))}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <p className="mt-1 text-[11px] text-slate-400">
                Outputs come from each scenario's saved compute snapshot — re-save a scenario after
                computing to refresh them.
              </p>
            </section>
          )}

          <section>
            <h2 className="text-sm font-semibold tracking-wide text-slate-500">TORNADO</h2>
            <p className="mt-1 text-xs text-slate-400">
              One-driver-at-a-time perturbation of a scenario (±10%; rate/cap ±50 bps) through the
              native engine, sorted by impact on the chosen metric.
            </p>
            <div className="mt-2 flex items-center gap-2 text-sm">
              <select
                value={tornadoScenarioId}
                onChange={(e) => setTornadoScenarioId(e.target.value)}
                className="rounded border border-slate-300 px-2 py-1 text-sm"
              >
                <option value="">Select scenario…</option>
                {scenarios.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.scenarioName}
                  </option>
                ))}
              </select>
              <select
                value={tornadoMetric}
                onChange={(e) => setTornadoMetric(e.target.value)}
                className="rounded border border-slate-300 px-2 py-1 text-sm"
              >
                {schema.outputs.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label}
                  </option>
                ))}
              </select>
              <button
                onClick={() => void handleRunTornado()}
                disabled={!tornadoScenarioId || tornadoBusy}
                className="rounded bg-slate-900 px-3 py-1 text-sm text-white hover:bg-slate-700 disabled:opacity-40"
              >
                {tornadoBusy ? 'Running…' : 'Run tornado'}
              </button>
            </div>
            {tornadoError && <div className="mt-2 text-sm text-red-600">{tornadoError}</div>}
            {tornado && (
              <TornadoChart
                tornado={tornado}
                format={(v) =>
                  formatOutputValue(schema.outputs.find((m) => m.id === tornado.metric)!, v)
                }
              />
            )}
          </section>
        </>
      )}
    </div>
  )
}
