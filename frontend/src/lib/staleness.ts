// Pipeline staleness (H7). Pure for unit testing. A deal is "stale" when it
// hasn't been touched in 14 days and "very stale" at 30 — but only while it
// is in an active stage; closed/dead deals are supposed to sit still.

import type { DealStatus } from '../types/deal'

export const STALE_DAYS = 14
export const VERY_STALE_DAYS = 30

const TERMINAL_STATUSES: DealStatus[] = ['closed', 'dead']

export function daysSince(iso: string, nowMs: number = Date.now()): number {
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return 0
  return Math.max(0, Math.floor((nowMs - then) / 86_400_000))
}

export interface StalenessBadge {
  label: string
  tone: 'amber' | 'red'
}

export function stalenessBadge(
  status: DealStatus,
  updatedAt: string,
  nowMs: number = Date.now(),
): StalenessBadge | null {
  if (TERMINAL_STATUSES.includes(status)) return null
  const days = daysSince(updatedAt, nowMs)
  if (days >= VERY_STALE_DAYS) return { label: `stale ${days}d`, tone: 'red' }
  if (days >= STALE_DAYS) return { label: `stale ${days}d`, tone: 'amber' }
  return null
}

export function relativeAge(iso: string, nowMs: number = Date.now()): string {
  const days = daysSince(iso, nowMs)
  if (days === 0) return 'today'
  if (days === 1) return 'yesterday'
  if (days < 30) return `${days}d ago`
  if (days < 365) return `${Math.floor(days / 30)}mo ago`
  return `${Math.floor(days / 365)}y ago`
}
