// Pipeline saved views + CSV export (I10). Run 6 wave 2 adds column sort
// with a direction (incl. the metric columns), stage / staleness / tag
// filters — all captured by a saved view, with older saved views upgraded
// on load (normalizeView). Pure/injectable for unit tests.

import { ALL_STAGES, dealTypeOf, stageRank, TERMINAL_STAGES } from './dealStages'
import { daysSince, stalenessBadge } from './staleness'
import { hasAllTags } from './tags'
import type { StorageLike } from './safeStorage'
import type { Deal, DealStatus } from '../types/deal'

/** The per-deal numbers the pipeline can show (and sort by). */
export const METRIC_SORT_KEYS = ['totalCost', 'equity', 'leveredIrr', 'equityMultiple', 'yield'] as const
export type MetricSortKey = (typeof METRIC_SORT_KEYS)[number]

export type PipelineSortKey = 'stage' | 'updated' | 'name' | 'staleness' | 'market' | MetricSortKey
export type SortDir = 'asc' | 'desc'
export type StalenessLevel = 'fresh' | 'stale' | 'critical'

export const STALENESS_LEVELS: StalenessLevel[] = ['fresh', 'stale', 'critical']
export const STALENESS_LABELS: Record<StalenessLevel, string> = {
  fresh: 'Fresh',
  stale: 'Stale',
  critical: 'Critical',
}

/** The direction a column starts in when first clicked. Numbers start
 *  biggest-first (the usual question is "which deal has the most…"). */
export const DEFAULT_SORT_DIR: Record<PipelineSortKey, SortDir> = {
  stage: 'asc',
  updated: 'desc',
  name: 'asc',
  staleness: 'desc',
  market: 'asc',
  totalCost: 'desc',
  equity: 'desc',
  leveredIrr: 'desc',
  equityMultiple: 'desc',
  yield: 'desc',
}

export interface PipelineViewState {
  marketFilter: string
  sortKey: PipelineSortKey
  sortDir: SortDir
  showTerminal: boolean
  stageFilter: DealStatus[]
  stalenessFilter: StalenessLevel[]
  tagFilter: string[]
  /** The optional metric columns shown; absent = leave the current choice. */
  columns?: string[]
}

export interface PipelineView extends PipelineViewState {
  name: string
}

export const DEFAULT_VIEW_STATE: PipelineViewState = {
  marketFilter: '',
  sortKey: 'stage',
  sortDir: 'asc',
  showTerminal: false,
  stageFilter: [],
  stalenessFilter: [],
  tagFilter: [],
}

const STORAGE_KEY = 'cre.pipelineViews'
const SORT_KEYS = Object.keys(DEFAULT_SORT_DIR) as PipelineSortKey[]

function stringList(raw: unknown): string[] {
  return Array.isArray(raw) ? raw.filter((v): v is string => typeof v === 'string') : []
}

/** Coerce a stored view — possibly saved before sort direction / filters /
 *  columns existed ({name, marketFilter, sortKey, showTerminal}) — into the
 *  full shape; null when it is not a view at all. */
export function normalizeView(raw: unknown): PipelineView | null {
  if (typeof raw !== 'object' || raw === null) return null
  const v = raw as Record<string, unknown>
  if (typeof v.name !== 'string' || v.name.length === 0) return null
  const sortKey = SORT_KEYS.includes(v.sortKey as PipelineSortKey)
    ? (v.sortKey as PipelineSortKey)
    : DEFAULT_VIEW_STATE.sortKey
  const view: PipelineView = {
    name: v.name,
    marketFilter: typeof v.marketFilter === 'string' ? v.marketFilter : '',
    sortKey,
    // Old views sorted "updated" newest-first and everything else ascending
    // — exactly the per-key defaults.
    sortDir: v.sortDir === 'asc' || v.sortDir === 'desc' ? v.sortDir : DEFAULT_SORT_DIR[sortKey],
    showTerminal: v.showTerminal === true,
    stageFilter: stringList(v.stageFilter).filter((s): s is DealStatus => ALL_STAGES.includes(s as DealStatus)),
    stalenessFilter: stringList(v.stalenessFilter).filter((s): s is StalenessLevel =>
      STALENESS_LEVELS.includes(s as StalenessLevel),
    ),
    tagFilter: stringList(v.tagFilter),
  }
  if (Array.isArray(v.columns)) view.columns = stringList(v.columns)
  return view
}

export function loadViews(storage: StorageLike): PipelineView[] {
  try {
    const raw = storage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.map(normalizeView).filter((v): v is PipelineView => v !== null)
  } catch {
    return [] // corrupted storage is not an error state worth surfacing
  }
}

export function saveView(storage: StorageLike, view: PipelineView): PipelineView[] {
  const views = loadViews(storage).filter((v) => v.name !== view.name) // upsert by name
  views.push(view)
  storage.setItem(STORAGE_KEY, JSON.stringify(views))
  return views
}

export function deleteView(storage: StorageLike, name: string): PipelineView[] {
  const views = loadViews(storage).filter((v) => v.name !== name)
  storage.setItem(STORAGE_KEY, JSON.stringify(views))
  return views
}

/** Clicking a column header: a new column starts in its default direction,
 *  the current column flips. */
export function toggleSort(
  current: { sortKey: PipelineSortKey; sortDir: SortDir },
  key: PipelineSortKey,
): { sortKey: PipelineSortKey; sortDir: SortDir } {
  if (current.sortKey !== key) return { sortKey: key, sortDir: DEFAULT_SORT_DIR[key] }
  return { sortKey: key, sortDir: current.sortDir === 'asc' ? 'desc' : 'asc' }
}

export function dealMarket(deal: Pick<Deal, 'inputs'>): string {
  const market = deal.inputs?.market
  return typeof market === 'string' ? market : ''
}

