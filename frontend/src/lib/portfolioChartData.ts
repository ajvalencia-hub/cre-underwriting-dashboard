// Pure data shaping for the multi-deal charts (Portfolio, Pipeline, Compare,
// Comps). Rendering lives in components/portfolioCharts; nothing here
// formats for display beyond category labels, and no financial math is
// re-derived — every number comes from the engine/rollup/comp rows as-is.

import type { SeriesSlot } from '../components/charts/types'
import type { Comp, DealMetrics, PortfolioRollup } from './api'
import type { CompareColumn, CompareRow } from './compareMath'
import { ALL_STAGES, STAGE_LABELS, stagesFor, type DealType } from './dealStages'
import type { DealStatus } from '../types/deal'

const isNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

// ------------------------------------------------------------ shared

/** Dealflow -> fixed categorical slot, the same on every multi-deal chart
 *  (blue acquisitions / orange developments, matching the pipeline chips;
 *  aqua for legacy untyped deals). Color follows the dealflow, never rank. */
export const DEALFLOW_SLOT: Record<DealType | 'untyped', SeriesSlot> = {
  acquisition: 1,
  development: 2,
  untyped: 3,
}

export const DEALFLOW_LABEL: Record<DealType | 'untyped', string> = {
  acquisition: 'Acquisitions',
  development: 'Developments',
  untyped: 'Untyped',
}

export interface LabeledValue {
  label: string
  value: number
}

/** Sorted high -> low; beyond `max` bars the tail folds into one "Other"
 *  bar (top max-1 + Other), so a long list never needs a 9th row color or
 *  an unreadable chart. Non-finite values are dropped. */
export function foldTail(rows: readonly LabeledValue[], max = 8, otherLabel = 'Other'): LabeledValue[] {
  const clean = rows.filter((r) => isNum(r.value)).sort((a, b) => b.value - a.value)
  if (clean.length <= max) return clean
  const head = clean.slice(0, Math.max(1, max - 1))
  const tail = clean.slice(head.length)
  return [...head, { label: `${otherLabel} (${tail.length})`, value: tail.reduce((s, r) => s + r.value, 0) }]
}

// ------------------------------------------------------------ Portfolio

export interface ScatterSeriesData {
  key: string
  label: string
  slot: SeriesSlot
  points: { x: number; y: number; label: string }[]
}

/** Levered IRR (y) vs committed equity (x), one series per dealflow (≤3).
 *  Deals without an IRR are left out (they're counted in `missing`). */
export function irrVsEquitySeries(deals: PortfolioRollup['deals']): { series: ScatterSeriesData[]; missing: number } {
  const order: (DealType | 'untyped')[] = ['acquisition', 'development', 'untyped']
  let missing = 0
  const buckets = new Map<string, ScatterSeriesData['points']>()
  for (const d of deals) {
    if (!isNum(d.leveredIrr) || !isNum(d.equity)) {
      missing += 1
      continue
    }
    const type = d.dealType === 'acquisition' || d.dealType === 'development' ? d.dealType : 'untyped'
    const list = buckets.get(type) ?? []
    list.push({ x: d.equity, y: d.leveredIrr, label: d.name })
    buckets.set(type, list)
  }
  const series = order
    .filter((t) => (buckets.get(t)?.length ?? 0) > 0)
    .map((t) => ({ key: t, label: DEALFLOW_LABEL[t], slot: DEALFLOW_SLOT[t], points: buckets.get(t)! }))
  return { series, missing }
}

// ------------------------------------------------------------ Pipeline

export interface StageEquity {
  /** "Screening · 3" — registry order, stages with no shown deal omitted. */
  categories: string[]
  stages: DealStatus[]
  /** Summed committed equity per stage; null = no computable deal there. */
  values: (number | null)[]
  dealCount: number
  /** Deals whose metrics are incomplete / not loaded (not in any bar). */
  notComputed: number
  totalEquity: number
}

/** Equity by stage for one board, over exactly the deals the board shows.
 *  Stage order comes from the registry; a legacy stage (valid for the other
 *  flow) is appended in union order so the deal is still charted. */
export function stageEquity(
  type: DealType,
  deals: readonly { id: string; status: DealStatus }[],
  metrics: Record<string, DealMetrics> | null,
): StageEquity {
  const base = stagesFor(type)
  const legacy = ALL_STAGES.filter((s) => !base.includes(s))
  const order = [...base, ...legacy]
  const counts = new Map<DealStatus, number>()
  const equity = new Map<DealStatus, number>()
  let notComputed = 0
  for (const d of deals) {
    counts.set(d.status, (counts.get(d.status) ?? 0) + 1)
    const m = metrics?.[d.id]
    if (m && m.status === 'ok' && isNum(m.equity)) {
      equity.set(d.status, (equity.get(d.status) ?? 0) + m.equity)
    } else {
      notComputed += 1
    }
  }
  // Unknown statuses (not in the registry) still get a row, last.
  for (const s of counts.keys()) if (!order.includes(s)) order.push(s)
  const stages = order.filter((s) => (counts.get(s) ?? 0) > 0)
  const values = stages.map((s) => (equity.has(s) ? equity.get(s)! : null))
  return {
    categories: stages.map((s) => `${STAGE_LABELS[s] ?? s} · ${counts.get(s)}`),
    stages,
    values,
    dealCount: deals.length,
    notComputed,
    totalEquity: values.reduce<number>((sum, v) => sum + (v ?? 0), 0),
  }
}

