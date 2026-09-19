// Side-by-side comparison math. Shared by the Scenarios panel's comparison
// view (METRIC_DIRECTION / bestValueIndex, re-exported from
// scenarioComparison.ts) and the Compare page: the direction-aware "best
// value" highlight, the row builder over computed outputs, CSV export and
// the persisted selection. Rendering-side only — no financial math here.

import { hydrateDealState } from './dealPersistence'
import type { DealType } from './dealStages'
import { isOutputVisibleFor } from './outputVisibility'
import type { StorageLike } from './safeStorage'
import type { OutputMetric } from '../types/schema'

/** Direction of "good" per output metric. Metrics where better is genuinely
 *  ambiguous (leverage level, going-in cap — a buyer wants it high, a seller
 *  low; peak equity; fees) are omitted and never highlighted. */
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
  trendedYieldOnCost: 'up',
  developmentSpreadBps: 'up',
  breakEvenOccupancy: 'down',
  terminalValue: 'up',
  netSaleProceeds: 'up',
  totalProfit: 'up',
  grossMarginPct: 'up',
  npv: 'up',
  profitabilityIndex: 'up',
  minDscr: 'up',
  minMonthlyDscr: 'up',
  avgDscr: 'up',
  stressedDscr: 'up',
  debtYield: 'up',
  goingInDebtYield: 'up',
  breakEvenRatio: 'down',
  interestCoverageRatio: 'up',
  prepaymentCost: 'down',
}

/** Index of the best value across columns, or null when the metric has no
 *  unambiguous direction, fewer than 2 numeric values, or a tie. */
export function bestValueIndex(metricId: string, values: (number | null | undefined)[]): number | null {
  const direction = METRIC_DIRECTION[metricId]
  if (!direction) return null
  const numeric = values
    .map((v, i) => ({ v, i }))
    .filter((e): e is { v: number; i: number } => typeof e.v === 'number' && Number.isFinite(e.v))
  if (numeric.length < 2) return null
  const best = numeric.reduce((a, b) => (direction === 'up' ? (b.v > a.v ? b : a) : b.v < a.v ? b : a))
  const tied = numeric.filter((e) => e.v === best.v)
  return tied.length > 1 ? null : best.i
}

// ------------------------------------------------------------ Compare page

export const MIN_COMPARE_DEALS = 2
export const MAX_COMPARE_DEALS = 4
export const COMPARE_STORAGE_KEY = 'cre.compareDealIds'

export function loadCompareIds(storage: StorageLike): string[] {
  try {
    const parsed: unknown = JSON.parse(storage.getItem(COMPARE_STORAGE_KEY) ?? '[]')
    if (!Array.isArray(parsed)) return []
    return [...new Set(parsed.filter((v): v is string => typeof v === 'string'))].slice(0, MAX_COMPARE_DEALS)
  } catch {
    return []
  }
}

export function saveCompareIds(storage: StorageLike, ids: readonly string[]): void {
  try {
    storage.setItem(COMPARE_STORAGE_KEY, JSON.stringify(ids.slice(0, MAX_COMPARE_DEALS)))
  } catch {
    // storage unavailable — the selection just isn't remembered
  }
}

/** Toggle a deal in the selection; a full selection ignores additions. */
export function toggleCompareId(ids: readonly string[], id: string, max = MAX_COMPARE_DEALS): string[] {
  if (ids.includes(id)) return ids.filter((x) => x !== id)
  if (ids.length >= max) return [...ids]
  return [...ids, id]
}

/** Drop ids that no longer exist in the list (deleted/archived deals). */
export function pruneCompareIds(ids: readonly string[], existing: readonly { id: string }[]): string[] {
  const known = new Set(existing.map((d) => d.id))
  return ids.filter((id) => known.has(id))
}

/** What the dashboard would compute for a saved deal: its inputs minus the
 *  quick-screen persistence keys, over the schema defaults (the same
 *  hydration App does when the deal is opened). */
export function dealFormValues(
  inputs: Record<string, unknown>,
  schemaDefaults: Record<string, unknown> = {},
): Record<string, unknown> {
  return hydrateDealState(schemaDefaults, inputs).formValues
}

export interface CompareColumn {
  dealId: string
  name: string
  dealType: DealType | null
  /** Computed outputs, or null when the deal is not computable. */
  outputs: Record<string, unknown> | null
  /** Why it is not computable (untyped, missing inputs, engine error…). */
  note?: string
}

export interface CompareRow {
  metric: OutputMetric
  /** One entry per column: the numeric value, or null. */
  values: (number | null)[]
  /** Whether the metric applies to that column's deal type at all. */
  applicable: boolean[]
  best: number | null
}

/** Rows for every metric visible for AT LEAST one column's deal type; a
 *  cell not applicable to its column is flagged so the UI can render "n/a"
 *  instead of a misleading dash. A metric no computed column produced a
 *  number for (e.g. for-sale or hotel metrics on a rental comparison) is
 *  dropped, like the sidebar hides empty metrics. */
export function buildCompareRows(metrics: readonly OutputMetric[], columns: readonly CompareColumn[]): CompareRow[] {
  const rows: CompareRow[] = []
  const anyComputed = columns.some((c) => c.outputs)
  for (const metric of metrics) {
    const applicable = columns.map((c) => isOutputVisibleFor(metric.id, c.dealType))
    if (!applicable.some(Boolean)) continue
    const values = columns.map((c, i) => {
      if (!applicable[i] || !c.outputs) return null
      const v = c.outputs[metric.id]
      return typeof v === 'number' && Number.isFinite(v) ? v : null
    })
    if (anyComputed && values.every((v) => v === null)) continue
    rows.push({ metric, values, applicable, best: bestValueIndex(metric.id, values) })
  }
  return rows
}

function csvCell(text: string): string {
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/** CSV of the rendered table: formatted values, "n/a" where not applicable,
 *  an empty cell where not computed. */
export function compareToCsv(
  rows: readonly CompareRow[],
  columns: readonly CompareColumn[],
  format: (metric: OutputMetric, value: number) => string,
): string {
  const lines = [['Metric', ...columns.map((c) => c.name)].map(csvCell).join(',')]
  for (const row of rows) {
    const cells = row.values.map((v, i) => (!row.applicable[i] ? 'n/a' : v === null ? '' : format(row.metric, v)))
    lines.push([row.metric.label, ...cells].map(csvCell).join(','))
  }
  return lines.join('\n')
}
