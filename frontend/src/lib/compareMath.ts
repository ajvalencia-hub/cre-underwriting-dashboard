// Side-by-side comparison math (wave 2). Shared by the Scenarios panel's
// comparison view and the Compare page: the direction-aware "best value"
// highlight, the row builder over computed outputs, CSV export and the
// persisted selection. Rendering-side only — no financial math here.

import {
  ACQUISITION_QUICK_SCREEN_INPUTS_KEY,
  QUICK_SCREEN_INPUTS_KEY,
  QUICK_SCREEN_MODE_KEY,
} from './dealPersistence'
import type { DealType } from './dealStages'
import { isOutputVisibleFor } from './outputVisibility'
import type { OutputMetric } from '../types/schema'

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

/** Index of the best value across columns, or null when the metric has no
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

// ------------------------------------------------------------ Compare page

export const MIN_COMPARE_DEALS = 2
export const MAX_COMPARE_DEALS = 4
export const COMPARE_STORAGE_KEY = 'cre.compareDealIds'

interface StorageLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export function loadCompareIds(storage: StorageLike): string[] {
  try {
    const parsed = JSON.parse(storage.getItem(COMPARE_STORAGE_KEY) ?? '[]')
    if (!Array.isArray(parsed)) return []
    return parsed.filter((v): v is string => typeof v === 'string').slice(0, MAX_COMPARE_DEALS)
  } catch {
    return []
  }
}

export function saveCompareIds(storage: StorageLike, ids: readonly string[]): void {
  storage.setItem(COMPARE_STORAGE_KEY, JSON.stringify(ids.slice(0, MAX_COMPARE_DEALS)))
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

/** Deal.inputs minus the quick-screen persistence keys — the same shape
 *  App's form values have, which is what the compute endpoint expects. */
export function dealFormValues(inputs: Record<string, unknown>): Record<string, unknown> {
  const {
    [QUICK_SCREEN_INPUTS_KEY]: _qs,
    [ACQUISITION_QUICK_SCREEN_INPUTS_KEY]: _aqs,
    [QUICK_SCREEN_MODE_KEY]: _mode,
    ...values
  } = inputs
  return values
}

export interface CompareColumn {
  dealId: string
  name: string
  dealType: DealType | null
  /** Computed outputs, or null when the deal is not computable. */
  outputs: Record<string, unknown> | null
  /** Why it is not computable (untyped, engine error, …). */
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
 *  instead of a misleading dash. */
export function buildCompareRows(metrics: readonly OutputMetric[], columns: readonly CompareColumn[]): CompareRow[] {
  const rows: CompareRow[] = []
  for (const metric of metrics) {
    const applicable = columns.map((c) => isOutputVisibleFor(metric.id, c.dealType))
    if (!applicable.some(Boolean)) continue
    const values = columns.map((c, i) => {
      if (!applicable[i] || !c.outputs) return null
      const v = c.outputs[metric.id]
      return typeof v === 'number' && Number.isFinite(v) ? v : null
    })
    rows.push({ metric, values, applicable, best: bestValueIndex(metric.id, values) })
  }
  return rows
}

function csvCell(text: string): string {
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
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
    const cells = row.values.map((v, i) =>
      !row.applicable[i] ? 'n/a' : v === null ? '' : format(row.metric, v),
    )
    lines.push([row.metric.label, ...cells].map(csvCell).join(','))
  }
  return lines.join('\n')
}