// ------------------------------------------------------------ Compare

export type CompareFamilyKey = 'returns' | 'multiples' | 'money'

/** Headline metrics per unit family — one chart per family so a chart never
 *  mixes % with x with $ (one y-axis). Order = category order. */
export const COMPARE_FAMILIES: { key: CompareFamilyKey; title: string; unit: string; ids: string[] }[] = [
  {
    key: 'returns',
    title: 'Returns and yields',
    unit: 'Percent',
    ids: ['leveredIrr', 'unleveredIrr', 'avgCashOnCash', 'yieldOnCost', 'goingInCapRate'],
  },
  {
    key: 'multiples',
    title: 'Multiples and coverage',
    unit: 'Multiple (x)',
    ids: ['equityMultiple', 'unleveredEquityMultiple', 'minDscr', 'avgDscr'],
  },
  {
    key: 'money',
    title: 'Dollar outcomes',
    unit: 'Dollars',
    ids: ['totalProfit', 'npv', 'peakEquity'],
  },
]

/** Short axis labels (the table keeps the schema's full labels). */
export const COMPARE_SHORT_LABELS: Record<string, string> = {
  leveredIrr: 'Levered IRR',
  unleveredIrr: 'Unlevered IRR',
  avgCashOnCash: 'Avg cash-on-cash',
  yieldOnCost: 'Yield on cost',
  goingInCapRate: 'Going-in cap',
  equityMultiple: 'Equity multiple',
  unleveredEquityMultiple: 'Unlev. multiple',
  minDscr: 'Min DSCR',
  avgDscr: 'Avg DSCR',
  peakEquity: 'Peak equity',
  totalProfit: 'Total profit',
  npv: 'NPV',
}

/** A stable slot per selected deal: kept while the deal stays selected, the
 *  lowest free slot for a newcomer — so removing deal A never repaints B. */
export function assignCompareSlots(
  ids: readonly string[],
  prev: Readonly<Record<string, SeriesSlot>>,
): Record<string, SeriesSlot> {
  const next: Record<string, SeriesSlot> = {}
  const used = new Set<SeriesSlot>()
  for (const id of ids) {
    const s = prev[id]
    if (s && !used.has(s)) {
      next[id] = s
      used.add(s)
    }
  }
  for (const id of ids) {
    if (next[id]) continue
    const free = ([1, 2, 3, 4, 5, 6, 7, 8] as SeriesSlot[]).find((s) => !used.has(s)) ?? 8
    next[id] = free
    used.add(free)
  }
  return next
}

export function sameSlots(a: Readonly<Record<string, SeriesSlot>>, b: Readonly<Record<string, SeriesSlot>>): boolean {
  const ka = Object.keys(a)
  return ka.length === Object.keys(b).length && ka.every((k) => a[k] === b[k])
}

export interface CompareFamilyChart {
  key: CompareFamilyKey
  title: string
  unit: string
  /** 'percent' | 'multiple' | 'currency' — drives the formatter. */
  type: 'percent' | 'multiple' | 'currency'
  categories: string[]
  series: { key: string; label: string; slot: SeriesSlot; values: (number | null)[] }[]
  /** The table's own best-value picks (row.best), per charted metric. */
  best: { metric: string; deal: string }[]
}

const FAMILY_TYPE: Record<CompareFamilyKey, CompareFamilyChart['type']> = {
  returns: 'percent',
  multiples: 'multiple',
  money: 'currency',
}

/** Grouped-bar data per family from the SAME rows the comparison table
 *  renders (so values, n/a and "best" agree with the table). Only computed
 *  columns become series; a family with no charted metric is dropped. */
