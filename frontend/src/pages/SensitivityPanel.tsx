import { useEffect, useState } from 'react'
import {
  fetchMappingProfile,
  fetchScenarios,
  runSensitivity,
  saveScenarioSensitivity,
  type SavedSensitivity,
} from '../lib/api'
import { formatOutputValue } from '../lib/formatValue'
import { flattenFields, type FlatField } from '../lib/schemaFields'
import { boundsReady, heatColor, linspace } from '../lib/sensitivityMath'
import type { OutputMetric, InputSchema } from '../types/schema'
import type { Scenario } from '../types/scenario'
import type { SensitivityPoint } from '../types/sensitivity'
import type { TemplateSummary } from '../types/template'

interface SensitivityPanelProps {
  schema: InputSchema
  template: TemplateSummary | null
  mappingProfileId: string | null
  baseValues: Record<string, unknown>
  dealId: string | null
}

type SweepMode = 'native' | 'template'

const MAX_POINTS: Record<SweepMode, number> = { native: 625, template: 30 }
const MAX_STEPS: Record<SweepMode, number> = { native: 25, template: 10 }

const DRIVER_TYPES = new Set(['number', 'percent', 'currency'])

interface DriverConfig {
  fieldId: string
  min: string
  max: string
  steps: string
}

function toRawValue(field: FlatField | undefined, display: number): number {
  return field?.type === 'percent' ? display / 100 : display
}

function formatDriverValue(field: FlatField | undefined, raw: number): string {
  if (field?.type === 'percent') return `${(raw * 100).toFixed(2)}%`
  if (field?.type === 'currency') return `$${raw.toLocaleString()}`
  return raw.toLocaleString()
}

