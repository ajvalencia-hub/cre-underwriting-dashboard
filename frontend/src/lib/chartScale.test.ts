import { describe, expect, it } from 'vitest'
import {
  bandScale,
  finiteExtent,
  isFiniteNumber,
  linearScale,
  median,
  niceStep,
  niceTicks,
  quantile,
} from './chartScale'

describe('isFiniteNumber / finiteExtent', () => {
  it('rejects null, NaN and infinities', () => {
    expect([1, 0, -2].every(isFiniteNumber)).toBe(true)
    expect([null, undefined, NaN, Infinity, -Infinity, '1'].some(isFiniteNumber)).toBe(false)
  })
  it('skips non-finite values and returns null for none', () => {
    expect(finiteExtent([3, null, NaN, -1, 7, Infinity])).toEqual([-1, 7])
    expect(finiteExtent([])).toBeNull()
    expect(finiteExtent([NaN, null])).toBeNull()
  })
})

describe('linearScale', () => {
  it('maps and inverts', () => {
    const s = linearScale([0, 100], [0, 500])
    expect(s(50)).toBe(250)
    expect(s.invert(250)).toBe(50)
  })
  it('supports an inverted (SVG y) range', () => {
    const s = linearScale([0, 10], [200, 0])
    expect(s(0)).toBe(200)
    expect(s(10)).toBe(0)
    expect(s(2.5)).toBe(150)
  })
  it('maps a degenerate domain to the range midpoint, never NaN', () => {
    const s = linearScale([5, 5], [0, 100])
    expect(s(5)).toBe(50)
    expect(s(99)).toBe(50)
    expect(Number.isNaN(s.invert(10))).toBe(false)
  })
})

describe('niceStep', () => {
  it('snaps to the nearest 1 / 2 / 5 × 10^k (no 2.5)', () => {
    expect(niceStep(1)).toBe(1)
    expect(niceStep(1.3)).toBe(1)
    expect(niceStep(1.6)).toBe(2)
    expect(niceStep(2.5)).toBe(2)
    expect(niceStep(3.1)).toBe(2)
    expect(niceStep(3.3)).toBe(5)
    expect(niceStep(4)).toBe(5)
    expect(niceStep(8)).toBe(10)
    expect(niceStep(180)).toBe(200)
    expect(niceStep(0.012)).toBeCloseTo(0.01)
  })
  it('falls back to 1 for zero / negative / non-finite', () => {
    expect(niceStep(0)).toBe(1)
    expect(niceStep(-3)).toBe(1)
    expect(niceStep(NaN)).toBe(1)
  })
})

describe('niceTicks', () => {
  it('expands to whole steps and lists clean ticks', () => {
    const t = niceTicks(3, 97, 5)
    expect(t.domain).toEqual([0, 100])
    expect(t.ticks).toEqual([0, 20, 40, 60, 80, 100])
    expect(t.step).toBe(20)
  })
  it('keeps the domain tight (6.1M max -> 8M top, not 10M)', () => {
    const t = niceTicks(-4_200_000, 6_100_000, 4, { includeZero: true })
    expect(t.domain).toEqual([-6_000_000, 8_000_000])
    expect(t.step).toBe(2_000_000)
  })
  it('handles money-sized values', () => {
    const t = niceTicks(1_234_567, 4_870_000, 4)
    expect(t.ticks[0]).toBeLessThanOrEqual(1_234_567)
    expect(t.ticks[t.ticks.length - 1]).toBeGreaterThanOrEqual(4_870_000)
    expect(t.ticks.every((v) => v % 500_000 === 0)).toBe(true)
  })
  it('produces float-clean percent ticks (no 0.30000000000000004)', () => {
    const t = niceTicks(0.061, 0.187, 5)
    for (const v of t.ticks) expect(String(v).length).toBeLessThan(7)
    expect(t.ticks).toEqual([0.06, 0.08, 0.1, 0.12, 0.14, 0.16, 0.18, 0.2])
  })
  it('keeps small decimal steps exact', () => {
    expect(niceTicks(0, 0.1, 4).ticks).toEqual([0, 0.02, 0.04, 0.06, 0.08, 0.1])
    expect(niceTicks(0.0012, 0.0049, 3).ticks).toEqual([0.001, 0.002, 0.003, 0.004, 0.005])
  })
  it('spans negative-to-positive through zero', () => {
    const t = niceTicks(-420, 910, 5)
    expect(t.ticks).toContain(0)
    expect(t.domain[0]).toBeLessThanOrEqual(-420)
    expect(t.domain[1]).toBeGreaterThanOrEqual(910)
  })
  it('includes zero on request', () => {
    expect(niceTicks(40, 90, 5, { includeZero: true }).domain[0]).toBe(0)
    expect(niceTicks(-90, -40, 5, { includeZero: true }).domain[1]).toBe(0)
  })
  it('pads a flat range so the value sits inside the axis', () => {
    const t = niceTicks(1.25, 1.25, 5)
    expect(t.domain[0]).toBeLessThan(1.25)
    expect(t.domain[1]).toBeGreaterThan(1.25)
    expect(niceTicks(0, 0).domain).toEqual([0, 1])
    expect(niceTicks(-5, -5).domain[1]).toBeGreaterThan(-5)
  })
  it('falls back to [0, 1] on non-finite input and fixes swapped bounds', () => {
    expect(niceTicks(NaN, NaN).domain).toEqual([0, 1])
    expect(niceTicks(NaN, 8).domain[1]).toBeGreaterThanOrEqual(8)
    expect(niceTicks(10, 0).domain).toEqual([0, 10])
  })
  it('never emits -0', () => {
    const t = niceTicks(-1, 1, 4)
    expect(t.ticks.some((v) => Object.is(v, -0))).toBe(false)
  })
})

describe('bandScale', () => {
  it('splits the range into equal bands', () => {
    const b = bandScale(4, [0, 400])
    expect(b.band).toBe(100)
    expect(b.start(2)).toBe(200)
    expect(b.center(0)).toBe(50)
  })
  it('finds and clamps the band under a pixel', () => {
    const b = bandScale(4, [0, 400])
    expect(b.indexAt(250)).toBe(2)
    expect(b.indexAt(-10)).toBe(0)
    expect(b.indexAt(9999)).toBe(3)
    expect(bandScale(0, [0, 400]).indexAt(10)).toBe(-1)
  })
})

describe('median / quantile', () => {
  it('ignores non-finite values', () => {
    expect(median([3, null, 1, NaN, 2])).toBe(2)
    expect(median([4, 1, 3, 2])).toBe(2.5)
    expect(Number.isNaN(median([]))).toBe(true)
  })
  it('interpolates like PERCENTILE.INC', () => {
    expect(quantile([1, 2, 3, 4, 5], 0.25)).toBe(2)
    expect(quantile([10, 20], 0.9)).toBeCloseTo(19)
    expect(quantile([7], 0.9)).toBe(7)
  })
})
