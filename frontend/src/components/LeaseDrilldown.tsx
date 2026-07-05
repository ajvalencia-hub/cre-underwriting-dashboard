import { useState } from 'react'
import {
  annualize,
  sliceToCsv,
  SLICE_ROWS,
  type LeaseSlice,
} from '../lib/leaseSlice'

interface LeaseDrilldownProps {
  perLease: LeaseSlice[]
}

const money = (v: number) => `$${Math.round(v).toLocaleString()}`

function downloadCsv(slice: LeaseSlice, mode: 'monthly' | 'annual') {
  const blob = new Blob([sliceToCsv(slice, mode)], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `lease-${slice.suiteId}-${mode}.csv`
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

/** I8: per-lease drill-down — the engine's own per-lease slice, no client
 *  math beyond annual summing. */
export default function LeaseDrilldown({ perLease }: LeaseDrilldownProps) {
  const [mode, setMode] = useState<'annual' | 'monthly'>('annual')

  if (perLease.length === 0) return null

  return (
    <div className="mt-3 border-t border-slate-100 pt-2">
      <div className="flex items-center gap-3">
        <div className="text-xs font-semibold text-slate-500">PER-LEASE DRILL-DOWN</div>
        <div className="flex rounded border border-slate-200 text-[11px]">
          {(['annual', 'monthly'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-2 py-0.5 ${
                mode === m ? 'bg-slate-900 text-white' : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {m}
            </button>
          ))}
        </div>
      </div>
      {perLease.map((slice) => {
        const vectors = SLICE_ROWS.map(({ key, label }) => ({
          label,
          values:
            mode === 'annual'
              ? annualize(slice[key] as number[])
              : (slice[key] as number[]),
        }))
        const periods = vectors[0].values.length
        return (
          <details key={slice.suiteId} className="mt-1 rounded border border-slate-100">
            <summary className="cursor-pointer select-none px-2 py-1 text-xs text-slate-600 hover:bg-slate-50">
              <span className="font-medium">{slice.suiteId}</span>
              {slice.tenant ? ` · ${slice.tenant}` : ''} ·{' '}
              {Math.round(slice.sf).toLocaleString()} SF · {slice.recoveryType}
              {slice.endDate ? ` · expires ${slice.endDate}` : ' · no end date'}
            </summary>
            <div className="p-2">
              {slice.rolloverEvents.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1">
                  {slice.rolloverEvents.map((event, i) => (
                    <span
                      key={i}
                      className="rounded bg-violet-50 px-1.5 py-0.5 text-[10px] text-violet-700"
                      title={`Renewal probability ${Math.round(event.renewalProbability * 100)}%, downtime ${event.downtimeMonths} mo`}
                    >
                      Gen {i + 1}: expires M{event.expiryMonth} → commences M
                      {event.commencementMonth} @ ${event.startRentPsf}/SF
                    </span>
                  ))}
                </div>
              )}
              <div className="max-w-full overflow-x-auto">
                <table className="text-[11px]">
                  <thead>
                    <tr className="text-left text-slate-400">
                      <th className="px-2 py-0.5 font-medium">Series</th>
                      {Array.from({ length: periods }, (_, i) => (
                        <th key={i} className="px-2 py-0.5 text-right font-medium">
                          {mode === 'annual' ? `Y${i + 1}` : `M${i + 1}`}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {vectors.map(({ label, values }) => (
                      <tr key={label} className="border-t border-slate-50 text-slate-600">
                        <td className="whitespace-nowrap px-2 py-0.5">{label}</td>
                        {values.map((v, i) => (
                          <td key={i} className="px-2 py-0.5 text-right tabular-nums">
                            {v === 0 ? '—' : money(v)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <button
                onClick={() => downloadCsv(slice, mode)}
                className="mt-2 rounded border border-slate-200 px-2 py-0.5 text-[11px] text-slate-500 hover:bg-slate-50"
              >
                Export {mode} CSV
              </button>
            </div>
          </details>
        )
      })}
    </div>
  )
}
