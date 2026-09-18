import type { MappingEntry, MappingsById } from '../types/mapping'

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
