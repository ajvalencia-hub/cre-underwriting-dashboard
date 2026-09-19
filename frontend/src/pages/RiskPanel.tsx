import { useEffect, useMemo, useRef, useState } from 'react'
import {
  cancelMonteCarlo,
  fetchGoalSeekInputs,
  fetchScenarios,
  pollMonteCarlo,
  saveScenarioMonteCarlo,
  startMonteCarlo,
  type McDriver,
  type MonteCarloResult,
} from '../lib/api'
import { friendlyEngineError } from '../lib/engineErrors'
import {
  MONTE_CARLO_POLL_INTERVAL_MS,
  pollTimedOut,
  pollTimeoutMessage,
} from '../lib/monteCarloPolling'
import { parseSeed } from '../lib/monteCarloSeed'
import { visibleFields } from '../lib/schemaFields'
import type { InputSchema } from '../types/schema'
import type { Scenario } from '../types/scenario'
import { formatMoney } from '../lib/money'
import { MonteCarloCharts } from '../components/analysisCharts/MonteCarloCharts'

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
const fmtMoney = (v: number) => formatMoney(v)

const PARAM_FIELDS: Record<string, string[]> = {
  normal: ['mean', 'stdDev'],
  triangular: ['min', 'mode', 'max'],
  uniform: ['min', 'max'],
}

/** J8: Monte Carlo risk panel — seeded, deterministic, saved to scenarios. */
export default function RiskPanel({ schema, values, dealId }: RiskPanelProps) {
  const [inputList, setInputList] = useState<{ id: string; label: string; type?: string }[]>([])
  // Type-aware: suggestions per dealflow, picker limited to fields the
  // engine actually reads for this deal.
  const dealType = values.dealType === 'development' ? 'development' : 'acquisition'
  const suggested = SUGGESTED_PATHS_BY_TYPE[dealType]
  // Perf (Run 6 wave 2): the visible-field walk reruns only when the schema
  // or values change, not on every keystroke inside this panel.
  const visibleIds = useMemo(
    () => new Set(visibleFields(schema, values).map((f) => f.id)),
    [schema, values],
  )
  const applicableInputs = useMemo(
    () => inputList.filter((f) => visibleIds.has(f.id)),
    [inputList, visibleIds],
  )
  const [drivers, setDrivers] = useState<McDriver[]>([])
  const [n, setN] = useState(500)
  const [seed, setSeed] = useState('')
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState(0)
  const [result, setResult] = useState<MonteCarloResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [dealScenarios, setDealScenarios] = useState<Scenario[]>([])
  const [saveTargetId, setSaveTargetId] = useState('')
  const [saveMessage, setSaveMessage] = useState<string | null>(null)
  const pollTimer = useRef<number | null>(null)
  const jobIdRef = useRef<string | null>(null)

  function stopPolling() {
    if (pollTimer.current !== null) window.clearInterval(pollTimer.current)
    pollTimer.current = null
    jobIdRef.current = null
  }

  useEffect(() => {
    fetchGoalSeekInputs().then(setInputList).catch(() => setInputList([]))
    return stopPolling
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

  // B18: validated seed — junk never silently becomes a random run.
  const seedParse = parseSeed(seed)

  async function handleRun() {
    if (!seedParse.ok) return
    const incomplete = drivers.find((d) => PARAM_FIELDS[d.distribution].some((p) => !Number.isFinite(d.params[p])))
    if (incomplete) {
      setError(
        `Fill in every parameter for ${inputList.find((f) => f.id === incomplete.inputPath)?.label ?? incomplete.inputPath} — an empty box is not treated as 0.`,
      )
      return
    }
    setRunning(true)
    setError(null)
    setNotice(null)
    setResult(null)
    setSaveMessage(null)
    setProgress(0)
    try {
      const { jobId } = await startMonteCarlo({
        values,
        drivers,
        n,
        seed: seedParse.seed,
      })
      jobIdRef.current = jobId
      const startedAt = Date.now()
      pollTimer.current = window.setInterval(() => {
        void (async () => {
          // Wave 2: a hard ceiling so a stuck job never spins the UI forever.
          if (pollTimedOut(startedAt, Date.now())) {
            stopPolling()
            setRunning(false)
            setError(pollTimeoutMessage())
            void cancelMonteCarlo(jobId)
            return
          }
          try {
            const status = await pollMonteCarlo(jobId)
            // A cancel/timeout landed while this poll was in flight — ignore it.
            if (jobIdRef.current !== jobId) return
            setProgress(status.completed)
            if (status.status !== 'running') {
              stopPolling()
              setRunning(false)
              if (status.status === 'done' && status.result) {
                setResult(status.result)
                setSeed(String(status.result.seed))
              } else if (status.status === 'cancelled') {
                setNotice('Run cancelled.')
              } else {
                setError(friendlyEngineError(status.error ?? '', 'The run failed.'))
              }
            }
          } catch {
            if (jobIdRef.current !== jobId) return
            stopPolling()
            setRunning(false)
            setError('Lost contact with the run.')
          }
        })()
      }, MONTE_CARLO_POLL_INTERVAL_MS)
    } catch (e) {
      setRunning(false)
      setError(friendlyEngineError(e, 'Could not start the run.'))
    }
  }

  // Wave 2: stop polling immediately; the server-side cancel is best effort
  // (cancelMonteCarlo never throws — a finished/unknown job resolves false).
  async function handleCancel() {
    const jobId = jobIdRef.current
    stopPolling()
    setRunning(false)
    setNotice('Run cancelled.')
    if (jobId) await cancelMonteCarlo(jobId)
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
          aria-label="Add another input as a driver"
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
            aria-label={`Distribution for ${inputList.find((f) => f.id === driver.inputPath)?.label ?? driver.inputPath}`}
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
          {PARAM_FIELDS[driver.distribution].map((p) => {
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
            aria-label={`Remove driver ${inputList.find((f) => f.id === driver.inputPath)?.label ?? driver.inputPath}`}
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
            aria-invalid={!seedParse.ok}
            aria-describedby={seedParse.ok ? undefined : 'mc-seed-error'}
            inputMode="numeric"
            className={`w-28 rounded border px-1 py-0.5 ${
              seedParse.ok ? 'border-slate-300' : 'border-red-400'
            }`}
          />
        </label>
        {!seedParse.ok && (
          <span id="mc-seed-error" className="text-red-600">
            {seedParse.error}
          </span>
        )}
        <button
          onClick={() => void handleRun()}
          disabled={running || drivers.length === 0 || !seedParse.ok}
          className="rounded bg-sky-600 px-3 py-1.5 text-white hover:bg-sky-700 disabled:opacity-40"
        >
          {running ? `Running… ${progress}/${n}` : 'Run simulation'}
        </button>
        {running && (
          <button
            onClick={() => void handleCancel()}
            className="rounded border border-slate-300 px-3 py-1.5 text-slate-600 hover:bg-slate-50"
          >
            Cancel
          </button>
        )}
        {error && <span className="text-red-600">{error}</span>}
        {notice && !error && <span className="text-slate-500">{notice}</span>}
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
          <MonteCarloCharts
            leveredIrr={result.leveredIrr}
            bins={result.histogram.leveredIrr}
            hurdleIrr={result.hurdleIrr}
            probIrrNegative={result.probIrrNegative}
            probIrrBelowHurdle={result.probIrrBelowHurdle}
          />

          {dealScenarios.length > 0 && (
            <div className="mt-3 flex items-center gap-2 text-xs">
              <span className="font-medium text-slate-500">SAVE RUN TO SCENARIO</span>
              <select
                value={saveTargetId}
                aria-label="Scenario to save the run to"
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
