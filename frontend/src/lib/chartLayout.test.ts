import { describe, expect, it } from 'vitest'
import {
  MARK,
  applyStackGap,
  barRect,
  dataEnd,
  dodge,
  gappedAreaPath,
  gappedLinePath,
  isolatedIndices,
  labelStride,
  truncateLabel,
  groupedBarSlots,
  nearestIndex,
  nearestPoint,
  placeTooltip,
  roundedBarPath,
  stackExtent,
  stackValues,
  stepIndex,
} from './chartLayout'

describe('groupedBarSlots', () => {
  it('caps a single bar at 24px and centers it in a wide band', () => {
    const s = groupedBarSlots(100, 1)
    expect(s.thickness).toBe(24)
    expect(s.offsets[0]).toBe(38)
  })
  it('separates grouped bars by exactly the 2px surface gap', () => {
    const s = groupedBarSlots(120, 3)
    expect(s.gap).toBe(MARK.surfaceGap)
    expect(s.offsets[1] - (s.offsets[0] + s.thickness)).toBeCloseTo(2)
    expect(s.offsets[2] - (s.offsets[1] + s.thickness)).toBeCloseTo(2)
    // group is centered
    const groupEnd = s.offsets[2] + s.thickness
    expect(s.offsets[0]).toBeCloseTo(120 - groupEnd)
  })
  it('thins bars in narrow bands without exceeding the band', () => {
    const s = groupedBarSlots(30, 2)
    expect(s.thickness).toBeLessThan(24)
    expect(s.offsets[1] + s.thickness).toBeLessThanOrEqual(30)
    expect(s.offsets[0]).toBeGreaterThanOrEqual(0)
  })
  it('drops the gap before the bars vanish in tiny bands', () => {
    const s = groupedBarSlots(4, 3)
    expect(s.gap).toBe(0)
    expect(s.thickness).toBeGreaterThanOrEqual(1)
  })
})

describe('stackValues / stackExtent', () => {
  it('stacks positives up and negatives down independently', () => {
    const segs = stackValues([10, -4, 5, -6])
    expect(segs.map((s) => [s.series, s.start, s.end])).toEqual([
      [0, 0, 10],
      [1, 0, -4],
      [2, 10, 15],
      [3, -4, -10],
    ])
    expect(segs.map((s) => s.first)).toEqual([true, true, false, false])
    expect(segs.map((s) => s.outermost)).toEqual([false, false, true, true])
  })
  it('skips null, NaN and zero values', () => {
    const segs = stackValues([null, NaN, 0, 3])
    expect(segs).toHaveLength(1)
    expect(segs[0]).toMatchObject({ series: 3, start: 0, end: 3, first: true, outermost: true })
  })
  it('returns no segments for an all-empty category', () => {
    expect(stackValues([null, undefined])).toEqual([])
  })
  it('computes the extent of stacked totals across categories, always including 0', () => {
    expect(stackExtent([[10, -4, 5], [2, 2, -9], [null, NaN, 1]])).toEqual([-9, 15])
    expect(stackExtent([[3, 4]])).toEqual([0, 7])
    expect(stackExtent([])).toEqual([0, 0])
  })
})

describe('applyStackGap', () => {
  it('keeps the first segment on the baseline', () => {
    expect(applyStackGap({ from: 200, to: 150 }, true)).toEqual({ from: 200, to: 150 })
  })
  it('pulls later segments 2px away from the previous one (upward bar)', () => {
    expect(applyStackGap({ from: 150, to: 100 }, false)).toEqual({ from: 148, to: 100 })
  })
  it('works downward and horizontally too', () => {
    expect(applyStackGap({ from: 220, to: 260 }, false)).toEqual({ from: 222, to: 260 })
    expect(applyStackGap({ from: 50, to: 90 }, false, 2)).toEqual({ from: 52, to: 90 })
  })
  it('drops segments the gap would swallow', () => {
    expect(applyStackGap({ from: 100, to: 99 }, false)).toBeNull()
    expect(applyStackGap({ from: 100, to: 100 }, true)).toBeNull()
  })
})

