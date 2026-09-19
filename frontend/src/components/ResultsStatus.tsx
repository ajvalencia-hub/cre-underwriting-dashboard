import { describeStamp, type ResultStamp } from '../lib/resultFreshness'
import { fieldIdFromMissing } from '../lib/goToField'
import type { ComputeFailure } from '../lib/useComputeResults'

interface ResultsStatusProps {
  latest: ResultStamp | null
  stale: boolean
  computing: boolean
  failure: ComputeFailure | null
  onRecompute: () => void
  onGoToField: (fieldId: string) => void
  labelOf: (fieldId: string) => string
}

/** Top of the summary sidebar: are these numbers current, and from where. */
export default function ResultsStatus({
  latest,
  stale,
  computing,
  failure,
  onRecompute,
  onGoToField,
  labelOf,
}: ResultsStatusProps) {
  const recompute = (
    <button
      onClick={onRecompute}
      disabled={computing}
      className="rounded bg-slate-900 px-2 py-0.5 text-[11px] text-white hover:bg-slate-700 disabled:opacity-50"
      title="Compute with the inputs on screen (⌘↩)"
    >
      {computing ? 'Computing…' : latest ? 'Recompute' : 'Compute'} <span className="opacity-60">⌘↩</span>
    </button>
  )

  return (
    <div className="mb-4 space-y-2 text-xs" aria-live="polite">
      {failure && (
        <div className="rounded border border-red-200 bg-red-50 px-2 py-1.5 text-red-700">
          <div className="font-medium">Last compute failed{latest ? ' — the numbers below are older' : ''}.</div>
          {failure.missing.length > 0 ? (
            <div className="mt-0.5">
              Fill in:{' '}
              {failure.missing.map((entry) => {
                const id = fieldIdFromMissing(entry)
                return (
                  <button key={entry} onClick={() => onGoToField(id)} className="mr-1.5 underline decoration-dotted">
                    {labelOf(id)}
                  </button>
                )
              })}
            </div>
          ) : (
            <div className="mt-0.5">{failure.message}</div>
          )}
        </div>
      )}
      {latest && stale && (
        <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-amber-700">
          <div className="font-medium">Out of date — inputs changed since these results.</div>
          <div className="mt-0.5 flex items-center justify-between gap-2">
            <span className="text-[11px]">Struck-through values don't reflect the inputs on screen.</span>
            {recompute}
          </div>
        </div>
      )}
      {latest && !stale && (
        <div className="flex items-center justify-between gap-2 text-slate-500">
          <span>
            <span className="font-medium text-emerald-600">Current</span> · {describeStamp(latest)}
          </span>
          {recompute}
        </div>
      )}
      {!latest && (
        <div className="flex items-center justify-between gap-2 text-slate-500">
          <span>No results for this deal yet.</span>
          {recompute}
        </div>
      )}
    </div>
  )
}
