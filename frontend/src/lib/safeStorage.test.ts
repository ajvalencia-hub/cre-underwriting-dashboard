import { describe, expect, it } from 'vitest'
import { createSafeStorage } from './safeStorage'

function memory() {
  const data = new Map<string, string>()
  return {
    getItem: (k: string) => (data.has(k) ? data.get(k)! : null),
    setItem: (k: string, v: string) => {
      data.set(k, v)
    },
    removeItem: (k: string) => {
      data.delete(k)
    },
  }
}

describe('createSafeStorage', () => {
  it('reads and writes through a working backing store', () => {
    const store = memory()
    const s = createSafeStorage(() => store)
    expect(s.get('a')).toBeNull()
    expect(s.set('a', '1')).toBe(true)
    expect(s.get('a')).toBe('1')
    expect(s.remove('a')).toBe(true)
    expect(s.get('a')).toBeNull()
  })

  it('returns null / false when resolving the store throws (SecurityError)', () => {
    const s = createSafeStorage(() => {
      throw new Error('SecurityError')
    })
    expect(s.get('a')).toBeNull()
    expect(s.set('a', '1')).toBe(false)
    expect(s.remove('a')).toBe(false)
  })

  it('swallows quota errors on write', () => {
    const s = createSafeStorage(() => ({
      getItem: () => null,
      setItem: () => {
        throw new Error('QuotaExceededError')
      },
    }))
    expect(s.set('a', '1')).toBe(false)
  })

  it('exposes StorageLike adapters', () => {
    const store = memory()
    const s = createSafeStorage(() => store)
    s.setItem('k', 'v')
    expect(s.getItem('k')).toBe('v')
    s.removeItem('k')
    expect(s.getItem('k')).toBeNull()
  })

  it('treats a missing store as empty', () => {
    const s = createSafeStorage(() => null)
    expect(s.get('x')).toBeNull()
    expect(s.set('x', 'y')).toBe(false)
  })
})
