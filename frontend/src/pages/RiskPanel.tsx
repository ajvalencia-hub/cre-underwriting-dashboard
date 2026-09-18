import { useEffect, useRef, useState } from 'react'
import {
  fetchGoalSeekInputs,
  fetchScenarios,
  pollMonteCarlo,
  saveScenarioMonteCarlo,
  startMonteCarlo,
  type McDriver,
  type MonteCarloResult,
} from '../lib/api'
import { visibleFields } from '../lib/schemaFields'
import type { InputSchema } from '../types/schema'
import type { Scenario } from '../types/scenario'

interface RiskPanelProps {
  schema: InputSchema
  values: Record<string, unknown>
  dealId: string | null
}

// Seed suggestions mirror the tornado's driver set, expressed as concrete
// numeric fields per dealflow (the tornado's composite "rent" driver has no
// single path). Acquisitions sample purchase price; developments sample the
// construction budget instead — the field the engine actually reads.
const SUGGESTED_PATHS_BY_TYPE: Record<string, string[]> = {
  acquisition: ['grossPotentialRent', 'exitCapRatePct', 'purchasePrice', 'interestRate', 'vacancyPct'],
  development: ['grossPotentialRent', 'exitCapRatePct', 'hardCosts', 'interestRate', 'vacancyPct'],
}

function defaultDriver(path: string, values: Record<string, unknown>): McDriver {
  const current = typeof values[path] === 'number' ? (values[path] as number) : 0
  if (path === 'exitCapRatePct' || path === 'interestRate') {
    // Rates: ±50bps triangular around today's value.
    const mode = current || 0.06
    return {
      inputPath: path,
      distribution: 'triangular',
      params: { min: mode - 0.005, mode, max: mode + 0.005 },
    }
  }
  const mode = current || 1
  return {
    inputPath: path,
    distribution: 'triangular',
    params: { min: mode * 0.9, mode, max: mode * 1.1 },
  }
}

const fmtPct = (v: number) => `${(v * 100).toFixed(2)}%`
const fmtX = (v: number) => `${v.toFixed(2)}x`
const fmtMoney = (v: number) => `$${Math.round(v).toLocaleString()}`

function Histogram({ bins }: { bins: { lo: number; hi: number; count: number }[] }) {
  const max = Math.max(...bins.map((b) => b.count), 1)
  const w = 460
  const h = 120
  const bw = w / bins.length
  return (
    <svg width={w} height={h + 16} className="mt-2">
      {bins.map((b, i) => {
        const bh = (b.count / max) * h
        return (
          <rect
            key={i}
            x={i * bw + 1}
            y={h - bh}
            width={bw - 2}
            height={bh}
            fill="#0284c7"
            opacity={0.8}
          >
            <title>
              {fmtPct(b.lo)} – {fmtPct(b.hi)}: {b.count}
            </title>
          </rect>
        )
      })}
      <text x={0} y={h + 12} className="fill-slate-400 text-[10px]">
        {fmtPct(bins[0].lo)}
      </text>
      <text x={w} y={h + 12} textAnchor="end" className="fill-slate-400 text-[10px]">
        {fmtPct(bins[bins.length - 1].hi)}
      </text>
    </svg>
  )
}