export default function SensitivityPanel({
  schema,
  template,
  mappingProfileId,
  baseValues,
  dealId,
}: SensitivityPanelProps) {
  const fields = flattenFields(schema)
  const fieldById = new Map<string, FlatField>(fields.map((f) => [f.id, f]))
  const driverCandidates = fields.filter((f) => DRIVER_TYPES.has(f.type))

  const [mode, setMode] = useState<SweepMode>('native')
  const [mappedFieldIds, setMappedFieldIds] = useState<Set<string>>(new Set())
  const [driver1, setDriver1] = useState<DriverConfig>({ fieldId: '', min: '', max: '', steps: '5' })
  const [driver2, setDriver2] = useState<DriverConfig>({ fieldId: '', min: '', max: '', steps: '5' })
  const [selectedOutputs, setSelectedOutputs] = useState<Set<string>>(new Set())
  const [points, setPoints] = useState<SensitivityPoint[] | null>(null)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dealScenarios, setDealScenarios] = useState<Scenario[]>([])
  const [saveTargetId, setSaveTargetId] = useState('')
  const [saveMessage, setSaveMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!mappingProfileId) {
      setMappedFieldIds(new Set())
      return
    }
    fetchMappingProfile(mappingProfileId)
      .then((profile) => setMappedFieldIds(new Set(Object.keys(profile.mappings))))
      .catch(() => setMappedFieldIds(new Set()))
  }, [mappingProfileId])

  useEffect(() => {
    if (!dealId) {
      setDealScenarios([])
      return
    }
    fetchScenarios({ dealId, kind: 'full' })
      .then(setDealScenarios)
      .catch(() => setDealScenarios([]))
  }, [dealId, points])

  const templateAvailable = Boolean(template && mappingProfileId)
  // Native mode sweeps ANY numeric schema input and tracks ANY output metric;
  // template mode is limited to what the mapping profile carries.
  const eligibleDrivers =
    mode === 'native'
      ? driverCandidates
      : driverCandidates.filter((f) => mappedFieldIds.has(f.id))
  const eligibleOutputs =
    mode === 'native' ? schema.outputs : schema.outputs.filter((m) => mappedFieldIds.has(m.id))

  function toggleOutput(id: string) {
    setSelectedOutputs((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  async function handleRun() {
    if (mode === 'template' && (!template || !mappingProfileId)) return
    if (!driver1.fieldId) return
    // Guard against Number('') === 0: never sweep from a blank bound.
    if (!boundsReady(driver1) || (driver2.fieldId !== '' && !boundsReady(driver2))) return
    setRunning(true)
    setError(null)
    setPoints(null)
    setSaveMessage(null)
    try {
      const drivers = [
        {
          fieldId: driver1.fieldId,
          values: linspace(
            toRawValue(fieldById.get(driver1.fieldId), Number(driver1.min)),
            toRawValue(fieldById.get(driver1.fieldId), Number(driver1.max)),
            Number(driver1.steps),
          ),
        },
      ]
      if (driver2.fieldId) {
        drivers.push({
          fieldId: driver2.fieldId,
          values: linspace(
            toRawValue(fieldById.get(driver2.fieldId), Number(driver2.min)),
            toRawValue(fieldById.get(driver2.fieldId), Number(driver2.max)),
            Number(driver2.steps),
          ),
        })
      }
      const result = await runSensitivity({
        mode,
        templateId: mode === 'template' ? template?.id : undefined,
        mappingProfileId: mode === 'template' ? mappingProfileId : undefined,
        baseValues,
        drivers,
        outputFieldIds: Array.from(selectedOutputs),
      })
      setPoints(result.points)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sensitivity analysis failed')
    } finally {
      setRunning(false)
    }
  }

  const driver1Ready = driver1.fieldId !== '' && boundsReady(driver1)
  const driver2Ready = driver2.fieldId === '' || boundsReady(driver2)
  const driver1Values = driver1Ready
    ? linspace(Number(driver1.min), Number(driver1.max), Number(driver1.steps))
    : []
  const driver2Values = driver2.fieldId !== '' && boundsReady(driver2)
    ? linspace(Number(driver2.min), Number(driver2.max), Number(driver2.steps))
    : []
  const totalPoints = driver1Values.length * (driver2Values.length || 1)
  const boundsIncomplete =
    (driver1.fieldId !== '' && !boundsReady(driver1)) ||
    (driver2.fieldId !== '' && !boundsReady(driver2))

  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-semibold">Sensitivity Analysis</h1>
      <p className="mt-1 text-slate-500">
        {mode === 'native'
          ? 'Sweep any 1–2 numeric inputs through the built-in pro-forma engine — no template required, any output metric, grids up to 25×25.'
          : 'Each grid point is a real server-side recalculation of your mapped Excel template — slower, but verifies the native engine against your model.'}
      </p>

      <div className="mt-3 flex items-center gap-2 text-sm">
        <span className="text-xs font-medium text-slate-500">ENGINE</span>
        <button
          onClick={() => setMode('native')}
          className={`rounded border px-2 py-1 text-xs ${
            mode === 'native'
              ? 'border-slate-900 bg-slate-900 text-white'
              : 'border-slate-300 text-slate-600 hover:bg-slate-50'
          }`}
        >
          Native engine
        </button>
        <button
          onClick={() => templateAvailable && setMode('template')}
          disabled={!templateAvailable}
          title={
            templateAvailable
              ? 'Run each grid point through the mapped Excel template via LibreOffice'
              : 'Upload a template and save a mapping profile first'
          }
          className={`rounded border px-2 py-1 text-xs disabled:opacity-40 ${
            mode === 'template'
              ? 'border-slate-900 bg-slate-900 text-white'
              : 'border-slate-300 text-slate-600 hover:bg-slate-50'
          }`}
        >
          Verify via Excel template
        </button>
      </div>

      {mode === 'template' && eligibleDrivers.length === 0 && (
        <div className="mt-4 rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
          No numeric/percent/currency fields are mapped in the active mapping profile yet. Map at
          least one (e.g. exit cap rate, rent growth) under "2. Template &amp; Mapping" first.
        </div>
      )}

      <div className="mt-6 space-y-4 rounded-md border border-slate-200 bg-white p-4">
        <DriverRow
          label="Driver 1 (required)"
          config={driver1}
          onChange={setDriver1}
          options={eligibleDrivers}
          allowNone={false}
          maxSteps={MAX_STEPS[mode]}
        />
        <DriverRow
          label="Driver 2 (optional)"
          config={driver2}
          onChange={setDriver2}
          options={eligibleDrivers.filter((f) => f.id !== driver1.fieldId)}
          allowNone
          maxSteps={MAX_STEPS[mode]}
        />

        <div>
          <label className="block text-xs font-medium text-slate-600">Output metrics to track</label>
          {eligibleOutputs.length === 0 ? (
            <p className="mt-1 text-xs text-slate-400">
              No output metrics are mapped yet — map some under "Computed Outputs" in Template &amp;
              Mapping.
            </p>
          ) : (
            <div className="mt-1 flex flex-wrap gap-3">
              {eligibleOutputs.map((m) => (
                <label key={m.id} className="flex items-center gap-1 text-xs text-slate-600">
                  <input
                    type="checkbox"
                    checked={selectedOutputs.has(m.id)}
                    onChange={() => toggleOutput(m.id)}
                  />
                  {m.label}
                </label>
              ))}
            </div>
          )}
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleRun}
            disabled={
              running ||
              !driver1Ready ||
              !driver2Ready ||
              selectedOutputs.size === 0 ||
              totalPoints === 0 ||
              totalPoints > MAX_POINTS[mode]
            }
            className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700 disabled:opacity-40"
          >
            {running ? `Running ${totalPoints} points…` : `Run Sensitivity (${totalPoints} points)`}
          </button>
          {totalPoints > MAX_POINTS[mode] && (
            <span className="text-xs text-red-600">
              Max {MAX_POINTS[mode]} grid points in {mode} mode — reduce steps.
            </span>
          )}
          {boundsIncomplete && (
            <span className="text-xs text-slate-400">
              Enter a numeric min/max (and at least 2 steps) for each selected driver.
            </span>
          )}
        </div>
      </div>

      {error && (
        <div className="mt-4 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">{error}</div>
      )}

      {points && (
        <SensitivityResults
          points={points}
          driver1={driver1}
          driver2={driver2}
          driver1Values={driver1Values}
          driver2Values={driver2Values}
          fieldById={fieldById}
          outputs={schema.outputs.filter((m) => selectedOutputs.has(m.id))}
        />
      )}

      {points && dealScenarios.length > 0 && (
        <div className="mt-4 flex items-center gap-2 text-sm">
          <span className="text-xs font-medium text-slate-500">SAVE RUN TO SCENARIO</span>
          <select
            value={saveTargetId}
            onChange={(e) => setSaveTargetId(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1 text-sm"
          >
            <option value="">Select scenario…</option>
            {dealScenarios.map((s) => (
              <option key={s.id} value={s.id}>
                {s.scenarioName}
              </option>
            ))}
          </select>
          <button
            onClick={() => void handleSaveToScenario()}
            disabled={!saveTargetId}
            className="rounded border border-emerald-300 px-2 py-1 text-xs text-emerald-700 hover:bg-emerald-50 disabled:opacity-40"
          >
            Save
          </button>
          {saveMessage && <span className="text-xs text-slate-400">{saveMessage}</span>}
        </div>
      )}
    </div>
  )

  async function handleSaveToScenario() {
    if (!points || !saveTargetId) return
    try {
      const snapshot = buildSavedSensitivity(
        points,
        driver1,
        driver2,
        driver1Values,
        driver2Values,
        fieldById,
        schema.outputs.filter((m) => selectedOutputs.has(m.id)),
        mode,
      )
      await saveScenarioSensitivity(saveTargetId, snapshot)
      setSaveMessage('Saved — the IC memo for that scenario now includes this run.')
    } catch (err) {
      setSaveMessage(err instanceof Error ? err.message : 'Could not save the run')
    }
  }
}

/** Snapshot a run in the shape the memo's sensitivity section consumes
 *  ({description, header, rows}) plus the raw run for future tooling. */
function buildSavedSensitivity(
  points: SensitivityPoint[],
  driver1: DriverConfig,
  driver2: DriverConfig,
  driver1Values: number[],
  driver2Values: number[],
  fieldById: Map<string, FlatField>,
  outputs: OutputMetric[],
  mode: SweepMode,
): SavedSensitivity {
  const field1 = fieldById.get(driver1.fieldId)
  const field2 = fieldById.get(driver2.fieldId)
  const metric = outputs[0]
  const close = (a: number, b: number) => Math.abs(a - b) < 1e-9

  const findPoint = (v1: number, v2?: number) =>
    points.find((p) => {
      const match1 = close(p.driverValues[driver1.fieldId], toRawValue(field1, v1))
      if (v2 === undefined) return match1
      return match1 && close(p.driverValues[driver2.fieldId], toRawValue(field2, v2))
    })

  if (driver2.fieldId && field2 && metric) {
    const header = [
      `${field1?.label ?? driver1.fieldId} \\ ${field2.label}`,
      ...driver2Values.map((v2) => formatDriverValue(field2, toRawValue(field2, v2))),
    ]
    const rows = driver1Values.map((v1) => [
      formatDriverValue(field1, toRawValue(field1, v1)),
      ...driver2Values.map((v2) => {
        const point = findPoint(v1, v2)
        return point ? formatOutputValue(metric, point.outputs[metric.id]) : '—'
      }),
    ])
    return {
      description: `${metric.label} — ${field1?.label ?? driver1.fieldId} (rows) × ${field2.label} (cols), ${mode} engine`,
      header,
      rows,
      run: {
        mode,
        drivers: [
          { fieldId: driver1.fieldId, values: driver1Values.map((v) => toRawValue(field1, v)) },
          { fieldId: driver2.fieldId, values: driver2Values.map((v) => toRawValue(field2, v)) },
        ],
        outputFieldIds: outputs.map((m) => m.id),
        points,
      },
    }
  }

  const header = [field1?.label ?? driver1.fieldId, ...outputs.map((m) => m.label)]
  const rows = driver1Values.map((v1) => {
    const point = findPoint(v1)
    return [
      formatDriverValue(field1, toRawValue(field1, v1)),
      ...outputs.map((m) => (point ? formatOutputValue(m, point.outputs[m.id]) : '—')),
    ]
  })
  return {
    description: `${field1?.label ?? driver1.fieldId} sweep, ${mode} engine`,
    header,
    rows,
    run: {
      mode,
      drivers: [
        { fieldId: driver1.fieldId, values: driver1Values.map((v) => toRawValue(field1, v)) },
      ],
      outputFieldIds: outputs.map((m) => m.id),
      points,
    },
  }
}

function DriverRow({
  label,
  config,
  onChange,
  options,
  allowNone,
  maxSteps = 10,
}: {
  label: string
  config: DriverConfig
  onChange: (c: DriverConfig) => void
  options: FlatField[]
  allowNone: boolean
  maxSteps?: number
}) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-600">{label}</label>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <select
          value={config.fieldId}
          onChange={(e) => onChange({ ...config, fieldId: e.target.value })}
          className="rounded border border-slate-300 px-2 py-1 text-sm"
        >
          {allowNone && <option value="">None</option>}
          {!allowNone && <option value="" disabled>Select field…</option>}
          {options.map((f) => (
            <option key={f.id} value={f.id}>
              {f.label}
            </option>
          ))}
        </select>
        {config.fieldId && (
          <>
            <input
              type="number"
              placeholder="Min"
              value={config.min}
              onChange={(e) => onChange({ ...config, min: e.target.value })}
              className="w-24 rounded border border-slate-300 px-2 py-1 text-sm"
            />
            <span className="text-slate-400">to</span>
            <input
              type="number"
              placeholder="Max"
              value={config.max}
              onChange={(e) => onChange({ ...config, max: e.target.value })}
              className="w-24 rounded border border-slate-300 px-2 py-1 text-sm"
            />
            <span className="text-slate-400">in</span>
            <input
              type="number"
              min={2}
              max={maxSteps}
              value={config.steps}
              onChange={(e) => onChange({ ...config, steps: e.target.value })}
              className="w-16 rounded border border-slate-300 px-2 py-1 text-sm"
            />
            <span className="text-slate-400">steps</span>
          </>
        )}
      </div>
    </div>
  )
}

