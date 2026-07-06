import { useEffect, useMemo, useState } from 'react'
import { fetchGoalSeekInputs, runGoalSeek, type GoalSeekResult } from '../lib/api'
import { formatOutputValue } from '../lib/formatValue'
import type { OutputMetric } from '../types/schema'

interface GoalSeekModalProps {
  metric: OutputMetric
  values: Record<string, unknown>
  /** Writes the solved value through the normal input-change path so
   *  autosave + history record it like any manual edit. */
  onApply: (fieldId: string, value: number) => void
  onClose: () => void
}

/** J7: solve one numeric input so `metric` hits a target value. */
export default function GoalSeekModal({ metric, values, onApply, onClose }: GoalSeekModalProps) {
  const [inputs, setInputs] = useState<{ id: string; label: string; type: string }[]>([])
  const [search, setSearch] = useState('')
  const [targetInput, setTargetInput] = useState('')
  const [targetValue, setTargetValue] = useState('')
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<GoalSeekResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchGoalSeekInputs()
      .then(setInputs)
      .catch(() => setError('Could not load the input list.'))
  }, [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return inputs
    return inputs.filter(
      (f) => f.label.toLowerCase().includes(q) || f.id.toLowerCase().includes(q),
    )
  }, [inputs, search])

  // Percent metrics are typed as decimals ("12" would be 1200%) — accept the
  // human form and divide.
  const parsedTarget = (() => {
    const raw = Number(targetValue)
    if (!Number.isFinite(raw)) return null
    return metric.type === 'percent' ? raw / 100 : raw
  })()

  async function handleRun() {
    if (!targetInput || parsedTarget === null) return
    setRunning(true)
    setError(null)
    setResult(null)
    try {
      setResult(
        await runGoalSeek({
          values,
          targetInput,
          outputMetric: metric.id,
          targetValue: parsedTarget,
        }),
      )
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Goal seek failed.')
    } finally {
      setRunning(false)
    }
  }

  const solvedField = inputs.find((f) => f.id === result?.targetInput)
  const fmtInput = (v: number) =>
    solvedField?.type === 'percent' ? `${(v * 100).toFixed(3)}%` : v.toLocaleString(undefined, { maximumFractionDigits: 4 })

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40"
      onClick={onClose}
    >
      <div
        className="w-[26rem] max-w-[90vw] rounded-lg bg-white p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-slate-700">
            Goal Seek — {metric.label}
          </h2>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            ✕
          </button>
        </div>

        <label className="mb-1 block text-xs text-slate-500">
          Target {metric.label} {metric.type === 'percent' ? '(%)' : ''}
        </label>
        <input
          value={targetValue}
          onChange={(e) => setTargetValue(e.target.value)}
          placeholder={metric.type === 'percent' ? 'e.g. 15 for 15%' : 'target value'}
          className="mb-3 w-full rounded border border-slate-300 px-2 py-1 text-sm"
        />

        <label className="mb-1 block text-xs text-slate-500">By changing input</label>
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="search inputs…"
          className="mb-1 w-full rounded border border-slate-300 px-2 py-1 text-sm"
        />
        <div className="mb-3 max-h-36 overflow-y-auto rounded border border-slate-200">
          {filtered.map((f) => (
            <button
              key={f.id}
              onClick={() => setTargetInput(f.id)}
              className={`block w-full px-2 py-1 text-left text-xs hover:bg-sky-50 ${
                targetInput === f.id ? 'bg-sky-100 font-medium text-sky-800' : 'text-slate-600'
              }`}
            >
              {f.label}
            </button>
          ))}
          {filtered.length === 0 && (
            <div className="px-2 py-1 text-xs text-slate-400">No matching inputs.</div>
          )}
        </div>

        <button
          onClick={handleRun}
          disabled={running || !targetInput || parsedTarget === null}
          className="rounded bg-sky-600 px-3 py-1.5 text-sm text-white hover:bg-sky-700 disabled:opacity-40"
        >
          {running ? 'Solving…' : 'Solve'}
        </button>

        {error && <div className="mt-2 text-xs text-red-600">{error}</div>}

        {result && result.solvedValue !== null && (
          <div className="mt-3 rounded border border-emerald-200 bg-emerald-50 p-2 text-xs text-slate-700">
            <div>
              Solved: <strong>{fmtInput(result.solvedValue)}</strong> →{' '}
              {formatOutputValue(metric, result.achievedMetric)} in {result.iterations}{' '}
              evaluations.
            </div>
            {(result.otherCrossings?.length ?? 0) > 0 && (
              <div className="mt-1 text-amber-600">
                The target is also crossed near{' '}
                {result.otherCrossings!.map(fmtInput).join(', ')} — this solution is the one
                nearest the current input.
              </div>
            )}
            <button
              onClick={() => {
                onApply(result.targetInput, result.solvedValue!)
                onClose()
              }}
              className="mt-2 rounded bg-emerald-600 px-3 py-1 text-white hover:bg-emerald-700"
            >
              Apply to inputs
            </button>
          </div>
        )}
        {result && result.solvedValue === null && (
          <div className="mt-3 rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
            <div>{result.detail ?? 'No solution found.'}</div>
            {result.scanned && (
              <div className="mt-1 text-slate-500">
                Scanned {fmtInput(result.scannedRange[0])} – {fmtInput(result.scannedRange[1])};
                metric ranged{' '}
                {(() => {
                  const ms = result.scanned!.map((s) => s.metric).filter((m): m is number => m !== null)
                  if (ms.length === 0) return 'undefined everywhere'
                  return `${formatOutputValue(metric, Math.min(...ms))} to ${formatOutputValue(metric, Math.max(...ms))}`
                })()}
                .
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
