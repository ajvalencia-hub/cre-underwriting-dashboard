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

// The direction-aware best-value highlight lives with the Compare page's
// math (one table for both views); re-exported here for existing callers.
export { METRIC_DIRECTION, bestValueIndex } from './compareMath'

// ---------------------------------------------------------------- tornado

export interface TornadoBar {
  key: string
  label: string
  low: number | null
  high: number | null
  impact: number
  inert?: boolean
  reason?: string | null
}

export interface TornadoGeometry {
  key: string
  label: string
  /** Run 6: true when the engine reports the driver cannot move this deal
   *  shape — rendered as a muted bar with the reason, not a silent zero. */
  inert: boolean
  reason?: string
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
      inert: b.inert === true,
      reason: b.reason ?? undefined,
      x0: toX(Math.min(lo, hi)),
      x1: toX(Math.max(lo, hi)),
      lowX: toX(lo),
      highX: toX(hi),
      lowLabel: b.low === null ? '—' : format(b.low),
      highLabel: b.high === null ? '—' : format(b.high),
    }
  })
}
