import { useMemo } from 'react'
import { BarChart } from '../charts'
import { devCostBreakdown, noiSplit } from '../../lib/analysisChartData'
import { money, moneyCompact, mult } from './format'

/** Development Quick Screen: what the total development cost is made of. */
export function DevCostChart({
  results,
  landCost,
}: {
  results: { hardCosts: number; softCosts: number; contingency: number; developerFee: number; financingCost: number }
  landCost: number
}) {
  const parts = useMemo(() => devCostBreakdown(results, landCost), [results, landCost])
  const total = parts.reduce((acc, p) => acc + p.value, 0)
  return (
    <BarChart
      title="Cost build-up"
      subtitle={`$ · total ${money(total)}`}
      categories={parts.map((p) => p.label)}
      categoryLabel="Component"
      orientation="horizontal"
      series={[{ key: 'cost', label: 'Cost', values: parts.map((p) => p.value), slot: 1 }]}
      format={money}
      tickFormat={moneyCompact}
    />
  )
}

/** Acquisition Quick Screen: where stabilized NOI goes — debt service first,
 *  the rest to equity (negative when debt service exceeds NOI). */
export function NoiSplitChart({
  results,
}: {
  results: { stabilizedNoi: number; annualDebtService: number; leveredCashFlow: number; minDscr: number | null }
}) {
  const split = useMemo(() => noiSplit(results), [results])
  if (!split) return null
  return (
    <BarChart
      title="Where NOI goes"
      subtitle={`$ per stabilized year · NOI ${money(split.noi)}${
        results.minDscr !== null && Number.isFinite(results.minDscr) ? ` · DSCR ${mult(results.minDscr)}` : ''
      }`}
      categories={['Stabilized NOI']}
      categoryLabel="Year"
      orientation="horizontal"
      mode="stacked"
      series={[
        { key: 'ds', label: 'Debt service', values: [split.debtService], slot: 2 },
        { key: 'cf', label: 'Cash flow to equity', values: [split.cashFlow], slot: 1 },
      ]}
      format={money}
      tickFormat={moneyCompact}
      height={72}
    />
  )
}
