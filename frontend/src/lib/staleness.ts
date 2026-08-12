// Pipeline staleness (H7, per-stage thresholds since the dealflow split).
// Pure for unit testing. Thresholds come from the stage registry: the
// default is 14d amber / 30d red, but long-lived development stages
// (entitlements, construction, …) are relaxed so they don't badge red for
// the entire life of a normal project. Terminal stages (closed, stabilized,
// dead) never badge — those deals are supposed to sit still.

import { TERMINAL_STAGES, stalenessThresholds } from './dealStages'
import type { DealStatus } from '../types/deal'

export const STALE_DAYS = 14
export const VERY_STALE_DAYS = 30

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
  if (TERMINAL_STAGES.includes(status)) return null
  const { stale, veryStale } = stalenessThresholds(status)
  const days = daysSince(updatedAt, nowMs)
  if (days >= veryStale) return { label: `stale ${days}d`, tone: 'red' }
  if (days >= stale) return { label: `stale ${days}d`, tone: 'amber' }
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
