// Derives the benchmark "subject" (what the deal claims) from the Deal
// Inputs form values. Pure + framework-free for unit testing. Context only:
// nothing here writes back into the form.

export interface BenchmarkSubject {
  avgRentMonthly?: number
  bedroomMix?: { bedrooms: number; count: number }[]
  rentGrowthPct?: number
  expenseRatioPct?: number
  exitCapRatePct?: number
}

const EXPENSE_DOLLAR_FIELDS = [
  'realEstateTaxes',
  'insurance',
  'utilities',
  'repairsMaintenance',
  'payroll',
  'generalAdmin',
  'replacementReserves',
]

function num(values: Record<string, unknown>, key: string): number | undefined {
  const v = values[key]
  return typeof v === 'number' && Number.isFinite(v) ? v : undefined
}

function bedroomsFromUnitType(unitType: unknown): number | undefined {
  if (typeof unitType !== 'string') return undefined
  const match = unitType.match(/(\d)\s*(bd|br|bed)/i)
  if (!match) return /studio|eff/i.test(unitType) ? 0 : undefined
  return Math.min(3, Number(match[1]))
}

export function deriveBenchmarkSubject(values: Record<string, unknown>): BenchmarkSubject {
  const subject: BenchmarkSubject = {}

  const unitMix = values.unitMix
  if (Array.isArray(unitMix)) {
    let totalRent = 0
    let totalUnits = 0
    const mixByBedrooms = new Map<number, number>()
    for (const row of unitMix) {
      if (typeof row !== 'object' || row === null) continue
      const record = row as Record<string, unknown>
      const count = typeof record.unitCount === 'number' ? record.unitCount : 0
      const rent =
        typeof record.inPlaceRent === 'number'
          ? record.inPlaceRent
          : typeof record.marketRent === 'number'
            ? record.marketRent
            : 0
      if (count > 0 && rent > 0) {
        totalRent += count * rent
        totalUnits += count
      }
      const bedrooms = bedroomsFromUnitType(record.unitType)
      if (count > 0 && bedrooms !== undefined) {
        mixByBedrooms.set(bedrooms, (mixByBedrooms.get(bedrooms) ?? 0) + count)
      }
    }
    if (totalUnits > 0) subject.avgRentMonthly = totalRent / totalUnits
    if (mixByBedrooms.size > 0) {
      subject.bedroomMix = [...mixByBedrooms.entries()].map(([bedrooms, count]) => ({
        bedrooms,
        count,
      }))
    }
  }

  const rentGrowth = num(values, 'rentGrowthPct')
  if (rentGrowth !== undefined && values.rentGrowthMode !== 'flat') {
    subject.rentGrowthPct = rentGrowth
  }

  const gpr = num(values, 'grossPotentialRent')
  if (gpr && gpr > 0) {
    const vacancy = num(values, 'vacancyPct') ?? 0
    const creditLoss = num(values, 'creditLossPct') ?? 0
    const otherIncome = num(values, 'otherIncome') ?? 0
    const egi = gpr * (1 - vacancy) * (1 - creditLoss) + otherIncome
    if (egi > 0) {
      const fixed = EXPENSE_DOLLAR_FIELDS.reduce((sum, f) => sum + (num(values, f) ?? 0), 0)
      const managementFee = (num(values, 'managementFeePct') ?? 0) * egi
      const total = fixed + managementFee
      if (total > 0) subject.expenseRatioPct = total / egi
    }
  }

  const exitCap = num(values, 'exitCapRatePct')
  if (exitCap && exitCap > 0) subject.exitCapRatePct = exitCap

  return subject
}
