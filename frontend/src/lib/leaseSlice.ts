// Per-lease drill-down helpers (I8). Pure for unit testing. Slice vectors
// are OPERATING months 1..N (no close column, unlike statement series).

export interface RolloverEvent {
  expiryMonth: number
  commencementMonth: number
  startRentPsf: number
  renewalProbability: number
  downtimeMonths: number
}

export interface LeaseSlice {
  suiteId: string
  tenant: string
  sf: number
  recoveryType: string
  endDate: string
  scheduledRent: number[]
  freeRent: number[]
  downtimeLoss: number[]
  recoveries: number[]
  leasingCapital: number[]
  rolloverEvents: RolloverEvent[]
}

export const SLICE_ROWS: { key: keyof LeaseSlice & string; label: string }[] = [
  { key: 'scheduledRent', label: 'Scheduled rent' },
  { key: 'freeRent', label: 'Free rent' },
  { key: 'downtimeLoss', label: 'Downtime loss' },
  { key: 'recoveries', label: 'Recoveries' },
  { key: 'leasingCapital', label: 'TI / LC (below NOI)' },
]

/** Sum a monthly vector into year buckets (year 1 = months 1..12; a partial
 *  final year keeps its raw sum). */
export function annualize(vector: number[]): number[] {
  const years: number[] = []
  for (let start = 0; start < vector.length; start += 12) {
    years.push(vector.slice(start, start + 12).reduce((sum, v) => sum + v, 0))
  }
  return years
}

/** CSV of one lease slice, monthly or annual, header row + one row per
 *  series. Excel-safe: numbers unformatted, comma-delimited. */
export function sliceToCsv(slice: LeaseSlice, mode: 'monthly' | 'annual'): string {
  const vectors = SLICE_ROWS.map(({ key, label }) => ({
    label,
    values: mode === 'annual' ? annualize(slice[key] as number[]) : (slice[key] as number[]),
  }))
  const periods = vectors[0].values.length
  const header = [
    'Series',
    ...Array.from({ length: periods }, (_, i) =>
      mode === 'annual' ? `Year ${i + 1}` : `M${i + 1}`,
    ),
  ]
  const lines = [header.join(',')]
  for (const { label, values } of vectors) {
    lines.push([`"${label}"`, ...values.map((v) => v.toFixed(2))].join(','))
  }
  return lines.join('\n')
}
