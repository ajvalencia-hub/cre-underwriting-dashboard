import { useState } from 'react'
import { formatOutputValue } from '../lib/formatValue'
import { SOURCE_TAG } from '../lib/resultFreshness'
import type { OutputMetric } from '../types/schema'
import { headlineIds } from '../lib/headlineMetrics'
import { isOutputVisibleFor } from '../lib/outputVisibility'

export interface MetricView {
  value: unknown
  provenance: 'native' | 'excel' | 'estimate' | 'none'
  stale: boolean
  /** Quick Screen can't estimate it; only a full compute produces it. */
  fullModelOnly: boolean
}

interface MetricsSidebarProps {
  metrics: OutputMetric[]
  view: (metric: OutputMetric) => MetricView
  dealType: unknown
  /** A build-to-sell deal leads with margin, peak equity and sellout. */
  forSale?: boolean
  irrConvention: 'periodic_monthly' | 'xirr' | null
  onGoalSeek: (metric: OutputMetric) => void
}


function hasValue(v: MetricView): boolean {
  return v.value !== undefined && v.value !== null && v.value !== ''
}

function valueClass(v: MetricView): string {
  // Stale: still legible (to compare against the new result), marked by a
  // tag rather than a strike-through that made the number hard to read.
  if (v.stale) return 'text-slate-500'
  if (v.provenance === 'native' || v.provenance === 'excel') return 'text-slate-800'
  if (v.provenance === 'estimate') return 'italic text-slate-400'
  return 'text-slate-400'
}

function SourceTag({ v }: { v: MetricView }) {
  if (v.stale) {
    return (
      <span
        className="ml-1 rounded bg-amber-50 px-1 text-[10px] font-normal not-italic text-amber-700"
        title="Inputs changed since this was computed — recompute to update it."
      >
        stale
      </span>
    )
  }
  if (v.provenance === 'native' || v.provenance === 'excel') {
    return (
      <span className={`ml-1 text-[10px] font-normal ${v.provenance === 'excel' ? 'text-emerald-700' : 'text-sky-700'}`}>
        {SOURCE_TAG[v.provenance]}
      </span>
    )
  }
  if (v.provenance === 'estimate') return <span className="ml-1 not-italic text-[10px] text-slate-400">est.</span>
  return null
}

export default function MetricsSidebar({ metrics, view, dealType, forSale = false, irrConvention, onGoalSeek }: MetricsSidebarProps) {
  const [showEmpty, setShowEmpty] = useState(false)
  const byId = new Map(metrics.map((m) => [m.id, m]))
  const headline = headlineIds(dealType, forSale)
    .map((id) => byId.get(id))
    .filter((m): m is OutputMetric => m !== undefined)
  const headlineSet = new Set(headline.map((m) => m.id))
  const constraint = byId.get('governingConstraint')
  const constraintView = constraint ? view(constraint) : null
  const groups = Array.from(new Set(metrics.map((m) => m.group ?? 'Metrics')))
  // Run 6 P1: the detail list hides metrics that don't apply to this deal's
  // type (development spread on an acquisition, …); untyped deals see all.
  const typeForVisibility =
    dealType === 'acquisition' || dealType === 'development' ? dealType : null
  const detail = metrics.filter(
    (m) =>
      !headlineSet.has(m.id) &&
      m.id !== 'governingConstraint' &&
      isOutputVisibleFor(m.id, typeForVisibility),
  )
  const emptyCount = detail.filter((m) => !hasValue(view(m))).length

  return (
    <div>
      <div className="mb-1.5 text-[11px] font-semibold tracking-wide text-slate-400">KEY METRICS</div>
      <div className="grid grid-cols-2 gap-1.5">
        {headline.map((metric) => {
          const v = view(metric)
          return (
            <div key={metric.id} className="rounded border border-slate-200 bg-white px-2 py-1.5">
              <div className="flex items-center justify-between text-[11px] text-slate-500">
                <span className="truncate" title={metric.label}>
                  {metric.label}
                </span>
                <button
                  onClick={() => onGoalSeek(metric)}
                  title={`Goal-seek ${metric.label}`}
                  aria-label={`Goal-seek ${metric.label}`}
                  className="text-[10px] text-sky-500 hover:text-sky-700"
                >
                  ◎
                </button>
              </div>
              <div
                className={`text-lg font-semibold tabular-nums ${valueClass(v)}`}
                title={v.fullModelOnly ? 'Needs a full compute (Deal Inputs → Compute).' : undefined}
              >
                {formatOutputValue(metric, v.value)}
              </div>
              <div className="h-3 text-right leading-3">
                <SourceTag v={v} />
              </div>
            </div>
          )
        })}
      </div>
      {constraintView && hasValue(constraintView) && (
        <div className={`mt-1.5 text-xs ${constraintView.stale ? 'text-slate-400 line-through' : 'text-slate-600'}`}>
          Loan sized by: <span className="font-medium">{String(constraintView.value)}</span>
        </div>
      )}
      {irrConvention && (
        <p className="mt-1 text-[10px] text-slate-400">
          IRRs: {irrConvention === 'xirr' ? 'date-based XIRR (Actual/365)' : 'periodic monthly, annualized'}
        </p>
      )}

      <div className="mt-4">
        {groups.map((group) => {
          const rows = detail.filter((m) => (m.group ?? 'Metrics') === group && (showEmpty || hasValue(view(m))))
          if (rows.length === 0) return null
          return (
            <details key={group} open className="mb-3">
              <summary className="mb-1.5 cursor-pointer select-none text-[11px] font-semibold tracking-wide text-slate-400">
                {group.toUpperCase()}
              </summary>
              <ul className="space-y-1.5 text-sm">
                {rows.map((metric) => {
                  const v = view(metric)
                  return (
                    <li key={metric.id} className="group flex items-center justify-between text-slate-500">
                      <span>
                        {metric.label}
                        {metric.type !== ('text' as string) && (
                          <button
                            onClick={() => onGoalSeek(metric)}
                            title={`Goal-seek ${metric.label}`}
                            aria-label={`Goal-seek ${metric.label}`}
                            // Invisible until hover OR keyboard focus (it was
                            // display:none, so unreachable by keyboard).
                            className="ml-1 text-[10px] text-sky-700 opacity-0 group-hover:opacity-100 focus:opacity-100"
                          >
                            ◎
                          </button>
                        )}
                      </span>
                      <span className={`tabular-nums ${valueClass(v)} ${hasValue(v) && !v.stale ? 'font-medium' : ''}`}>
                        {formatOutputValue(metric, v.value)}
                        <SourceTag v={v} />
                      </span>
                    </li>
                  )
                })}
              </ul>
            </details>
          )
        })}
        {emptyCount > 0 && (
          <button onClick={() => setShowEmpty((s) => !s)} className="text-[11px] text-slate-400 underline">
            {showEmpty ? 'Hide metrics without a value' : `Show ${emptyCount} metric(s) without a value`}
          </button>
        )}
      </div>
    </div>
  )
}
