// Pure data shaping for the single-deal analysis charts
// (src/components/analysisCharts). Every number comes from an engine result
// (or the Quick Screen's own math) that the page already holds — these only
// regroup, sum or ratio them for display. No compute is ever triggered here.

import { groupIntoYears, type Statement } from './cashflowStatement'
import type { SensitivityPoint } from '../types/sensitivity'

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
const sumAt = (series: readonly number[] | undefined, indices: readonly number[]) =>
  indices.reduce((acc, i) => acc + (series?.[i] ?? 0), 0)

/** Short, one-line-per-period x labels. */
export const yearLabel = (year: number) => `Y${year}`

// ---------------------------------------------------------------- cash flow

export interface AnnualOperating {
  years: string[]
  noi: number[]
  debtService: number[]
  /** Levered cash flow with the exit's net sale proceeds taken out (the
   *  close column is excluded), so the exit year doesn't dwarf operations. */
  leveredOperating: number[]
  /** Annual NOI ÷ annual debt service; null where there's no debt service. */
  dscr: (number | null)[]
  hasDebt: boolean
  /** False for deals with no operating income (e.g. build-to-sell). */
  hasOperations: boolean
}

/** Operating years 1..N summed from the monthly statement. */
export function annualOperating(statement: Statement): AnnualOperating {
  const years = groupIntoYears(statement).filter((c) => c.year !== null)
  const noi = years.map((c) => sumAt(statement.noi, c.indices))
  const debtService = years.map((c) => sumAt(statement.debtService, c.indices))
  const leveredOperating = years.map(
    (c) => sumAt(statement.levered, c.indices) - sumAt(statement.saleProceedsNet, c.indices),
  )
  const dscr = years.map((_, i) => (debtService[i] > 0.5 ? noi[i] / debtService[i] : null))
  return {
    years: years.map((c) => yearLabel(c.year as number)),
    noi,
    debtService,
    leveredOperating,
    dscr,
    hasDebt: debtService.some((v) => v > 0.5),
    hasOperations: noi.some((v) => Math.abs(v) > 0.5),
  }
}

export interface YearEndSeries {
  /** 'Close', then Y1..YN. */
  x: string[]
  values: number[]
}

/** Loan balance at close and at the end of each year (period-end values). */
export function loanBalanceByYear(statement: Statement): YearEndSeries {
  const cols = groupIntoYears(statement)
  return {
    x: cols.map((c) => (c.year === null ? 'Close' : yearLabel(c.year))),
    values: cols.map((c) => statement.loanBalance?.[c.indices[c.indices.length - 1]] ?? 0),
  }
}

/** Cumulative levered cash flow at close and each year end — the equity
 *  J-curve (negative until the equity is paid back). */
export function cumulativeLevered(statement: Statement): YearEndSeries {
  const cols = groupIntoYears(statement)
  let running = 0
  return {
    x: cols.map((c) => (c.year === null ? 'Close' : yearLabel(c.year))),
    values: cols.map((c) => (running += sumAt(statement.levered, c.indices))),
  }
}

/** First year-end label at which the cumulative series turns non-negative
 *  after having been negative, or null if it never pays back. */
export function paybackLabel(series: YearEndSeries): string | null {
  let wasNegative = false
  for (let i = 0; i < series.values.length; i++) {
    if (series.values[i] < -0.5) wasNegative = true
    else if (wasNegative) return series.x[i]
  }
  return null
}

export function hasAnyDebt(statement: Statement): boolean {
  return (statement.loanBalance ?? []).some((v) => Math.abs(v) > 0.5)
}

/** J1 renovation program: units complete / in progress per operating month. */
export function renovationByMonth(renovation: NonNullable<Statement['renovation']>) {
  const months = Math.max(0, renovation.unitsComplete.length - 1) // index 0 = close
  const idx = Array.from({ length: months }, (_, i) => i + 1)
  return {
    months: idx.map((m) => `M${m}`),
    complete: idx.map((m) => renovation.unitsComplete[m] ?? 0),
    inProgress: idx.map((m) => renovation.unitsInProgress[m] ?? 0),
  }
}

// --------------------------------------------------------------- hold sweep