/** J8: Monte Carlo risk panel — seeded, deterministic, saved to scenarios. */
export default function RiskPanel({ schema, values, dealId }: RiskPanelProps) {
  const [inputList, setInputList] = useState<{ id: string; label: string; type?: string }[]>([])
  // Type-aware: suggestions per dealflow, picker limited to fields the
  // engine actually reads for this deal.
  const dealType = values.dealType === 'development' ? 'development' : 'acquisition'
  const suggested = SUGGESTED_PATHS_BY_TYPE[dealType]
  const visibleIds = new Set(visibleFields(schema, values).map((f) => f.id))
  const applicableInputs = inputList.filter((f) => visibleIds.has(f.id))
  const [drivers, setDrivers] = useState<McDriver[]>([])
  const [n, setN] = useState(500)
  const [seed, setSeed] = useState('')
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState<MonteCarloResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [dealScenarios, setDealScenarios] = useState<Scenario[]>([])
  const [saveTargetId, setSaveTargetId] = useState('')
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const pollTimer = useRef<number | null>(null)

  useEffect(() => {
    fetchGoalSeekInputs().then(setInputList).catch(() => setInputList([]))
    return () => {
      if (pollTimer.current !== null) window.clearInterval(pollTimer.current)
    }
  }, [])

  useEffect(() => {
    if (!dealId) {
      setDealScenarios([])
      return
    }
    fetchScenarios({ dealId, kind: 'full' })
      .then(setDealScenarios)
      .catch(() => setDealScenarios([]))
  }, [dealId])

  function addDriver(path: string) {
    if (drivers.some((d) => d.inputPath === path) || drivers.length >= 6) return
    setDrivers([...drivers, defaultDriver(path, values)])
  }

  function updateDriver(i: number, next: McDriver) {
    setDrivers(drivers.map((d, idx) => (idx === i ? next : d)))
  }

  async function handleRun() {
    const incomplete = drivers.find((d) => paramFields[d.distribution].some((p) => !Number.isFinite(d.params[p])))
    if (incomplete) {
      setError(
        `Fill in every parameter for ${inputList.find((f) => f.id === incomplete.inputPath)?.label ?? incomplete.inputPath} — an empty box is not treated as 0.`,
      )
      return
    }
    setRunning(true)
    setError(null)
    setResult(null)
    setSaveMessage(null)
    setProgress(0)
    try {
      const { jobId } = await startMonteCarlo({
        values,
        drivers,
        n,
        seed: seed.trim() ? Number(seed) : undefined,
      })
      pollTimer.current = window.setInterval(() => {
        void (async () => {
          try {
            const status = await pollMonteCarlo(jobId)
            setProgress(status.completed)
            if (status.status !== 'running') {
              if (pollTimer.current !== null) window.clearInterval(pollTimer.current)
              pollTimer.current = null
              setRunning(false)
              if (status.status === 'done' && status.result) {
                setResult(status.result)
                setSeed(String(status.result.seed))
              } else {
                setError(status.error ?? 'The run failed.')
              }
            }
          } catch {
            if (pollTimer.current !== null) window.clearInterval(pollTimer.current)
            pollTimer.current = null
            setRunning(false)
            setError('Lost contact with the run.')
          }
        })()
      }, 400)
    } catch (e) {
      setRunning(false)
      setError(e instanceof Error ? e.message : 'Could not start the run.')
    }
  }

  async function handleSaveToScenario() {
    if (!saveTargetId || !result) return
    try {
      await saveScenarioMonteCarlo(saveTargetId, result)
      setSaveMessage('Saved — the IC memo for that scenario now includes a risk section.')
    } catch {
      setSaveMessage('Save failed.')
    }
  }

  const paramFields: Record<string, string[]> = {
    normal: ['mean', 'stdDev'],
    triangular: ['min', 'mode', 'max'],
    uniform: ['min', 'max'],
  }

  return (
    <div className="max-w-4xl">
      <h2 className="text-sm font-semibold text-slate-700">Risk — Monte Carlo</h2>
      <p className="mt-1 text-xs text-slate-500">
        Up to 6 input drivers with distributions; seeded runs are exactly reproducible.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <span className="text-xs text-slate-500">Add driver:</span>
        {suggested.filter((p) => !drivers.some((d) => d.inputPath === p)).map((p) => (
          <button
            key={p}
            onClick={() => addDriver(p)}
            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-50"
          >
            + {inputList.find((f) => f.id === p)?.label ?? p}
          </button>
        ))}
        <select
          value=""
          onChange={(e) => e.target.value && addDriver(e.target.value)}
          className="rounded border border-slate-300 px-1 py-0.5 text-xs text-slate-500"
        >
          <option value="">other input…</option>
          {applicableInputs
            .filter((f) => !drivers.some((d) => d.inputPath === f.id))
            .map((f) => (
              <option key={f.id} value={f.id}>
                {f.label}
              </option>
            ))}
        </select>
      </div>

      {drivers.map((driver, i) => (
        <div key={driver.inputPath} className="mt-2 flex flex-wrap items-center gap-2 text-xs">
          <span className="w-48 truncate font-medium text-slate-600">
            {inputList.find((f) => f.id === driver.inputPath)?.label ?? driver.inputPath}
          </span>
          <select
            value={driver.distribution}
            onChange={(e) => {
              const dist = e.target.value as McDriver['distribution']
              const current = typeof values[driver.inputPath] === 'number'
                ? (values[driver.inputPath] as number) : 1
              const params: Record<string, number> =
                dist === 'normal'
                  ? { mean: current, stdDev: Math.abs(current) * 0.1 || 0.01 }
                  : dist === 'uniform'
                    ? { min: current * 0.9, max: current * 1.1 }
                    : { min: current * 0.9, mode: current, max: current * 1.1 }
              updateDriver(i, { ...driver, distribution: dist, params })
            }}
            className="rounded border border-slate-300 px-1 py-0.5"
          >
            <option value="normal">normal</option>
            <option value="triangular">triangular</option>
            <option value="uniform">uniform</option>
          </select>
          {paramFields[driver.distribution].map((p) => {
            // Percent inputs are entered as whole percents (6.5 = 6.5%), like
            // everywhere else in the app; the engine still receives fractions.
            const isPct = inputList.find((f) => f.id === driver.inputPath)?.type === 'percent'
            const shown = driver.params[p]
            return (
              <label key={p} className="flex items-center gap-1 text-slate-500">
                {p}
                <input
                  type="number"
                  step="any"
                  value={shown === undefined ? '' : isPct ? +(shown * 100).toFixed(6) : shown}
                  onChange={(e) =>
                    updateDriver(i, {
                      ...driver,
                      params: {
                        ...driver.params,
                        [p]: e.target.value === '' ? Number.NaN : Number(e.target.value) / (isPct ? 100 : 1),
                      },
                    })
                  }
                  className="w-24 rounded border border-slate-300 px-1 py-0.5 text-right"
                />
                {isPct && <span>%</span>}
              </label>
            )
          })}
          <button
            onClick={() => setDrivers(drivers.filter((_, idx) => idx !== i))}
            className="text-slate-400 hover:text-red-500"
          >
            remove
          </button>
        </div>
      ))}

      <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
        <label className="flex items-center gap-1 text-slate-500">
          Trials
          <input
            type="number"
            min={1}
            max={2000}
            value={n}
            onChange={(e) => setN(Math.min(2000, Math.max(1, Number(e.target.value) || 1)))}
            className="w-20 rounded border border-slate-300 px-1 py-0.5"
          />
        </label>
        <label className="flex items-center gap-1 text-slate-500">
          Seed (blank = random)
          <input
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            className="w-28 rounded border border-slate-300 px-1 py-0.5"
          />
        </label>
        <button
          onClick={() => void handleRun()}
          disabled={running || drivers.length === 0}
          className="rounded bg-sky-600 px-3 py-1.5 text-white hover:bg-sky-700 disabled:opacity-40"
        >
          {running ? `Running… ${progress}/${n}` : 'Run simulation'}
        </button>
        {error && <span className="text-red-600">{error}</span>}
      </div>

      {result && (
        <div className="mt-4">
          <div className="text-xs text-slate-500">
            {result.successfulRuns.toLocaleString()} trials (seed {result.seed}
            {result.failedRuns > 0 ? `, ${result.failedRuns} failed` : ''}) —{' '}
            P(IRR &lt; 0) = {fmtPct(result.probIrrNegative)}, P(IRR &lt;{' '}
            {fmtPct(result.hurdleIrr)}) = {fmtPct(result.probIrrBelowHurdle)}
          </div>
          <table className="mt-2 text-xs">
            <thead>
              <tr className="text-left text-slate-400">
                <th className="pr-3 font-medium">Metric</th>
                {['P5', 'P25', 'P50', 'P75', 'P95', 'Mean'].map((h) => (
                  <th key={h} className="pr-3 font-medium">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="text-slate-600">
              {(
                [
                  ['Levered IRR', result.leveredIrr, fmtPct],
                  ['Equity multiple', result.equityMultiple, fmtX],
                  ['Peak negative CF (post-close)', result.peakNegativeCashFlow, fmtMoney],
                ] as const
              ).map(([label, stats, fmt]) => (
                <tr key={label}>
                  <td className="pr-3">{label}</td>
                  {([stats.p5, stats.p25, stats.p50, stats.p75, stats.p95, stats.mean]).map(
                    (v, idx) => (
                      <td key={idx} className="pr-3">
                        {fmt(v)}
                      </td>
                    ),
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          {result.histogram.leveredIrr && <Histogram bins={result.histogram.leveredIrr} />}

          {dealScenarios.length > 0 && (
            <div className="mt-3 flex items-center gap-2 text-xs">
              <span className="font-medium text-slate-500">SAVE RUN TO SCENARIO</span>
              <select
                value={saveTargetId}
                onChange={(e) => setSaveTargetId(e.target.value)}
                className="rounded border border-slate-300 px-1 py-0.5"
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
                className="rounded border border-slate-400 px-2 py-0.5 text-slate-600 hover:bg-slate-50 disabled:opacity-40"
              >
                Save
              </button>
              {saveMessage && <span className="text-slate-400">{saveMessage}</span>}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
