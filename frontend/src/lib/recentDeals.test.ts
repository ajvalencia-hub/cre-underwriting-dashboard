import { describe, expect, it } from 'vitest'
import { RECENT_DEALS_KEY, loadRecent, parseRecent, pushRecent, recordRecent } from './recentDeals'

function memory(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial))
  return {
    get: (k: string) => data.get(k) ?? null,
    set: (k: string, v: string) => data.set(k, v),
  }
}

describe('pushRecent', () => {
  it('moves a revisited id to the front and caps the length', () => {
    expect(pushRecent(['a', 'b', 'c'], 'b')).toEqual(['b', 'a', 'c'])
    expect(pushRecent(['1', '2', '3'], '4', 3)).toEqual(['4', '1', '2'])
  })
})

describe('parseRecent', () => {
  it('tolerates junk', () => {
    expect(parseRecent(null)).toEqual([])
    expect(parseRecent('not json')).toEqual([])
    expect(parseRecent('{"a":1}')).toEqual([])
    expect(parseRecent('["x", 3, "y"]')).toEqual(['x', 'y'])
  })
})

describe('recordRecent', () => {
  it('persists the updated list', () => {
    const storage = memory({ [RECENT_DEALS_KEY]: '["a"]' })
    expect(recordRecent(storage, 'b')).toEqual(['b', 'a'])
    expect(loadRecent(storage)).toEqual(['b', 'a'])
  })
})
