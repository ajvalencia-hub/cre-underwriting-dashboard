// Pure helpers for applying a proposed (extracted) unit mix onto the deal's
// existing unit-mix rows. No aggregation math here — the backend proposes,
// the user reviews/edits, this only reshapes.

export interface UnitMixRow {
  unitType: string
  unitCount: number | null
  avgSf: number | null
  inPlaceRent: number | null
  marketRent: number | null
}

export interface ProposedUnitMixRow extends UnitMixRow {
  occupiedCount: number | null
  occupancyPct: number | null
  sourceRowCount: number | null
}

export interface UnitMixProposal {
  rows: ProposedUnitMixRow[]
  groupedBy: 'label' | 'bedBath'
  warnings: string[]
}

/** Strip review-only metadata down to the schema's unitMix columns. */
export function toSchemaRows(rows: ProposedUnitMixRow[]): UnitMixRow[] {
  return rows.map((row) => ({
    unitType: row.unitType,
    unitCount: row.unitCount,
    avgSf: row.avgSf,
    inPlaceRent: row.inPlaceRent,
    marketRent: row.marketRent,
  }))
}

function normalizeType(label: unknown): string {
  return String(label ?? '').trim().toLowerCase()
}

export function isNonEmptyUnitMix(value: unknown): value is Record<string, unknown>[] {
  return Array.isArray(value) && value.length > 0
}

/**
 * merge: existing rows whose unitType matches a proposed row (case- and
 * whitespace-insensitive) are replaced by the proposed version; unmatched
 * existing rows are kept in place; proposed types not present get appended.
 * replace: the proposal becomes the whole table.
 */
export interface ProposedLeaseRow {
  tenant: string
  suiteId: string
  sf: number | null
  startDate: string | null
  endDate: string | null
  baseRentPsfAnnual: number | null
  escalationType: string
  escalationValue: number
  escalationMonths: number
  recoveryType: string
  recoveryValue: number
  freeRentMonths: number
}

export interface CommercialLeaseProposal {
  rows: ProposedLeaseRow[]
  warnings: string[]
}

function leaseKey(row: { suiteId?: unknown; tenant?: unknown }): string {
  const suite = String(row.suiteId ?? '').trim().toLowerCase()
  return suite || String(row.tenant ?? '').trim().toLowerCase()
}

/** Same semantics as mergeUnitMix, keyed on suiteId (tenant as fallback). */
export function mergeCommercialLeases(
  existing: Record<string, unknown>[],
  proposed: ProposedLeaseRow[],
  mode: 'replace' | 'merge',
): Record<string, unknown>[] {
  if (mode === 'replace') return proposed as unknown as Record<string, unknown>[]
  const byKey = new Map(proposed.map((row) => [leaseKey(row), row]))
  const consumed = new Set<string>()
  const merged = existing.map((row) => {
    const key = leaseKey(row)
    const replacement = byKey.get(key)
    if (replacement && key) {
      consumed.add(key)
      return replacement as unknown as Record<string, unknown>
    }
    return row
  })
  for (const row of proposed) {
    if (!consumed.has(leaseKey(row))) merged.push(row as unknown as Record<string, unknown>)
  }
  return merged
}

export function mergeUnitMix(
  existing: Record<string, unknown>[],
  proposed: ProposedUnitMixRow[],
  mode: 'replace' | 'merge',
): UnitMixRow[] {
  const proposedRows = toSchemaRows(proposed)
  if (mode === 'replace') return proposedRows

  const byType = new Map(proposedRows.map((row) => [normalizeType(row.unitType), row]))
  const consumed = new Set<string>()
  const merged: UnitMixRow[] = existing.map((row) => {
    const key = normalizeType(row.unitType)
    const replacement = byType.get(key)
    if (replacement) {
      consumed.add(key)
      return replacement
    }
    return row as unknown as UnitMixRow
  })
  for (const row of proposedRows) {
    if (!consumed.has(normalizeType(row.unitType))) merged.push(row)
  }
  return merged
}