export function compareFamilyCharts(
  rows: readonly CompareRow[],
  columns: readonly CompareColumn[],
  slots: Readonly<Record<string, SeriesSlot>>,
): CompareFamilyChart[] {
  const byId = new Map(rows.map((r) => [r.metric.id, r]))
  const computed = columns.map((c, i) => ({ c, i })).filter(({ c }) => c.outputs)
  if (computed.length === 0) return []
  const out: CompareFamilyChart[] = []
  for (const fam of COMPARE_FAMILIES) {
    const famRows = fam.ids
      .map((id) => byId.get(id))
      .filter((r): r is CompareRow => !!r && computed.some(({ i }) => isNum(r.values[i])))
    if (famRows.length === 0) continue
    const short = COMPARE_SHORT_LABELS
    out.push({
      key: fam.key,
      title: fam.title,
      unit: fam.unit,
      type: FAMILY_TYPE[fam.key],
      categories: famRows.map((r) => short[r.metric.id] ?? r.metric.label),
      series: computed.map(({ c, i }) => ({
        key: c.dealId,
        label: c.name,
        slot: slots[c.dealId] ?? 1,
        values: famRows.map((r) => (isNum(r.values[i]) ? r.values[i] : null)),
      })),
      best: famRows
        .filter((r) => r.best !== null)
        .map((r) => ({ metric: short[r.metric.id] ?? r.metric.label, deal: columns[r.best!]?.name ?? '' })),
    })
  }
  return out
}

// ------------------------------------------------------------ Comps

export interface CompStripValue {
  value: number
  label: string
}

export type CompMetric = 'pricePerUnit' | 'pricePerSf' | 'capRatePct' | 'avgRent' | 'rentPerSf'

/** One comp metric (rent per SF derived as avgRent / avgSf). */
export function compMetric(comp: Comp, metric: CompMetric): number | null {
  if (metric === 'rentPerSf') {
    return isNum(comp.avgRent) && isNum(comp.avgSf) && comp.avgSf > 0 ? comp.avgRent / comp.avgSf : null
  }
  const v = comp[metric]
  return isNum(v) ? v : null
}

/** Finite values of one metric, labeled by comp name. Fewer than 2 -> []
 *  (a lone dot isn't a distribution; the chart shows its quiet empty state). */
export function compStripValues(comps: readonly Comp[], metric: CompMetric): CompStripValue[] {
  const vals = comps.flatMap((c) => {
    const v = compMetric(c, metric)
    return v === null ? [] : [{ value: v, label: c.name }]
  })
  return vals.length >= 2 ? vals : []
}

/** Points with both fields finite; fewer than 3 -> [] (no relationship to read). */
export function compScatterPoints(
  comps: readonly Comp[],
  x: (c: Comp) => number | null | undefined,
  y: (c: Comp) => number | null | undefined,
): { x: number; y: number; label: string }[] {
  const pts = comps.flatMap((c) => {
    const xv = x(c)
    const yv = y(c)
    return isNum(xv) && isNum(yv) ? [{ x: xv, y: yv, label: c.name }] : []
  })
  return pts.length >= 3 ? pts : []
}

/** The active deal's own numbers to mark on the comp charts ("your deal").
 *  Price metrics only for acquisitions (a development's land price per unit
 *  isn't comparable to a stabilized sale); rent from the unit mix (in-place,
 *  else market); cap = the deal's exit cap, the same comparison the Deal
 *  Inputs benchmark flag makes against the sale-comp median. */
export interface CompSubject {
  pricePerUnit?: number
  pricePerSf?: number
  capRatePct?: number
  avgRent?: number
  rentPerSf?: number
}

export function compSubjectFromValues(values: Record<string, unknown> | null | undefined): CompSubject {
  const subject: CompSubject = {}
  if (!values) return subject
  let units = 0
  let unitSf = 0
  let rentTotal = 0
  let rentUnits = 0
  let rentSfTotal = 0
  let rentSfUnits = 0
  if (Array.isArray(values.unitMix)) {
    for (const row of values.unitMix) {
      if (typeof row !== 'object' || row === null) continue
      const r = row as Record<string, unknown>
      const count = isNum(r.unitCount) && r.unitCount > 0 ? r.unitCount : 0
      if (count === 0) continue
      units += count
      const sf = isNum(r.avgSf) && r.avgSf > 0 ? r.avgSf : 0
      unitSf += count * sf
      const rent = isNum(r.inPlaceRent) && r.inPlaceRent > 0 ? r.inPlaceRent : isNum(r.marketRent) && r.marketRent > 0 ? r.marketRent : 0
      if (rent > 0) {
        rentTotal += count * rent
        rentUnits += count
        if (sf > 0) {
          rentSfTotal += count * rent
          rentSfUnits += count * sf
        }
      }
    }
  }
  if (rentUnits > 0) subject.avgRent = rentTotal / rentUnits
  if (rentSfUnits > 0) subject.rentPerSf = rentSfTotal / rentSfUnits
  if (values.dealType === 'acquisition') {
    const price = isNum(values.purchasePrice) && values.purchasePrice > 0 ? values.purchasePrice : 0
    const sf = isNum(values.rentableSf) && values.rentableSf > 0 ? values.rentableSf : unitSf
    if (price > 0 && units > 0) subject.pricePerUnit = price / units
    if (price > 0 && sf > 0) subject.pricePerSf = price / sf
  }
  if (isNum(values.exitCapRatePct) && values.exitCapRatePct > 0) subject.capRatePct = values.exitCapRatePct
  return subject
}
