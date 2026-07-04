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
