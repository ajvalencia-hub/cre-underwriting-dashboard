// A scenario's difference from the base scenario, in the unit an analyst
// reads it in (roadmap #16): rates in basis points, multiples in x,
// dollars in dollars.
import { formatMoney } from './money'
import type { OutputMetric } from '../types/schema'

export function formatDelta(metric: Pick<OutputMetric, 'id' | 'type'>, delta: number): string {
  if (Math.abs(delta) < 1e-12) return '±0'
  const sign = delta > 0 ? '+' : '-'
  const abs = Math.abs(delta)
  if (metric.type === 'percent' || metric.id === 'developmentSpreadBps') return `${sign}${Math.round(abs * 10_000)} bps`
  if (metric.type === 'multiple') return `${sign}${abs.toFixed(2)}x`
  if (metric.type === 'currency') return `${sign}${formatMoney(abs)}`
  if (metric.type === 'years') return `${sign}${abs.toFixed(1)} yrs`
  return `${sign}${abs.toLocaleString(undefined, { maximumFractionDigits: 2 })}`
}
