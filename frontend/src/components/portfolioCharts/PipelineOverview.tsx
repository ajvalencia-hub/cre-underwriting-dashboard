import { useMemo, useState } from 'react'
import { BarChart, StatTileRow } from '../charts'
import type { DealMetrics } from '../../lib/api'
import type { DealType } from '../../lib/dealStages'
import { DEALFLOW_LABEL, DEALFLOW_SLOT, stageEquity } from '../../lib/portfolioChartData'
import { safeStorage } from '../../lib/safeStorage'
import type { DealStatus } from '../../types/deal'
import { fmtMoney, fmtMoneyCompact } from './format'

const OPEN_KEY = 'cre.pipelineOverviewOpen'

interface Props {
  /** Exactly what each board shows (filters, sort and terminal toggle
   *  applied; archived deals are never counted, like the boards' chips). */
  acquisitions: readonly { id: string; status: DealStatus }[]
  developments: readonly { id: string; status: DealStatus }[]
  untypedCount: number
  metrics: Record<string, DealMetrics> | null
}

function StageBar({ type, data }: { type: DealType; data: ReturnType<typeof stageEquity> }) {
  const note = data.notComputed > 0 ? ` · ${data.notComputed} not yet computable` : ''
  return (
    <BarChart
      title={`${DEALFLOW_LABEL[type]}: equity by stage`}
      subtitle={`Committed equity, $ · stage · deals shown${note}`}
      orientation="horizontal"
      categories={data.categories}
      series={[{ key: 'equity', label: 'Equity', values: data.values, slot: DEALFLOW_SLOT[type] }]}
      format={fmtMoney}
      tickFormat={fmtMoneyCompact}
      showValues
      categoryLabel="Stage · deals"
      emptyMessage={
        data.dealCount === 0 ? `No ${type} deals in this view.` : 'No computable equity in this view yet.'
      }
    />
  )
}

/** Compact, collapsible summary above the two boards: KPI row plus equity by
 *  stage per board, charted over the same filtered set the tables show. */
export function PipelineOverview({ acquisitions, developments, untypedCount, metrics }: Props) {
  const [open, setOpen] = useState(() => safeStorage.get(OPEN_KEY) !== '0')
  const acq = useMemo(() => stageEquity('acquisition', acquisitions, metrics), [acquisitions, metrics])
  const dev = useMemo(() => stageEquity('development', developments, metrics), [developments, metrics])
  const shown = acq.dealCount + dev.dealCount
  const equity = acq.totalEquity + dev.totalEquity
  const notComputed = acq.notComputed + dev.notComputed

  return (
    <details
      open={open}
      onToggle={(e) => {
        const next = (e.currentTarget as HTMLDetailsElement).open
        setOpen(next)
        safeStorage.set(OPEN_KEY, next ? '1' : '0')
      }}
      className="rounded border border-slate-200 bg-white"
    >
      <summary className="cursor-pointer px-3 py-2 text-xs text-slate-600">
        <span className="font-semibold tracking-wide text-slate-500">PIPELINE OVERVIEW</span>
        <span className="ml-2 text-slate-500">
          {shown} deal(s) shown · {metrics ? fmtMoneyCompact(equity) : '…'} equity
        </span>
      </summary>
      {open && (
        <div className="space-y-4 border-t border-slate-100 px-3 pb-3 pt-3">
          <StatTileRow
            tiles={[
              {
                key: 'shown',
                label: 'Deals shown',
                value: String(shown),
                hint: `${acq.dealCount} acquisition · ${dev.dealCount} development${untypedCount > 0 ? ` · ${untypedCount} untyped` : ''}`,
              },
              {
                key: 'equity',
                label: 'Committed equity',
                value: metrics ? fmtMoneyCompact(equity) : '—',
                hint: metrics ? fmtMoney(equity) : 'Loading…',
              },
              {
                key: 'missing',
                label: 'Not yet computable',
                value: metrics ? String(notComputed) : '—',
                hint: 'Missing inputs — not in the equity bars',
              },
            ]}
          />
          <div className="grid gap-4 md:grid-cols-2">
            <StageBar type="acquisition" data={acq} />
            <StageBar type="development" data={dev} />
          </div>
        </div>
      )}
    </details>
  )
}
