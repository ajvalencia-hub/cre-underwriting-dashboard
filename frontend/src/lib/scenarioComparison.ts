// Pure helpers for the scenario comparison view and the tornado chart.
// Rendering-side only: numbers come from stored scenario outputs and the
// tornado endpoint; nothing here computes financial results.

import type { InputSchema } from '../types/schema'
import type { Scenario } from '../types/scenario'

export interface ComparisonRow {
  fieldId: string
  label: string
  sectionLabel: string
  values: unknown[]
  differs: boolean
}

/** Inputs table for 2-4 scenarios, grouped by schema section. `differs` marks
 *  rows where any scenario deviates; identical rows collapse behind a toggle. */
export function buildComparisonRows(schema: InputSchema, scenarios: Scenario[]): ComparisonRow[] {
  const rows: ComparisonRow[] = []
  const seen = new Set<string>()
  for (const section of schema.sections) {
    for (const field of section.fields) {
      const values = scenarios.map((s) => s.inputs[field.id])
      if (values.every((v) => v === undefined || v === null || v === '')) continue
      seen.add(field.id)
      rows.push({
        fieldId: field.id,
        label: field.label,
        sectionLabel: section.label,
        values,
        differs: valuesDiffer(values),
      })
    }
  }
  // Inputs that exist on scenarios but not in the schema (legacy/custom keys).
  const extraIds = new Set<string>()
  for (const s of scenarios) {
    for (const key of Object.keys(s.inputs)) {
      if (!seen.has(key) && key !== 'quickScreen') extraIds.add(key)
    }
  }
  for (const fieldId of [...extraIds].sort()) {
    const values = scenarios.map((s) => s.inputs[fieldId])
    rows.push({
      fieldId,
      label: fieldId,
      sectionLabel: 'Other',
      values,
      differs: valuesDiffer(values),
    })
  }
  return rows
}

function valuesDiffer(values: unknown[]): boolean {
  const first = JSON.stringify(values[0] ?? null)
  return values.some((v) => JSON.stringify(v ?? null) !== first)
}

/** Direction of "good" per output metric. Metrics where better is genuinely
 *  ambiguous (leverage level, going-in cap — a buyer wants it high, a seller
 *  low) are omitted and never highlighted. */
export const METRIC_DIRECTION: Record<string, 'up' | 'down'> = {
  unleveredIrr: 'up',
  leveredIrr: 'up',
  lpIrr: 'up',
  gpIrr: 'up',
  equityMultiple: 'up',
  unleveredEquityMultiple: 'up',
  lpEquityMultiple: 'up',
  moic: 'up',
  avgCashOnCash: 'up',
  cashOnCashYear1: 'up',
  stabilizedCashOnCash: 'up',
  annualizedReturn: 'up',
  paybackPeriodYears: 'down',
  yieldOnCost: 'up',
  developmentSpreadBps: 'up',
  breakEvenOccupancy: 'down',
  terminalValue: 'up',
  netSaleProceeds: 'up',
  totalProfit: 'up',
  npv: 'up',
  profitabilityIndex: 'up',
  minDscr: 'up',
  avgDscr: 'up',
  debtYield: 'up',
  breakEvenRatio: 'down',
  interestCoverageRatio: 'up',
}

/** Index of the best value across scenarios, or null when the metric has no
 *  unambiguous direction, fewer than 2 numeric values, or a tie. */
export function bestValueIndex(metricId: string, values: (number | null | undefined)[]): number | null {
  const direction = METRIC_DIRECTION[metricId]
  if (!direction) return null
  const numeric = values
    .map((v, i) => ({ v, i }))
    .filter((e): e is { v: number; i: number } => typeof e.v === 'number' && Number.isFinite(e.v))
  if (numeric.length < 2) return null
  const best = numeric.reduce((a, b) =>
    direction === 'up' ? (b.v > a.v ? b : a) : (b.v < a.v ? b : a),
  )
  const tied = numeric.filter((e) => e.v === best.v)
  return tied.length > 1 ? null : best.i
}

// ---------------------------------------------------------------- tornado

export interface TornadoBar {
  key: string
  label: string
  low: number | null
  high: number | null
  impact: number
}

export interface TornadoGeometry {
  key: string
  label: string
  /** bar extents as fractions of chart width, 0.5 = the base value */
  x0: number
  x1: number
  /** label anchor positions: where the DOWN and UP perturbations actually
   *  landed (a down-perturbed cap rate can produce the HIGHER value). */
  lowX: number
  highX: number
  lowLabel: string
  highLabel: string
}

/** Symmetric geometry around the base: the widest swing spans the chart.
 *  Bars are assumed pre-sorted by impact (the endpoint sorts). */
export function tornadoGeometry(
  bars: TornadoBar[],
  base: number,
  format: (v: number) => string,
): TornadoGeometry[] {
  const maxSwing = Math.max(
    1e-12,
    ...bars.flatMap((b) =>
      [b.low, b.high].filter((v): v is number => v !== null).map((v) => Math.abs(v - base)),
    ),
  )
  const toX = (v: number) => 0.5 + ((v - base) / maxSwing) * 0.5
  return bars.map((b) => {
    const lo = b.low ?? base
    const hi = b.high ?? base
    return {
      key: b.key,
      label: b.label,
      x0: toX(Math.min(lo, hi)),
      x1: toX(Math.max(lo, hi)),
      lowX: toX(lo),
      highX: toX(hi),
      lowLabel: b.low === null ? '—' : format(b.low),
      highLabel: b.high === null ? '—' : format(b.high),
    }
  })
}