describe('roundedBarPath', () => {
  it('rounds only the data end (top) and keeps the baseline square', () => {
    const p = roundedBarPath(10, 20, 20, 100, 'top')
    // starts at the square bottom-left corner on the baseline
    expect(p.startsWith('M10,120V24A4,4')).toBe(true)
    expect(p).toContain('H26A4,4')
    expect(p.endsWith('V120Z')).toBe(true)
    expect((p.match(/A/g) ?? []).length).toBe(2)
  })
  it('rounds the bottom end for a negative column', () => {
    const p = roundedBarPath(0, 100, 20, 50, 'bottom')
    expect(p.startsWith('M20,100V146')).toBe(true)
  })
  it('rounds the right / left ends for horizontal bars', () => {
    expect(roundedBarPath(0, 0, 100, 20, 'right').startsWith('M0,0H96A4,4')).toBe(true)
    expect(roundedBarPath(0, 0, 100, 20, 'left').startsWith('M100,20H4A4,4')).toBe(true)
  })
  it('clamps the radius on tiny bars', () => {
    const p = roundedBarPath(0, 0, 4, 1.5, 'top')
    expect(p).toContain('A1.5,1.5')
    const thin = roundedBarPath(0, 0, 2, 50, 'top')
    expect(thin).toContain('A1,1')
  })
  it('draws a square rect with radius 0 and nothing for empty bars', () => {
    expect(roundedBarPath(0, 0, 10, 10, 'top', 0)).toBe('M0,0H10V10H0Z')
    expect(roundedBarPath(0, 0, 0, 10, 'top')).toBe('')
    expect(roundedBarPath(0, 0, 10, NaN, 'top')).toBe('')
  })
})

describe('barRect / dataEnd', () => {
  it('builds vertical and horizontal rects from value-axis px', () => {
    expect(barRect(200, 120, 30, 24, 'vertical')).toEqual({ x: 30, y: 120, w: 24, h: 80 })
    expect(barRect(50, 10, 5, 12, 'horizontal')).toEqual({ x: 10, y: 5, w: 40, h: 12 })
  })
  it('points the data end away from the baseline', () => {
    expect(dataEnd(200, 120, 'vertical')).toBe('top')
    expect(dataEnd(200, 260, 'vertical')).toBe('bottom')
    expect(dataEnd(50, 90, 'horizontal')).toBe('right')
    expect(dataEnd(50, 10, 'horizontal')).toBe('left')
  })
})

describe('hit testing', () => {
  it('nearestIndex snaps to the closest position and skips NaN', () => {
    expect(nearestIndex([0, 50, 100], 70)).toBe(1)
    expect(nearestIndex([0, 50, 100], 80)).toBe(2)
    expect(nearestIndex([NaN, 50], 0)).toBe(1)
    expect(nearestIndex([], 5)).toBe(-1)
  })
  it('nearestPoint respects the max distance', () => {
    const pts = [
      { x: 0, y: 0 },
      { x: 100, y: 100 },
    ]
    expect(nearestPoint(pts, 90, 95)).toBe(1)
    expect(nearestPoint(pts, 50, 50, 24)).toBe(-1)
    expect(nearestPoint(pts, 10, 10, 24)).toBe(0)
  })
  it('stepIndex moves, wraps to ends, and clears on Escape', () => {
    expect(stepIndex(-1, 5, 'ArrowRight')).toBe(0)
    expect(stepIndex(-1, 5, 'ArrowLeft')).toBe(4)
    expect(stepIndex(4, 5, 'ArrowRight')).toBe(4)
    expect(stepIndex(0, 5, 'ArrowUp')).toBe(0)
    expect(stepIndex(2, 5, 'Home')).toBe(0)
    expect(stepIndex(2, 5, 'End')).toBe(4)
    expect(stepIndex(2, 5, 'Escape')).toBe(-1)
    expect(stepIndex(2, 5, 'a')).toBeUndefined()
    expect(stepIndex(0, 0, 'ArrowRight')).toBeUndefined()
  })
})

