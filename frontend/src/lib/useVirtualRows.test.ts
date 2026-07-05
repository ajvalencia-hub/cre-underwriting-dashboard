import { describe, expect, it } from 'vitest'
import { computeWindow } from './useVirtualRows'

describe('computeWindow', () => {
  it('is empty for an empty list', () => {
    expect(computeWindow(0, 32, 0, 400)).toEqual({ start: 0, end: 0, padTop: 0, padBottom: 0 })
  })

  it('renders the whole list when it fits', () => {
    const w = computeWindow(10, 32, 0, 400)
    expect(w.start).toBe(0)
    expect(w.end).toBe(10)
    expect(w.padTop).toBe(0)
    expect(w.padBottom).toBe(0)
  })

  it('windows the middle of a long list with overscan and padding', () => {
    // 1000 rows x 32px, scrolled to row 500, 400px viewport, overscan 8
    const w = computeWindow(1000, 32, 500 * 32, 400, 8)
    expect(w.start).toBe(492)
    expect(w.end).toBe(500 + 13 + 8)
    expect(w.padTop).toBe(492 * 32)
    expect(w.padBottom).toBe((1000 - w.end) * 32)
    // padding + rendered rows always reconstruct the full scroll height
    expect(w.padTop + (w.end - w.start) * 32 + w.padBottom).toBe(1000 * 32)
  })

  it('clamps at the end of the list', () => {
    const w = computeWindow(100, 32, 99 * 32, 400)
    expect(w.end).toBe(100)
    expect(w.padBottom).toBe(0)
  })
})
