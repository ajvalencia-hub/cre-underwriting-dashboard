import { describe, expect, it } from 'vitest'
import { createLatestGuard } from './latest'

describe('createLatestGuard', () => {
  it('only the newest token is current', () => {
    const guard = createLatestGuard()
    const a = guard.next()
    const b = guard.next()
    const c = guard.next()
    expect(guard.isCurrent(a)).toBe(false)
    expect(guard.isCurrent(b)).toBe(false)
    expect(guard.isCurrent(c)).toBe(true)
  })

  it('invalidate retires the outstanding token', () => {
    const guard = createLatestGuard()
    const a = guard.next()
    guard.invalidate()
    expect(guard.isCurrent(a)).toBe(false)
  })

  it('resolves out-of-order fetches to the last requested value', async () => {
    const guard = createLatestGuard()
    let shown = ''
    const request = (value: string, delay: number) => {
      const token = guard.next()
      return new Promise<void>((resolve) =>
        setTimeout(() => {
          if (guard.isCurrent(token)) shown = value
          resolve()
        }, delay),
      )
    }
    await Promise.all([request('A', 5), request('B', 30), request('C', 10)])
    expect(shown).toBe('C')
  })
})
