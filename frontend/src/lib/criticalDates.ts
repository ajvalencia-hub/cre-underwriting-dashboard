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

/** Quick-add label presets per dealflow (stored labels stay free text).
 *  Untyped deals see the acquisition set — the app-wide historical default. */
export const PRESETS_BY_TYPE = {
  acquisition: ['LOI expiry', 'DD end', 'Financing contingency', 'Closing'],
  development: [
    'Feasibility deadline',
    'Land closing',
    'Permit approval',
    'Groundbreaking',
    'Certificate of occupancy',
    'Stabilization',
  ],
} as const

export const PRESET_LABELS = PRESETS_BY_TYPE.acquisition

export const UPCOMING_WINDOW_DAYS = 14

/** A row is only a date once it HAS a date (Run 6 B11): the editor adds rows
 *  with an empty date while the user picks one — those never reach the
 *  chips, the pipeline strip, or the deal's stored inputs. */
export function hasDate(row: Pick<CriticalDate, 'date'>): boolean {
  return typeof row.date === 'string' && row.date.trim() !== ''
}

export function readCriticalDates(inputs: Record<string, unknown> | undefined): CriticalDate[] {
  const raw = inputs?.criticalDates
  if (!Array.isArray(raw)) return []
  return raw.filter(
    (r): r is CriticalDate =>
      Boolean(r) &&
      typeof r === 'object' &&
      typeof (r as CriticalDate).date === 'string' &&
      hasDate(r as CriticalDate),
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

/** The deal's closing date from its critical dates, if any: "Closing"
 *  (acquisitions) first, then "Land closing" (developments), then any other
 *  label mentioning closing. Offered for analysisStartDate, never applied
 *  silently — it moves every lease date in the model. */
export function closingDateOf(rows: CriticalDate[]): string | null {
  const valid = rows.filter((r) => /^\d{4}-\d{2}-\d{2}$/.test(r.date))
  const byLabel = (test: (label: string) => boolean) =>
    valid.find((r) => test(r.label.trim().toLowerCase()))?.date ?? null
  return (
    byLabel((l) => l === 'closing') ??
    byLabel((l) => l === 'land closing') ??
    byLabel((l) => l.includes('closing'))
  )
}
