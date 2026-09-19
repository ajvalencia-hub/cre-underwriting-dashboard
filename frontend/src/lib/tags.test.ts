import { describe, expect, it } from 'vitest'
import {
  MAX_TAGS,
  MAX_TAG_LENGTH,
  addTag,
  addTags,
  allTags,
  filterByTags,
  hasAllTags,
  normalizeTag,
  normalizeTags,
  parseTagInput,
  removeTag,
  toggleTag,
} from './tags'

describe('normalizeTag / normalizeTags (backend rules)', () => {
  it('trims and keeps case', () => {
    expect(normalizeTag('  Core Plus ')).toBe('Core Plus')
    expect(normalizeTag('')).toBe('')
  })

  it('drops blanks and dedupes case-insensitively keeping the first spelling', () => {
    expect(normalizeTags([' Core', '', 'core ', 'Miami'])).toEqual({ ok: true, tags: ['Core', 'Miami'] })
  })

  it('rejects an over-long tag instead of cutting it', () => {
    const result = normalizeTags(['x'.repeat(MAX_TAG_LENGTH + 1)])
    expect(result.ok).toBe(false)
    expect(normalizeTags(['x'.repeat(MAX_TAG_LENGTH)]).ok).toBe(true)
  })

  it('rejects more than the cap', () => {
    const result = normalizeTags(Array.from({ length: MAX_TAGS + 1 }, (_, i) => `t${i}`))
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error).toContain(String(MAX_TAGS))
  })
})

describe('parseTagInput', () => {
  it('splits on commas, semicolons and newlines', () => {
    expect(parseTagInput('core, miami;value-add\n  ')).toEqual(['core', 'miami', 'value-add'])
    expect(parseTagInput('  ')).toEqual([])
  })
})

describe('addTag / addTags / removeTag', () => {
  it('appends a trimmed tag', () => {
    expect(addTag([], ' Core ')).toEqual({ ok: true, tags: ['Core'] })
  })

  it('adds several typed at once, skipping ones already there', () => {
    expect(addTags(['core'], 'Core, miami, austin')).toEqual({ ok: true, tags: ['core', 'miami', 'austin'] })
  })

  it('rejects blanks, duplicates and the 21st tag', () => {
    expect(addTag([], '   ').ok).toBe(false)
    expect(addTag(['core'], 'CORE').ok).toBe(false)
    const full = Array.from({ length: MAX_TAGS }, (_, i) => `t${i}`)
    const result = addTag(full, 'one more')
    expect(result.ok).toBe(false)
    if (!result.ok) expect(result.error).toContain(String(MAX_TAGS))
  })

  it('removes case-insensitively, whatever spelling the server kept', () => {
    expect(removeTag(['core', 'miami'], ' Core')).toEqual(['miami'])
    expect(removeTag(['Core', 'miami'], 'core')).toEqual(['miami'])
  })
})

describe('allTags / filters', () => {
  const deals = [{ tags: ['core', 'miami'] }, { tags: ['Core'] }, { tags: undefined }, { tags: ['austin'] }]

  it('counts usage case-insensitively, most used first then alphabetical', () => {
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
    expect(hasAllTags({ tags: ['Core'] }, ['core'])).toBe(true)
  })

  it('toggleTag adds or removes from the selection', () => {
    expect(toggleTag([], 'core')).toEqual(['core'])
    expect(toggleTag(['core', 'miami'], 'CORE')).toEqual(['miami'])
  })
})