export interface HoldSweepRowLike {
  holdYear: number
  unleveredIrr: number | null
  leveredIrr: number | null
  equityMultiple: number | null
}

export function holdSweepSeries(rows: readonly HoldSweepRowLike[]) {
  return {
    x: rows.map((r) => yearLabel(r.holdYear)),
    levered: rows.map((r) => r.leveredIrr),
    unlevered: rows.map((r) => r.unleveredIrr),
    equityMultiple: rows.map((r) => r.equityMultiple),
  }
}

// ------------------------------------------------------------ quick screens

export interface CostPart {
  label: string
  value: number
}

/** The development cost stack in the order it is built up. */
export function devCostBreakdown(
  results: { hardCosts: number; softCosts: number; contingency: number; developerFee: number; financingCost: number },
  landCost: number,
): CostPart[] {
  return [
    { label: 'Land', value: landCost },
    { label: 'Hard costs', value: results.hardCosts },
    { label: 'Soft costs', value: results.softCosts },
    { label: 'Contingency', value: results.contingency },
    { label: 'Developer fee', value: results.developerFee },
    { label: 'Interest (est.)', value: results.financingCost },
  ].map((p) => ({ ...p, value: finite(p.value) ? p.value : 0 }))
}

/** Where stabilized NOI goes: debt service, then what's left for equity
 *  (negative when debt service exceeds NOI). */
export function noiSplit(results: { stabilizedNoi: number; annualDebtService: number; leveredCashFlow: number }) {
  if (!finite(results.stabilizedNoi) || !finite(results.annualDebtService) || !finite(results.leveredCashFlow)) return null
  return {
    noi: results.stabilizedNoi,
    debtService: results.annualDebtService,
    cashFlow: results.leveredCashFlow,
  }
}

// -------------------------------------------------------------- sensitivity

/** One output metric along a one-driver sweep: the value at each driver
 *  step (raw engine units), matched to the run's points by driver value. */
export function sweepLine(
  points: readonly SensitivityPoint[],
  driverId: string,
  rawDriverValues: readonly number[],
  metricId: string,
): (number | null)[] {
  return rawDriverValues.map((raw) => {
    const p = points.find((pt) => Math.abs(pt.driverValues[driverId] - raw) < 1e-9)
    const v = p ? Number(p.outputs[metricId]) : NaN
    return p && p.outputs[metricId] !== null && p.outputs[metricId] !== '' && Number.isFinite(v) ? v : null
  })
}

/** Heat-grid tint relative to the base case: which pole and how strongly
 *  (0..1). Painted with the --viz-div-* tokens by the page. */
export function heatTint(
  value: number,
  base: number,
  maxAbsDelta: number,
): { side: 'pos' | 'neg' | 'mid'; strength: number } {
  if (!Number.isFinite(value) || !Number.isFinite(base) || !(maxAbsDelta > 0)) return { side: 'mid', strength: 0 }
  const t = Math.max(-1, Math.min(1, (value - base) / maxAbsDelta))
  if (Math.abs(t) < 1e-9) return { side: 'mid', strength: 0 }
  return { side: t > 0 ? 'pos' : 'neg', strength: Math.abs(t) }
}

// ------------------------------------------------------------- Monte Carlo

export interface Bin {
  lo: number
  hi: number
  count: number
}

/** Histogram bins split into two series by the hurdle: a bin counts as
 *  "clears" when its lower edge is at or above the hurdle. */
export function histogramByHurdle(bins: readonly Bin[], hurdle: number | null, fmt: (v: number) => string) {
  const categories = bins.map((b) => `${fmt(b.lo)} to ${fmt(b.hi)}`)
  if (hurdle === null || !Number.isFinite(hurdle)) {
    return { categories, below: bins.map((b) => b.count), above: bins.map(() => null as number | null), split: false }
  }
  return {
    categories,
    below: bins.map((b) => (b.lo < hurdle ? b.count : null)),
    above: bins.map((b) => (b.lo >= hurdle ? b.count : null)),
    split: true,
  }
}

/** Exceedance curve from histogram bins: at each bin's lower edge, the share
 *  of successful trials at or above it (1 at the first edge, falling to the
 *  last bin's share). Empty when there are no counts. */
