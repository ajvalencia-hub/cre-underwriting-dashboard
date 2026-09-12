import { describe, expect, it } from 'vitest'
import {
  MAX_TAGS,
  addTag,
  allTags,
  filterByTags,
  hasAllTags,
  normalizeTag,
  removeTag,
  toggleTag,
} from './tags'

describe('normalizeTag', () => {
  it('trims, collapses whitespace and lower-cases', () => {
    expect(normalizeTag('  Core   Plus ')).toBe('core plus')
    expect(normalizeTag('')).toBe('')
  })

  it('caps the length', () => {
    expect(normalizeTag('x'.repeat(80))).toHaveLength(40)
  })
})

describe('addTag / removeTag', () => {
  it('appends a normalised tag', () => {
    expect(addTag([], ' Core ')).toEqual({ ok: true, tags: ['core'] })
  })

  it('rejects blanks, duplicates and the 21st tag', () => {
    expect(addTag([], '   ').ok).toBe(false)
    expect(addTag(['core'], 'CORE').ok).toBe(false)
    const full = Array.from({ length: MAX_TAGS }, (_, i) => `t${i}`)
    const result = addTag(full, 'one more')
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error).toContain(String(MAX_TAGS))
  })

  it('removes by normalised name, whatever spelling the server kept', () => {
    expect(removeTag(['core', 'miami'], ' Core')).toEqual(['miami'])
    expect(removeTag(['Core', 'miami'], 'core')).toEqual(['miami'])
  })
})

describe('allTags / filters', () => {
  const deals = [
    { tags: ['core', 'miami'] },
    { tags: ['core'] },
    { tags: undefined },
    { tags: ['austin'] },
  ]

  it('counts usage, most used first then alphabetical', () => {
    expect(allTags(deals)).toEqual([
      { tag: 'core', count: 2 },
      { tag: 'austin', count: 1 },
      { tag: 'miami', count: 1 },
    ])
  })

  it('AND semantics: every selected tag must be present', () => {
    expect(filterByTags(deals, [])).toHaveLength(4)
    expect(filterByTags(deals, ['core'])).toHaveLength(2)
    expect(filterByTags(deals, ['core', 'miami'])).toHaveLength(1)
    expect(hasAllTags({ tags: undefined }, ['core'])).toBe(false)
    expect(hasAllTags({ tags: ['Core'] }, ['core'])).toBe(true) // server-kept spelling
  })

  it('toggleTag adds or removes from the selection', () => {
    expect(toggleTag([], 'core')).toEqual(['core'])
    expect(toggleTag(['core', 'miami'], 'core')).toEqual(['miami'])
  })
})
