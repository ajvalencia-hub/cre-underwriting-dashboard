import { describe, expect, it } from 'vitest'
import { flattenGroups, nextIndex } from './searchNav'
import type { SearchGroup } from './api'

const GROUPS: SearchGroup[] = [
  { kind: 'deals', items: [{ id: 'd1', title: 'Alpha', subtitle: '' }, { id: 'd2', title: 'Beta', subtitle: '' }] },
  { kind: 'notes', items: [{ id: 'n1', title: 'a note', subtitle: '' }] },
]

describe('flattenGroups', () => {
  it('preserves group order then item order', () => {
    expect(flattenGroups(GROUPS).map((i) => i.id)).toEqual(['d1', 'd2', 'n1'])
  })
  it('handles empty', () => {
    expect(flattenGroups([])).toEqual([])
  })
})

describe('nextIndex', () => {
  it('advances and wraps as a ring', () => {
    expect(nextIndex(0, 1, 3)).toBe(1)
    expect(nextIndex(2, 1, 3)).toBe(0) // wrap forward
    expect(nextIndex(0, -1, 3)).toBe(2) // wrap backward
  })
  it('returns -1 when there is nothing to select', () => {
    expect(nextIndex(0, 1, 0)).toBe(-1)
  })
  it('recovers from an out-of-range current index', () => {
    expect(nextIndex(-1, 1, 3)).toBe(0)
  })
})