describe('placeTooltip', () => {
  const box = { width: 400, height: 200 }
  const size = { width: 100, height: 40 }
  it('prefers up-and-right of the anchor', () => {
    expect(placeTooltip({ x: 100, y: 100 }, size, box)).toEqual({ left: 112, top: 48 })
  })
  it('flips left near the right edge', () => {
    expect(placeTooltip({ x: 350, y: 100 }, size, box).left).toBe(238)
  })
  it('flips below near the top edge', () => {
    expect(placeTooltip({ x: 100, y: 10 }, size, box).top).toBe(22)
  })
  it('clamps inside the box on every side', () => {
    const p = placeTooltip({ x: 395, y: 195 }, size, box)
    expect(p.left + size.width).toBeLessThanOrEqual(box.width)
    expect(p.top + size.height).toBeLessThanOrEqual(box.height)
    const q = placeTooltip({ x: 5, y: 5 }, { width: 380, height: 40 }, box)
    expect(q.left).toBeGreaterThanOrEqual(0)
    expect(q.left + 380).toBeLessThanOrEqual(box.width)
  })
  it('pins to 0,0 when the tooltip is larger than the box', () => {
    expect(placeTooltip({ x: 50, y: 50 }, { width: 500, height: 300 }, box)).toEqual({ left: 0, top: 0 })
  })
})

describe('dodge', () => {
  it('leaves isolated dots on the center line', () => {
    expect(dodge([0, 100, 200], 4, 20)).toEqual([0, 0, 0])
  })
  it('separates coincident dots by at least one diameter', () => {
    const ys = dodge([50, 50, 50], 4, 40, 1)
    const sorted = [...ys].sort((a, b) => a - b)
    expect(sorted[1] - sorted[0]).toBeGreaterThanOrEqual(9 - 1e-6)
    expect(sorted[2] - sorted[1]).toBeGreaterThanOrEqual(9 - 1e-6)
    expect(ys).toContain(0)
  })
  it('never lets placed dots overlap within the band', () => {
    const xs = [10, 12, 13, 15, 16, 17, 30, 31]
    const ys = dodge(xs, 4, 100, 1)
    for (let i = 0; i < xs.length; i++)
      for (let j = i + 1; j < xs.length; j++)
        expect(Math.hypot(xs[i] - xs[j], ys[i] - ys[j])).toBeGreaterThanOrEqual(9 - 1e-6)
  })
  it('clamps offsets to the band', () => {
    const ys = dodge(new Array(20).fill(5), 4, 12)
    expect(Math.max(...ys.map(Math.abs))).toBeLessThanOrEqual(12)
  })
})

describe('gappedLinePath / gappedAreaPath / isolatedIndices', () => {
  const pts = [{ x: 0, y: 10 }, { x: 10, y: 20 }, null, { x: 30, y: 5 }, { x: 40, y: 6 }, null, { x: 60, y: 1 }]
  it('lifts the pen over gaps', () => {
    expect(gappedLinePath(pts)).toBe('M0,10 L10,20 M30,5 L40,6 M60,1')
    expect(gappedLinePath([null, null])).toBe('')
    expect(gappedLinePath([{ x: 0, y: NaN }, { x: 1, y: 1 }])).toBe('M1,1')
  })
  it('closes one area per unbroken run of 2+ points', () => {
    const d = gappedAreaPath(pts, 100)
    expect(d).toBe('M0,100 L0,10 L10,20 L10,100 Z M30,100 L30,5 L40,6 L40,100 Z')
    expect(gappedAreaPath([{ x: 0, y: 1 }], 100)).toBe('')
  })
  it('finds lone points a line cannot draw', () => {
    expect(isolatedIndices(pts)).toEqual([6])
    expect(isolatedIndices([{ x: 0, y: 0 }])).toEqual([0])
  })
})

describe('labelStride', () => {
  it('shows every label when there is room', () => {
    expect(labelStride(5, 500, 30)).toBe(1)
  })
  it('thins labels on crowded axes', () => {
    expect(labelStride(120, 600, 30)).toBe(8)
  })
  it('is safe on empty or zero-width axes', () => {
    expect(labelStride(0, 500, 30)).toBe(1)
    expect(labelStride(10, 0, 30)).toBe(1)
  })
})

describe('truncateLabel', () => {
  it('keeps short labels and ellipsizes long ones within the budget', () => {
    expect(truncateLabel('Rent', 100)).toBe('Rent')
    const t = truncateLabel('Exit cap rate sensitivity driver', 60)
    expect(t.endsWith('…')).toBe(true)
    expect(t.length).toBeLessThan(12)
  })
})