/** fresh / stale (amber) / critical (red), from the per-stage thresholds. */
export function stalenessLevel(status: DealStatus, updatedAt: string, nowMs: number = Date.now()): StalenessLevel {
  const badge = stalenessBadge(status, updatedAt, nowMs)
  if (!badge) return 'fresh'
  return badge.tone === 'red' ? 'critical' : 'stale'
}

export type PipelineFilters = Pick<
  PipelineViewState,
  'marketFilter' | 'showTerminal' | 'stageFilter' | 'stalenessFilter' | 'tagFilter'
>

/** Every filter AND-ed: terminal stages, stage, staleness, tags (a deal must
 *  carry every selected tag), then the market-or-name text. */
export function filterDeals<T extends Deal>(
  deals: readonly T[],
  filters: PipelineFilters,
  nowMs: number = Date.now(),
): T[] {
  const needle = filters.marketFilter.trim().toLowerCase()
  return deals.filter((deal) => {
    if (!filters.showTerminal && TERMINAL_STAGES.includes(deal.status)) return false
    if (filters.stageFilter.length > 0 && !filters.stageFilter.includes(deal.status)) return false
    if (
      filters.stalenessFilter.length > 0 &&
      !filters.stalenessFilter.includes(stalenessLevel(deal.status, deal.updatedAt, nowMs))
    ) {
      return false
    }
    if (!hasAllTags(deal, filters.tagFilter)) return false
    if (!needle) return true
    return dealMarket(deal).toLowerCase().includes(needle) || deal.name.toLowerCase().includes(needle)
  })
}

/** Staleness rank: level first, then age — so "most stale" is a total order
 *  even inside one level. Terminal stages are always fresh (rank 0). */
function stalenessRank(deal: Deal, nowMs: number): number {
  const level = stalenessLevel(deal.status, deal.updatedAt, nowMs)
  const levelRank = level === 'critical' ? 2 : level === 'stale' ? 1 : 0
  return levelRank * 100_000 + (level === 'fresh' ? 0 : daysSince(deal.updatedAt, nowMs))
}

/** The number a metric column shows for a deal, or null (not computed /
 *  incomplete) — supplied by the page, which owns the metrics fetch. */
export type MetricAccessor = (deal: Deal, key: MetricSortKey) => number | null

function isMetricKey(key: PipelineSortKey): key is MetricSortKey {
  return (METRIC_SORT_KEYS as readonly string[]).includes(key)
}

export function sortDeals<T extends Deal>(
  deals: readonly T[],
  sortKey: PipelineSortKey,
  sortDir: SortDir,
  nowMs: number = Date.now(),
  metricOf?: MetricAccessor,
): T[] {
  const sign = sortDir === 'asc' ? 1 : -1
  const byUpdatedDesc = (a: Deal, b: Deal) => Date.parse(b.updatedAt) - Date.parse(a.updatedAt)
  return [...deals].sort((a, b) => {
    let primary = 0
    if (isMetricKey(sortKey)) {
      const va = metricOf?.(a, sortKey) ?? null
      const vb = metricOf?.(b, sortKey) ?? null
      // Deals without the number always sink to the bottom, either direction.
      if (va === null || vb === null) {
        if (va !== vb) return va === null ? 1 : -1
        return byUpdatedDesc(a, b)
      }
      primary = va - vb
    } else {
      switch (sortKey) {
        case 'name':
          primary = a.name.localeCompare(b.name)
          break
        case 'market':
          primary = dealMarket(a).localeCompare(dealMarket(b))
          break
        case 'updated':
          primary = Date.parse(a.updatedAt) - Date.parse(b.updatedAt)
          break
        case 'staleness':
          primary = stalenessRank(a, nowMs) - stalenessRank(b, nowMs)
          break
        case 'stage':
        default:
          primary = stageRank(a.status) - stageRank(b.status)
          break
      }
    }
    // Ties always fall back to most-recently-touched first, regardless of direction.
    return primary !== 0 ? sign * primary : byUpdatedDesc(a, b)
  })
}

export function applyPipelineView<T extends Deal>(
  deals: readonly T[],
  view: PipelineViewState,
  nowMs: number = Date.now(),
  metricOf?: MetricAccessor,
): T[] {
  return sortDeals(filterDeals(deals, view, nowMs), view.sortKey, view.sortDir, nowMs, metricOf)
}

/** The original three-knob signature (market text, sort key in its default
 *  direction, terminal toggle), kept for existing callers. */
export function applyView(
  deals: Deal[],
  marketFilter: string,
  sortKey: PipelineSortKey,
  showTerminal: boolean,
): Deal[] {
  return applyPipelineView(deals, {
    ...DEFAULT_VIEW_STATE,
    marketFilter,
    sortKey,
    sortDir: DEFAULT_SORT_DIR[sortKey],
    showTerminal,
  })
}

/** CSV of the CURRENT filtered/sorted view — what you see is what exports. */
export function pipelineToCsv(deals: Deal[], nowMs: number = Date.now()): string {
  const header = ['Name', 'Type', 'Market', 'Status', 'Last touched', 'Staleness', 'Tags']
  const lines = [header.join(',')]
  for (const deal of deals) {
    const market = dealMarket(deal)
    const badge = stalenessBadge(deal.status, deal.updatedAt, nowMs)
    lines.push(
      [
        `"${deal.name.replace(/"/g, '""')}"`,
        dealTypeOf(deal) ?? '',
        `"${market.replace(/"/g, '""')}"`,
        deal.status,
        deal.updatedAt,
        badge ? badge.label : '',
        `"${(deal.tags ?? []).join('; ').replace(/"/g, '""')}"`,
      ].join(','),
    )
  }
  return lines.join('\n')
}
