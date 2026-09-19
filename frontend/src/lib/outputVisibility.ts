// Sidebar output metrics per dealflow (Run 6 P1). The schema's output
// definitions carry no dealType hint, so the split is an explicit map
// mirroring the engine (backend/app/services/proforma): development spread,
// combined LTC and per-component yield-on-cost only mean something for a
// ground-up deal, and the build-to-sell outputs (gross margin, sellout) are
// only produced by the for-sale engine, which applies to development deals
// only (for_sale.applies). The post-renovation rent is a value-add
// acquisition metric. Untyped deals see everything.

import type { DealType } from './dealStages'

export const DEVELOPMENT_ONLY_OUTPUTS: ReadonlySet<string> = new Set([
  'developmentSpreadBps',
  'combinedLtc',
  'residentialYieldOnCost',
  'commercialYieldOnCost',
  'grossMarginPct',
  'selloutYears',
])

export const ACQUISITION_ONLY_OUTPUTS: ReadonlySet<string> = new Set(['postRenoAvgRent'])

export function isOutputVisibleFor(metricId: string, dealType: DealType | null): boolean {
  if (dealType === 'acquisition') return !DEVELOPMENT_ONLY_OUTPUTS.has(metricId)
  if (dealType === 'development') return !ACQUISITION_ONLY_OUTPUTS.has(metricId)
  return true
}

export function visibleOutputsFor<T extends { id: string }>(
  metrics: readonly T[],
  dealType: DealType | null,
): T[] {
  return metrics.filter((m) => isOutputVisibleFor(m.id, dealType))
}
