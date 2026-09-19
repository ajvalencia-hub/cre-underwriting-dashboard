import { useMemo } from 'react'
import { BarChart } from '../charts'
import type { SeriesSlot } from '../charts'
import type { CompareColumn, CompareRow } from '../../lib/compareMath'
import { compareFamilyCharts, type CompareFamilyChart } from '../../lib/portfolioChartData'
import { CARD, fmtMoney, fmtMoneyCompact, fmtMultiple, fmtPct0, fmtPct2 } from './format'

const FORMAT: Record<CompareFamilyChart['type'], { format: (v: number) => string; tick: (v: number) => string }> = {
  percent: { format: fmtPct2, tick: fmtPct0 },
  multiple: { format: fmtMultiple, tick: fmtMultiple },
  currency: { format: fmtMoney, tick: fmtMoneyCompact },
}

/** One grouped bar chart per unit family (%, x, $); each deal keeps its
 *  slot on every chart and on the table header swatch. The best-value line
 *  under each chart repeats the table's own picks (row.best). */
export function CompareCharts({
  rows,
  columns,
  slots,
}: {
  rows: readonly CompareRow[]
  columns: readonly CompareColumn[]
  slots: Readonly<Record<string, SeriesSlot>>
}) {
  const charts = useMemo(() => compareFamilyCharts(rows, columns, slots), [rows, columns, slots])
  if (charts.length === 0) return null
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
      {charts.map((c) => (
        <div key={c.key} className={CARD}>
          <BarChart
            title={c.title}
            subtitle={`${c.unit} · one bar per deal`}
            categories={c.categories}
            series={c.series}
            format={FORMAT[c.type].format}
            tickFormat={FORMAT[c.type].tick}
            orientation="horizontal"
            categoryLabel="Metric"
            height={c.categories.length * (c.series.length * 12 + 18) + 32}
          />
          {c.best.length > 0 && (
            <p className="mt-1 text-[11px] text-slate-500">
              <span className="font-medium">Best</span>{' '}
              {c.best.map((b, i) => (
                <span key={b.metric}>
                  {i > 0 ? ' · ' : ''}
                  {b.metric}: <span className="font-medium text-slate-700">{b.deal}</span>
                </span>
              ))}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}