export function exceedanceCurve(bins: readonly Bin[]): { edges: number[]; prob: number[] } {
  const total = bins.reduce((acc, b) => acc + b.count, 0)
  if (total <= 0) return { edges: [], prob: [] }
  let remaining = total
  const edges: number[] = []
  const prob: number[] = []
  for (const b of bins) {
    edges.push(b.lo)
    prob.push(remaining / total)
    remaining -= b.count
  }
  return { edges, prob }
}

// ---------------------------------------------------------------- scenarios

export interface ScenarioCell {
  value: number | null
  savedNum: number | null
  usingSaved: boolean
  disagrees: boolean
}

/** One scenario's value for a metric: a fresh recompute wins; the number
 *  saved with the scenario is the fallback while the recompute is pending
 *  or when it failed. */
export function scenarioCell(
  savedMetrics: Record<string, unknown> | undefined,
  fresh: Record<string, unknown> | 'failed' | undefined,
  metricId: string,
): ScenarioCell {
  const saved = savedMetrics?.[metricId]
  const savedNum = typeof saved === 'number' ? saved : null
  const freshNum =
    fresh && fresh !== 'failed' && typeof fresh[metricId] === 'number' ? (fresh[metricId] as number) : null
  const usingSaved = fresh === 'failed' || fresh === undefined
  const value = freshNum ?? (usingSaved ? savedNum : null)
  const disagrees =
    freshNum !== null && savedNum !== null && Math.abs(freshNum - savedNum) > Math.max(1e-9, Math.abs(freshNum) * 0.005)
  return { value, savedNum, usingSaved: usingSaved && savedNum !== null, disagrees }
}

/** Stable color slot for a newly compared scenario: the lowest slot (1..8)
 *  no other compared scenario holds, so colors follow the scenario, not its
 *  column position. */
export function nextFreeSlot(taken: readonly number[]): number {
  for (let s = 1; s <= 8; s++) if (!taken.includes(s)) return s
  return 8
}

/** Metrics grouped into one family per unit so each chart has one axis. */
export function metricFamilies<M extends { id: string; type: string }>(metrics: readonly M[]) {
  return {
    percent: metrics.filter((m) => m.type === 'percent'),
    multiple: metrics.filter((m) => m.type === 'multiple'),
  }
}

// -------------------------------------------------------------- deal inputs

/** J5 floating debt: the index path per month 1..months (a step function,
 *  current index before the first curve point — as the engine reads it), and
 *  the index the loan actually pays after the floor and, while in force, the
 *  cap. Null when the inputs aren't a floating loan with a current index. */
export function forwardCurvePath(values: Record<string, unknown>, months: number) {
  if (values.rateMode !== 'floating' || !finite(values.currentIndexPct) || months < 1) return null
  const current = values.currentIndexPct
  const floor = finite(values.floorPct) ? values.floorPct : null
  const strike = finite(values.rateCapStrikePct) ? values.rateCapStrikePct : 0
  const capTerm = finite(values.rateCapTermMonths) ? Math.trunc(values.rateCapTermMonths) : 0
  const capActive = strike > 0 && capTerm > 0
  const curve = (Array.isArray(values.forwardCurve) ? values.forwardCurve : [])
    .filter(
      (r): r is { month: number; indexPct: number } =>
        !!r && typeof r === 'object' && finite((r as { month?: unknown }).month) && finite((r as { indexPct?: unknown }).indexPct),
    )
    .map((r) => [Math.trunc(r.month), r.indexPct] as const)
    .sort((a, b) => a[0] - b[0])
  const index: number[] = []
  const effective: number[] = []
  for (let m = 1; m <= months; m++) {
    let v = current
    for (const [pm, pv] of curve) {
      if (pm <= m) v = pv
      else break
    }
    index.push(v)
    let e = floor !== null ? Math.max(v, floor) : v
    if (capActive && m <= capTerm) e = Math.min(e, strike)
    effective.push(e)
  }
  return {
    months: Array.from({ length: months }, (_, i) => i + 1),
    index,
    effective,
    floor,
    strike: capActive ? strike : null,
    /** The floor or cap changes what the loan pays somewhere on the path. */
    bites: effective.some((e, i) => Math.abs(e - index[i]) > 1e-12),
  }
}
