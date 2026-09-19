import { useMemo } from 'react'
import { BarChart, LineChart, StatTileRow } from '../charts'
import { exceedanceCurve, histogramByHurdle, type Bin } from '../../lib/analysisChartData'
import type { McStats } from '../../lib/api'
import { count, pct0, pct1, pct2 } from './format'

interface Props {
  leveredIrr: McStats
  bins: Bin[] | undefined
  hurdleIrr: number
  probIrrNegative: number
  probIrrBelowHurdle: number
}

/** J8 Monte Carlo read-out: the headline odds as tiles, the IRR distribution
 *  split at the hurdle, and the exceedance curve ("chance IRR is at least x"). */
export function MonteCarloCharts({ leveredIrr, bins, hurdleIrr, probIrrNegative, probIrrBelowHurdle }: Props) {
  const hist = useMemo(() => histogramByHurdle(bins ?? [], hurdleIrr, pct1), [bins, hurdleIrr])
  const exceed = useMemo(() => exceedanceCurve(bins ?? []), [bins])
  const hurdle = pct2(hurdleIrr)
  return (
    <div className="mt-3 space-y-5 rounded border border-slate-200 bg-white p-3">
      <StatTileRow
        tiles={[
          { key: 'p50', label: 'Median levered IRR (P50)', value: pct2(leveredIrr.p50), hint: `P5 ${pct2(leveredIrr.p5)} · P95 ${pct2(leveredIrr.p95)}` },
          { key: 'neg', label: 'Chance IRR < 0', value: pct1(probIrrNegative) },
          { key: 'hurdle', label: `Chance IRR < ${hurdle} hurdle`, value: pct1(probIrrBelowHurdle) },
        ]}
      />
      <div className="grid grid-cols-1 gap-x-8 gap-y-6 lg:grid-cols-2">
        <BarChart
          title="Levered IRR distribution"
          subtitle={`Trials per IRR bin · split at the ${hurdle} hurdle (by bin start)`}
          categories={hist.categories}
          categoryLabel="Levered IRR"
          mode="stacked"
          series={
            hist.split
              ? [
                  { key: 'below', label: `Below ${hurdle}`, values: hist.below, slot: 2 },
                  { key: 'above', label: `At or above ${hurdle}`, values: hist.above, slot: 1 },
                ]
              : [{ key: 'all', label: 'Trials', values: hist.below, slot: 1 }]
          }
          format={count}
          height={220}
          emptyMessage="No distribution to plot — every trial failed."
        />
        <LineChart
          title="Chance of reaching each IRR"
          subtitle="% of successful trials with levered IRR at or above x"
          x={exceed.edges}
          xFormat={(v) => pct1(Number(v))}
          xLabel="Levered IRR ≥"
          series={[{ key: 'p', label: 'Share of trials', values: exceed.prob, slot: 1 }]}
          format={pct1}
          tickFormat={pct0}
          includeZero
          emptyMessage="No distribution to plot — every trial failed."
        />
      </div>
    </div>
  )
}