function SensitivityResults({
  points,
  driver1,
  driver2,
  driver1Values,
  driver2Values,
  fieldById,
  outputs,
}: {
  points: SensitivityPoint[]
  driver1: DriverConfig
  driver2: DriverConfig
  driver1Values: number[]
  driver2Values: number[]
  fieldById: Map<string, FlatField>
  outputs: OutputMetric[]
}) {
  const field1 = fieldById.get(driver1.fieldId)
  const field2 = fieldById.get(driver2.fieldId)

  function findPoint(v1: number, v2?: number): SensitivityPoint | undefined {
    return points.find((p) => {
      const raw1 = toRawValue(field1, v1)
      const closeEnough = (a: number, b: number) => Math.abs(a - b) < 1e-9
      const match1 = closeEnough(p.driverValues[driver1.fieldId], raw1)
      if (v2 === undefined) return match1
      const raw2 = toRawValue(field2, v2)
      return match1 && closeEnough(p.driverValues[driver2.fieldId], raw2)
    })
  }

  if (!driver2.fieldId) {
    return (
      <div className="mt-6 overflow-x-auto rounded-md border border-slate-200 bg-white p-4">
        <h2 className="mb-2 text-sm font-semibold tracking-wide text-slate-500">RESULTS</h2>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-slate-500">
              <th className="py-1.5 pr-4 font-medium">{field1?.label ?? driver1.fieldId}</th>
              {outputs.map((m) => (
                <th key={m.id} className="py-1.5 pr-4 font-medium">
                  {m.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {driver1Values.map((v1) => {
              const point = findPoint(v1)
              return (
                <tr key={v1} className="border-b border-slate-50">
                  <td className="py-1.5 pr-4 font-medium">{formatDriverValue(field1, toRawValue(field1, v1))}</td>
                  {outputs.map((m) => (
                    <td key={m.id} className="py-1.5 pr-4">
                      {point ? formatOutputValue(m, point.outputs[m.id]) : '—'}
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    )
  }

  return (
    <div className="mt-6 space-y-6">
      {outputs.map((m) => {
        const values = points.map((p) => Number(p.outputs[m.id])).filter((v) => Number.isFinite(v))
        const min = Math.min(...values)
        const max = Math.max(...values)
        return (
          <div key={m.id} className="overflow-x-auto rounded-md border border-slate-200 bg-white p-4">
            <h2 className="mb-2 text-sm font-semibold tracking-wide text-slate-500">
              {m.label.toUpperCase()} — {field1?.label} (rows) × {field2?.label} (cols)
            </h2>
            <table className="border-collapse text-sm">
              <thead>
                <tr>
                  <th className="border border-slate-200 px-2 py-1"></th>
                  {driver2Values.map((v2) => (
                    <th key={v2} className="border border-slate-200 px-2 py-1 font-medium">
                      {formatDriverValue(field2, toRawValue(field2, v2))}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {driver1Values.map((v1) => (
                  <tr key={v1}>
                    <td className="border border-slate-200 bg-slate-50 px-2 py-1 font-medium">
                      {formatDriverValue(field1, toRawValue(field1, v1))}
                    </td>
                    {driver2Values.map((v2) => {
                      const point = findPoint(v1, v2)
                      const rawValue = point ? Number(point.outputs[m.id]) : NaN
                      const t = Number.isFinite(rawValue) && max > min ? (rawValue - min) / (max - min) : 0.5
                      return (
                        <td
                          key={v2}
                          className="border border-slate-200 px-2 py-1 text-center"
                          style={{ backgroundColor: point ? heatColor(t) : undefined }}
                        >
                          {point ? formatOutputValue(m, point.outputs[m.id]) : '—'}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      })}
    </div>
  )
}
