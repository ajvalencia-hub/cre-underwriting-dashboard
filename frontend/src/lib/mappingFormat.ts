import type { MappingEntry } from '../types/mapping'

export function describeMapping(entry: MappingEntry | undefined): string {
  if (!entry) return '— unmapped —'
  if (entry.target === 'namedRange') return `Named range: ${entry.ref}`
  if (entry.target === 'cell') return entry.ref ?? '—'
  if (entry.target === 'table') return `Anchor ${entry.anchor} (${entry.sheet ?? ''})`
  return '—'
}
