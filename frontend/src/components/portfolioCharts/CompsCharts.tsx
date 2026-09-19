import { useMemo } from 'react'
import { ScatterChart, StripPlot } from '../charts'
import type { Comp, CompKind } from '../../lib/api'
import {
  compMetric,
  compScatterPoints,
  compStripValues,
  type CompMetric,
  type CompSubject,
} from '../../lib/portfolioChartData'
import { CARD, fmtMoney, fmtMoneyCents, fmtMoneyCompact, fmtPct1, fmtPct2, fmtSf, fmtYear } from './format'

interface StripDef {
  metric: CompMetric
  title: string
  unit: string
  format: (v: number) => string
  tick: (v: number) => string
  subjectLabel: string
}

const STRIPS: Record<CompKind, StripDef[]> = {
  sale: [
    { metric: 'pricePerUnit', title: 'Price per unit', unit: '$ per unit', format: fmtMoney, tick: fmtMoneyCompact, subjectLabel: 'Your deal' },
    { metric: 'pricePerSf', title: 'Price per SF', unit: '$ per SF', format: fmtMoneyCents, tick: fmtMoney, subjectLabel: 'Your deal' },
    { metric: 'capRatePct', title: 'Cap rate', unit: 'Percent', format: fmtPct2, tick: fmtPct1, subjectLabel: 'Your exit cap' },
  ],
  rent: [
    { metric: 'avgRent', title: 'Rent per unit', unit: '$ per unit per month', format: fmtMoney, tick: fmtMoney, subjectLabel: 'Your deal' },
    { metric: 'rentPerSf', title: 'Rent per SF', unit: '$ per SF per month (avg rent ÷ avg unit SF)', format: fmtMoneyCents, tick: fmtMoneyCents, subjectLabel: 'Your deal' },
  ],
}

/** Comp-set distributions (median marked, the active deal as a dashed
 *  reference) plus one relationship scatter, over the comps the table lists. */
export function CompsCharts({ kind, comps, subject }: { kind: CompKind; comps: readonly Comp[]; subject?: CompSubject }) {
  const strips = useMemo(
    () => STRIPS[kind].map((def) => ({ def, values: compStripValues(comps, def.metric) })),
    [kind, comps],
  )
  const scatter = useMemo(
    () =>
      kind === 'sale'
        ? compScatterPoints(comps, (c) => c.yearBuilt, (c) => compMetric(c, 'pricePerUnit'))
        : compScatterPoints(comps, (c) => c.avgSf, (c) => c.avgRent),
    [kind, comps],
  )
  if (comps.length < 2) {
    return (
      <div className={`${CARD} text-xs text-slate-500`}>
        Charts appear once at least two {kind} comps are listed.
      </div>
    )
  }
  return (
    <div className="space-y-4">
      <div className={`grid gap-4 ${kind === 'sale' ? 'md:grid-cols-3' : 'md:grid-cols-2'}`}>
        {strips.map(({ def, values }) => {
          const ref = subject?.[def.metric as keyof CompSubject]
          return (
            <div key={def.metric} className={CARD}>
              <StripPlot
                title={def.title}
                subtitle={`${def.unit} · one dot per comp`}
                rows={[{ key: def.metric, label: def.title, values, slot: 1 }]}
                format={def.format}
                tickFormat={def.tick}
                valueLabel={def.title}
                referenceLine={typeof ref === 'number' ? { value: ref, label: `${def.subjectLabel} ${def.format(ref)}` } : undefined}
                emptyMessage="Fewer than two comps have this value."
              />
            </div>
          )
        })}
      </div>
      {scatter.length > 0 && (
        <div className={CARD}>
          {kind === 'sale' ? (
            <ScatterChart
              title="Price per unit vs year built"
              subtitle="$ per unit (y) by year built (x), one dot per comp"
              series={[{ key: 'comps', label: 'Sale comps', points: scatter, slot: 1 }]}
              xLabel="Year built"
              yLabel="Price per unit"
              xFormat={fmtYear}
              yFormat={fmtMoney}
              yTickFormat={fmtMoneyCompact}
              referenceY={
                typeof subject?.pricePerUnit === 'number'
                  ? { value: subject.pricePerUnit, label: `Your deal ${fmtMoney(subject.pricePerUnit)}` }
                  : undefined
              }
              height={240}
            />
          ) : (
            <ScatterChart
              title="Rent vs unit size"
              subtitle="$ per unit per month (y) by average unit SF (x), one dot per comp"
              series={[{ key: 'comps', label: 'Rent comps', points: scatter, slot: 1 }]}
              xLabel="Avg unit SF"
              yLabel="Avg rent"
              xFormat={fmtSf}
              xTickFormat={(v) => Math.round(v).toLocaleString()}
              yFormat={fmtMoney}
              referenceY={
                typeof subject?.avgRent === 'number'
                  ? { value: subject.avgRent, label: `Your deal ${fmtMoney(subject.avgRent)}` }
                  : undefined
              }
              height={240}
            />
          )}
        </div>
      )}
    </div>
  )
}
