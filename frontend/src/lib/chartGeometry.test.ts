import { describe, expect, it } from 'vitest'
import { barRects, compactValue, linePath } from './chartGeometry'

describe('linePath', () => {
  it('returns empty for no values', () => {
    expect(linePath([], 100, 40)).toBe('')
  })

  it('renders a flat series as a mid-height line', () => {
    const path = linePath([5, 5, 5], 100, 40)
    expect(path).toBe('M0.00,20.00 L50.00,20.00 L100.00,20.00')
  })

  it('renders a single point as a full-width horizontal line', () => {
    expect(linePath([7], 100, 40)).toBe('M0,20.00 L100,20.00')
  })

  it('scales min to the bottom and max to the top with padding', () => {
    const path = linePath([0, 10], 100, 46, 3)
    // min -> height - pad = 43, max -> pad = 3
    expect(path).toBe('M0.00,43.00 L100.00,3.00')
  })
})

describe('barRects', () => {
  it('returns empty for no values', () => {
    expect(barRects([], 100, 40)).toEqual([])
  })

  it('anchors bars to the floor and scales the max to full height', () => {
    const rects = barRects([1, 4], 100, 40, 0)
    expect(rects).toHaveLength(2)
    expect(rects[1].h).toBeCloseTo(40)
    expect(rects[1].y).toBeCloseTo(0)
    expect(rects[0].h).toBeCloseTo(10)
    expect(rects[0].y).toBeCloseTo(30)
  })

  it('keeps a minimum visible bar height', () => {
    const rects = barRects([0, 1000], 100, 40)
    expect(rects[0].h).toBeGreaterThanOrEqual(1)
  })
})

describe('compactValue', () => {
  it('formats counts, money and percents', () => {
    expect(compactValue(1_234_567, 'count')).toBe('1.23M')
    expect(compactValue(84_200, 'money')).toBe('$84k')
    expect(compactValue(2_741, 'money')).toBe('$2,741')
    expect(compactValue(0.0525, 'percent')).toBe('5.3%')
  })
})
