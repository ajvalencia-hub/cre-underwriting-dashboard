import type { Deal } from '../types/deal'

/** J11: per-deal key dates. Stored in the deal's inputs blob
 *  (inputs.criticalDates) so they ride autosave, history, export/import,
 *  and the HTML share with zero extra plumbing. */
export interface CriticalDate {
  id: string
  label: string
  date: string // YYYY-MM-DD
  notes?: string
}

export const PRESET_LABELS = [
  'LOI expiry',
  'DD end',
  'Financing contingency',
  'Closing',
] as const

export const UPCOMING_WINDOW_DAYS = 14

export function readCriticalDates(inputs: Record<string, unknown> | undefined): CriticalDate[] {
  const raw = inputs?.criticalDates
  if (!Array.isArray(raw)) return []
  return raw.filter(
    (r): r is CriticalDate =>
      Boolean(r) && typeof r === 'object' && typeof (r as CriticalDate).date === 'string',
  )
}

/** Days from `today` to the date (negative = overdue). Date-only math in
 *  local time — deadlines are calendar days, not instants. */
export function daysUntil(date: string, today: Date): number {
  const [y, m, d] = date.split('-').map(Number)
  if (!y || !m || !d) return Number.NaN
  const target = new Date(y, m - 1, d)
  const base = new Date(today.getFullYear(), today.getMonth(), today.getDate())
  return Math.round((target.getTime() - base.getTime()) / 86_400_000)
}

export type DateStatus = 'overdue' | 'upcoming' | 'later'

export function dateStatus(date: string, today: Date): DateStatus {
  const days = daysUntil(date, today)
  if (Number.isNaN(days)) return 'later'
  if (days < 0) return 'overdue'
  if (days <= UPCOMING_WINDOW_DAYS) return 'upcoming'
  return 'later'
}

export function sortByDate(rows: CriticalDate[]): CriticalDate[] {
  return [...rows].sort((a, b) => a.date.localeCompare(b.date))
}

export interface DeadlineEntry {
  dealId: string
  dealName: string
  row: CriticalDate
  days: number
  status: DateStatus
}

/** The pipeline strip: overdue first (most overdue first), then the next
 *  14 days in ascending order. Later dates are excluded. */
export function upcomingDeadlines(deals: Deal[], today: Date): DeadlineEntry[] {
  const entries: DeadlineEntry[] = []
  for (const deal of deals) {
    for (const row of readCriticalDates(deal.inputs as Record<string, unknown>)) {
      const status = dateStatus(row.date, today)
      if (status === 'later') continue
      entries.push({
        dealId: deal.id,
        dealName: deal.name,
        row,
        days: daysUntil(row.date, today),
        status,
      })
    }
  }
  return entries.sort((a, b) => a.days - b.days)
}
