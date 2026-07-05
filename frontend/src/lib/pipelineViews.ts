// Pipeline saved views + CSV export (I10). Pure/injectable for unit tests.

import { stalenessBadge } from './staleness'
import type { Deal, DealStatus } from '../types/deal'

export type PipelineSortKey = 'stage' | 'updated' | 'name'

export interface PipelineView {
  name: string
  marketFilter: string
  sortKey: PipelineSortKey
  showTerminal: boolean
}

const STORAGE_KEY = 'cre.pipelineViews'

interface StorageLike {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
}

export function loadViews(storage: StorageLike): PipelineView[] {
  try {
    const raw = storage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    return parsed.filter(
      (v): v is PipelineView =>
        typeof v === 'object' && v !== null && typeof v.name === 'string' && v.name.length > 0,
    )
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

const STATUS_ORDER: DealStatus[] = [
  'screening', 'underwriting', 'loi', 'under_contract', 'closed', 'dead',
]

export function applyView(
  deals: Deal[],
  marketFilter: string,
  sortKey: PipelineSortKey,
  showTerminal: boolean,
): Deal[] {
  const needle = marketFilter.trim().toLowerCase()
  const filtered = deals.filter((deal) => {
    if (!showTerminal && (deal.status === 'closed' || deal.status === 'dead')) return false
    if (!needle) return true
    const market = typeof deal.inputs?.market === 'string' ? deal.inputs.market : ''
    return market.toLowerCase().includes(needle) || deal.name.toLowerCase().includes(needle)
  })
  return [...filtered].sort((a, b) => {
    if (sortKey === 'name') return a.name.localeCompare(b.name)
    if (sortKey === 'updated') return Date.parse(b.updatedAt) - Date.parse(a.updatedAt)
    const stage = STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status)
    return stage !== 0 ? stage : Date.parse(b.updatedAt) - Date.parse(a.updatedAt)
  })
}

/** CSV of the CURRENT filtered/sorted view — what you see is what exports. */
export function pipelineToCsv(deals: Deal[], nowMs: number = Date.now()): string {
  const header = ['Name', 'Market', 'Status', 'Last touched', 'Staleness']
  const lines = [header.join(',')]
  for (const deal of deals) {
    const market = typeof deal.inputs?.market === 'string' ? deal.inputs.market : ''
    const badge = stalenessBadge(deal.status, deal.updatedAt, nowMs)
    lines.push(
      [
        `"${deal.name.replace(/"/g, '""')}"`,
        `"${market.replace(/"/g, '""')}"`,
        deal.status,
        deal.updatedAt,
        badge ? badge.label : '',
      ].join(','),
    )
  }
  return lines.join('\n')
}
