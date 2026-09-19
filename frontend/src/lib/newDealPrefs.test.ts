import { describe, expect, it } from 'vitest'
import { NEW_DEAL_TYPE_KEY, defaultNewDealType, loadNewDealTypePref, saveNewDealTypePref } from './newDealPrefs'

function memoryStorage(initial: Record<string, string> = {}) {
  const data = { ...initial }
  return {
    getItem: (key: string) => (key in data ? data[key] : null),
    setItem: (key: string, value: string) => {
      data[key] = value
    },
  }
}

describe('new deal type preference', () => {
  it('defaults to ask and round-trips', () => {
    const storage = memoryStorage()
    expect(loadNewDealTypePref(storage)).toBe('ask')
    expect(defaultNewDealType(storage)).toBeNull()
    saveNewDealTypePref('development', storage)
    expect(loadNewDealTypePref(storage)).toBe('development')
    expect(defaultNewDealType(storage)).toBe('development')
  })

  it('ignores junk and a throwing store', () => {
    expect(loadNewDealTypePref(memoryStorage({ [NEW_DEAL_TYPE_KEY]: 'banana' }))).toBe('ask')
    const broken = {
      getItem: () => {
        throw new Error('SecurityError')
      },
      setItem: () => {
        throw new Error('SecurityError')
      },
    }
    expect(loadNewDealTypePref(broken)).toBe('ask')
    expect(() => saveNewDealTypePref('acquisition', broken)).not.toThrow()
  })
})
