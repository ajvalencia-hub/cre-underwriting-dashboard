import { formatValue } from './formatValue'
import { presetDiff } from './presetDiff'
import { flattenFields } from './schemaFields'
import type { InputSchema } from '../types/schema'

const hasValue = (v: unknown) => v !== undefined && v !== null && v !== ''

/** The values `next` would change among those the user already has, one
 *  "• Label: old → new" line each. `replaceAll` means fields missing from
 *  `next` get cleared (a scenario load), not kept (a merge). Empty when
 *  there's nothing to ask about. */
export function describeInputChanges(
  schema: InputSchema,
  current: Record<string, unknown>,
  next: Record<string, unknown>,
  replaceAll: boolean,
): string[] {
  const overwrites = presetDiff(current, next).filter((row) => row.changed && hasValue(row.current))
  const cleared = replaceAll ? Object.keys(current).filter((id) => hasValue(current[id]) && !hasValue(next[id])) : []
  if (overwrites.length === 0 && cleared.length === 0) return []
  const byId = new Map(flattenFields(schema).map((f) => [f.id, f]))
  return [
    ...overwrites.map((row) => {
      const field = byId.get(row.fieldId)
      return `• ${field?.label ?? row.fieldId}: ${formatValue(field, row.current)} → ${formatValue(field, row.proposed)}`
    }),
    ...cleared.map((id) => {
      const field = byId.get(id)
      return `• ${field?.label ?? id}: ${formatValue(field, current[id])} → (cleared)`
    }),
  ]
}

/** The confirm prompt for those lines: the first 12, then a count. */
export function inputChangesPrompt(what: string, lines: string[]): string {
  const shown = lines.slice(0, 12).join('\n')
  const more = lines.length > 12 ? `\n…and ${lines.length - 12} more` : ''
  return `${what} changes ${lines.length} value(s) already in Deal Inputs:\n\n${shown}${more}\n\nContinue?`
}
