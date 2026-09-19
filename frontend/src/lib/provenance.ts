// Where a Deal Inputs value came from, when the app filled it (roadmap #14).
// Stored beside the field values as inputs._provenance (the key the OM
// wizard already writes), so it rides autosave, history and export. A
// value the user types themselves has no entry: typing clears it.

export const PROVENANCE_KEY = '_provenance'

export interface SourceRef {
  doc?: string | null
  sheet?: string | null
  page?: number | null
  row?: number | null
}

export interface FieldProvenance {
  /** extraction | reviewed_proposal (OM wizard / Documents) | preset |
   *  goalSeek | quickScreen | agent (an approved Agent proposal). Unknown
   *  sources from older data still show. */
  source: string
  label?: string
  sourceRef?: SourceRef | null
  confidence?: number | null
  at?: string
}

export function readProvenance(values: Record<string, unknown>): Record<string, FieldProvenance> {
  const raw = values[PROVENANCE_KEY]
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {}
  const out: Record<string, FieldProvenance> = {}
  for (const [fieldId, entry] of Object.entries(raw as Record<string, unknown>)) {
    if (entry && typeof entry === 'object' && typeof (entry as FieldProvenance).source === 'string') {
      out[fieldId] = entry as FieldProvenance
    }
  }
  return out
}

/** `values` with each field in `entries` recorded as app-filled. */
export function recordProvenance(
  values: Record<string, unknown>,
  entries: Record<string, FieldProvenance>,
): Record<string, unknown> {
  if (Object.keys(entries).length === 0) return values
  return { ...values, [PROVENANCE_KEY]: { ...readProvenance(values), ...entries } }
}

/** The same entry for every field in a patch. */
export function sameSourceFor(fieldIds: string[], entry: FieldProvenance): Record<string, FieldProvenance> {
  return Object.fromEntries(fieldIds.map((id) => [id, entry]))
}

/** `values` without a provenance entry for `fieldId` (the user typed it). */
export function clearProvenance(values: Record<string, unknown>, fieldId: string): Record<string, unknown> {
  const current = readProvenance(values)
  if (!(fieldId in current)) return values
  const rest = { ...current }
  delete rest[fieldId]
  return { ...values, [PROVENANCE_KEY]: rest }
}

export function describeProvenance(p: FieldProvenance): string {
  const ref = p.sourceRef
  if (ref?.doc) {
    const where = [ref.sheet, ref.page != null ? `p.${ref.page}` : null, ref.row != null ? `row ${ref.row}` : null]
      .filter(Boolean)
      .join(' · ')
    return `from ${ref.doc}${where ? ` ${where}` : ''}`
  }
  switch (p.source) {
    case 'extraction':
    case 'reviewed_proposal':
      return 'from a document'
    case 'preset':
      return p.label ? `preset “${p.label}”` : 'from a preset'
    case 'goalSeek':
      return 'goal seek'
    case 'quickScreen':
      return 'from Quick Screen'
    case 'agent':
      return 'from the Underwriting Agent'
    default:
      return p.label ?? p.source
  }
}
