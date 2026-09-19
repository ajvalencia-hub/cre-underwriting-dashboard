import { describe, expect, it } from 'vitest'
import { parseSeed } from './monteCarloSeed'

describe('parseSeed', () => {
  it('blank means random', () => {
    expect(parseSeed('')).toEqual({ ok: true, seed: undefined })
    expect(parseSeed('   ')).toEqual({ ok: true, seed: undefined })
  })

  it('accepts non-negative integers', () => {
    expect(parseSeed('0')).toEqual({ ok: true, seed: 0 })
    expect(parseSeed(' 42 ')).toEqual({ ok: true, seed: 42 })
  })

  it('rejects junk, negatives, decimals and oversized values', () => {
    expect(parseSeed('abc').ok).toBe(false)
    expect(parseSeed('-1').ok).toBe(false)
    expect(parseSeed('1.5').ok).toBe(false)
    expect(parseSeed('1e3').ok).toBe(false)
    expect(parseSeed('99999999999999999999').ok).toBe(false)
  })
})
