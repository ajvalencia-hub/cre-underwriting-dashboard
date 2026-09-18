import type { MappingEntry, MappingsById } from '../types/mapping'

export function describeMapping(entry: MappingEntry | undefined): string {
  if (!entry) return '— unmapped —'
  if (entry.target === 'namedRange') return `Named range: ${entry.ref}`
  if (entry.target === 'cell') return entry.ref ?? '—'
  if (entry.target === 'table') return `Anchor ${entry.anchor} (${entry.sheet ?? ''})`
  return '—'
}

function stableEntry(entry: MappingEntry): string {
  // `source` (auto/manual) doesn't change where a value lands.
  return JSON.stringify([entry.target, entry.ref ?? null, entry.anchor ?? null, entry.sheet ?? null, entry.columnOrder ?? null])
}

/** True when two mapping sets write every field to the same place. */
export function mappingsEqual(a: MappingsById, b: MappingsById): boolean {
  const keysA = Object.keys(a)
  if (keysA.length !== Object.keys(b).length) return false
  return keysA.every((id) => id in b && stableEntry(a[id]) === stableEntry(b[id]))
}
