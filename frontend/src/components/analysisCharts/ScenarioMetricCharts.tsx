import { useMemo } from 'react'
import { BarChart, type SeriesSlot } from '../charts'
import { metricFamilies } from '../../lib/analysisChartData'
import type { OutputMetric } from '../../types/schema'
import { mult, pct1, pct2 } from './format'

export interface ComparedScenario {
  id: string
  name: string
  /** Stable color slot — follows the scenario, not its column. */
  slot: SeriesSlot
  /** metric id -> value (null = not available). */
  values: Record<string, number | null>
}

/** Scenario comparison as grouped bars, one chart per unit family
 *  (percentages together, multiples separately — never a shared axis). */
export function ScenarioMetricCharts({ scenarios, metrics }: { scenarios: ComparedScenario[]; metrics: OutputMetric[] }) {
  const families = useMemo(() => {
    const f = metricFamilies(metrics)
    const keep = (ms: OutputMetric[]) => ms.filter((m) => scenarios.some((s) => s.values[m.id] !== null && s.values[m.id] !== undefined))
    return { percent: keep(f.percent), multiple: keep(f.multiple) }
  }, [metrics, scenarios])
  const seriesFor = (ms: OutputMetric[]) =>
    scenarios.map((s) => ({ key: s.id, label: s.name, slot: s.slot, values: ms.map((m) => s.values[m.id] ?? null) }))

  // Metric names are long: horizontal bars, each metric's band sized for
  // one bar per compared scenario.
  const heightFor = (n: number) => n * (scenarios.length * 12 + 16) + 32

  if (families.percent.length === 0 && families.multiple.length === 0) return null
  return (
    <div className="mt-3 grid grid-cols-1 gap-x-8 gap-y-6 rounded border border-slate-200 bg-white p-3 md:grid-cols-2">
      {families.percent.length > 0 && (
        <BarChart
          title="Returns and yields by scenario"
          subtitle="% · headline metrics"
          categories={families.percent.map((m) => m.label)}
          categoryLabel="Metric"
          series={seriesFor(families.percent)}
          orientation="horizontal"
          height={heightFor(families.percent.length)}
          format={pct2}
          tickFormat={pct1}
        />
      )}
      {families.multiple.length > 0 && (
        <BarChart
          title="Multiples by scenario"
          subtitle="x · headline metrics"
          categories={families.multiple.map((m) => m.label)}
          categoryLabel="Metric"
          series={seriesFor(families.multiple)}
          orientation="horizontal"
          height={heightFor(families.multiple.length)}
          format={mult}
        />
      )}
    </div>
  )
}
