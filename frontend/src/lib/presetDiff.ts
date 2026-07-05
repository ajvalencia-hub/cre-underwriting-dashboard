// Preset apply preview (H8). Pure for unit testing: given the current form
// values and a preset's values, produce the row-by-row diff the user
// confirms before anything is applied.

export interface PresetDiffRow {
  fieldId: string
  current: unknown
  proposed: unknown
  changed: boolean
}

function equal(a: unknown, b: unknown): boolean {
  if (typeof a === 'number' && typeof b === 'number') {
    return Math.abs(a - b) < 1e-12
  }
  return a === b || (a == null && b == null)
}

export function presetDiff(
  current: Record<string, unknown>,
  presetValues: Record<string, unknown>,
): PresetDiffRow[] {
  return Object.entries(presetValues)
    .filter(([, proposed]) => proposed !== undefined && proposed !== null)
    .map(([fieldId, proposed]) => ({
      fieldId,
      current: current[fieldId],
      proposed,
      changed: !equal(current[fieldId], proposed),
    }))
}

/** The subset of a preset the user left checked, as a form-values patch. */
export function selectedChanges(
  rows: PresetDiffRow[],
  selected: Set<string>,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {}
  for (const row of rows) {
    if (row.changed && selected.has(row.fieldId)) patch[row.fieldId] = row.proposed
  }
  return patch
}
