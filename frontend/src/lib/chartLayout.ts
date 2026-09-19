// Pure layout math for the chart kit (src/components/charts): bar slots,
// stacking with negatives, rounded data-end paths, hit-testing, tooltip
// placement and dot dodging. No DOM, no React — see chartLayout.test.ts.

import { isFiniteNumber } from './chartScale'

/** The fixed mark specs (dataviz skill, marks-and-anatomy). */
export const MARK = {
  /** Bars never thicker than this; the rest of the band is air. */
  barMaxThickness: 24,
  /** Rounded data-end radius; the baseline end stays square. */
  barRadius: 4,
  /** Surface-colored gap between touching fills (stack segments, grouped bars). */
  surfaceGap: 2,
  lineWidth: 2,
  /** Marker radius (8px dot). */
  markerRadius: 4,
  /** Surface ring around markers. */
  ringWidth: 2,
  /** Minimum hover/focus target, px. */
  hitMin: 24,
} as const

// ---------------------------------------------------------------- bars

export interface BarSlots {
  /** Thickness of each bar, px (≤ maxThickness, ≥ 1). */
  thickness: number
  /** Offset of bar i from the band start, px. */
  offsets: number[]
  /** Gap actually used between adjacent bars in a group (may shrink to 0 in tiny bands). */
  gap: number
}

/** Place `seriesCount` side-by-side bars inside one category band. Bars are
 *  capped at `maxThickness`, separated by the surface gap, and the group is
 *  centered; `fill` is the share of the band the group may use at most. */
export function groupedBarSlots(
  band: number,
  seriesCount: number,
  { maxThickness = MARK.barMaxThickness, gap = MARK.surfaceGap, fill = 0.8 } = {},
): BarSlots {
  const n = Math.max(1, Math.floor(seriesCount))
  const usable = Math.max(0, band * fill)
  let g = n > 1 ? gap : 0
  // In very tight bands drop the gap before the bars vanish.
  if (n > 1 && usable - (n - 1) * g < n) g = 0
  const thickness = Math.max(1, Math.min(maxThickness, (usable - (n - 1) * g) / n))
  const groupWidth = n * thickness + (n - 1) * g
  const lead = (band - groupWidth) / 2
  return { thickness, gap: g, offsets: Array.from({ length: n }, (_, i) => lead + i * (thickness + g)) }
}

export interface StackSegment {
  /** Series index this segment belongs to. */
  series: number
  value: number
  /** Value-space start (nearer the zero baseline) and end. */
  start: number
  end: number
  /** First segment on its side of the baseline (touches the baseline). */
  first: boolean
  /** Outermost segment on its side — the one that gets the rounded data-end. */
  outermost: boolean
}

/** Stack one category's series values. Positives stack up from 0, negatives
 *  stack down from 0, each side independently (so a mix never cancels into a
 *  misleading net bar). Null/NaN/0 values produce no segment. */
export function stackValues(values: readonly (number | null | undefined)[]): StackSegment[] {
  const segs: StackSegment[] = []
  let pos = 0
  let neg = 0
  let lastPos = -1
  let lastNeg = -1
  values.forEach((v, series) => {
    if (!isFiniteNumber(v) || v === 0) return
    if (v > 0) {
      segs.push({ series, value: v, start: pos, end: pos + v, first: pos === 0, outermost: false })
      pos += v
      lastPos = segs.length - 1
    } else {
      segs.push({ series, value: v, start: neg, end: neg + v, first: neg === 0, outermost: false })
      neg += v
      lastNeg = segs.length - 1
    }
  })
  if (lastPos >= 0) segs[lastPos].outermost = true
  if (lastNeg >= 0) segs[lastNeg].outermost = true
  return segs
}

/** [min, max] of the stacked totals across categories (always includes 0). */
export function stackExtent(rows: readonly (readonly (number | null | undefined)[])[]): [number, number] {
  let min = 0
  let max = 0
  for (const row of rows) {
    let pos = 0
    let neg = 0
    for (const v of row) {
      if (!isFiniteNumber(v)) continue
      if (v > 0) pos += v
      else neg += v
    }
    if (pos > max) max = pos
    if (neg < min) min = neg
  }
  return [min, max]
}

export interface PxSpan {
  /** Pixel position nearer the baseline. */
  from: number
  /** Pixel position of the data end. */
  to: number
}

/** Pull a stacked segment's baseline-side edge `gap` px away from the
 *  previous segment (the 2px surface gap). The first segment on each side
 *  keeps its edge on the baseline. Returns null when the gap swallows it. */
export function applyStackGap(span: PxSpan, first: boolean, gap = MARK.surfaceGap): PxSpan | null {
  const dir = Math.sign(span.to - span.from)
  if (dir === 0) return null
  if (first) return span
  const from = span.from + dir * gap
  if ((span.to - from) * dir <= 0) return null
  return { from, to: span.to }
}

export type DataEnd = 'top' | 'bottom' | 'left' | 'right'

/** SVG path for a bar whose data end (`end`) carries rounded corners of
 *  radius `r` while the baseline end stays square. Radius clamps to half the
 *  thickness and the full length, so tiny bars degrade gracefully. */
export function roundedBarPath(
  x: number,
  y: number,
  w: number,
  h: number,
  end: DataEnd,
  r: number = MARK.barRadius,
): string {
  if (!(w > 0) || !(h > 0)) return ''
  const f = (n: number) => Number(n.toFixed(2))
  const vertical = end === 'top' || end === 'bottom'
  const rr = Math.max(0, Math.min(r, vertical ? w / 2 : h / 2, vertical ? h : w))
  const x1 = x + w
  const y1 = y + h
  if (rr === 0) return `M${f(x)},${f(y)}H${f(x1)}V${f(y1)}H${f(x)}Z`
  const a = `A${f(rr)},${f(rr)} 0 0 1`
  switch (end) {
    case 'top':
      return `M${f(x)},${f(y1)}V${f(y + rr)}${a} ${f(x + rr)},${f(y)}H${f(x1 - rr)}${a} ${f(x1)},${f(y + rr)}V${f(y1)}Z`
    case 'bottom':
      return `M${f(x1)},${f(y)}V${f(y1 - rr)}${a} ${f(x1 - rr)},${f(y1)}H${f(x + rr)}${a} ${f(x)},${f(y1 - rr)}V${f(y)}Z`
    case 'right':
      return `M${f(x)},${f(y)}H${f(x1 - rr)}${a} ${f(x1)},${f(y + rr)}V${f(y1 - rr)}${a} ${f(x1 - rr)},${f(y1)}H${f(x)}Z`
    case 'left':
      return `M${f(x1)},${f(y1)}H${f(x + rr)}${a} ${f(x)},${f(y1 - rr)}V${f(y + rr)}${a} ${f(x + rr)},${f(y)}H${f(x1)}Z`
  }
}

/** Rect (x, y, w, h) for a bar spanning value-axis px [a, b] across the
 *  category axis at [c, c + thickness]. */
export function barRect(
  a: number,
  b: number,
  c: number,
  thickness: number,
  orientation: 'vertical' | 'horizontal',
): { x: number; y: number; w: number; h: number } {
  const lo = Math.min(a, b)
  const len = Math.abs(b - a)
  return orientation === 'vertical'
    ? { x: c, y: lo, w: thickness, h: len }
    : { x: lo, y: c, w: len, h: thickness }
}

/** Which side the rounded data-end is on for a bar going from `from` to `to`. */
export function dataEnd(from: number, to: number, orientation: 'vertical' | 'horizontal'): DataEnd {
  // SVG y grows downward: a vertical bar whose end is above its start points up.
  if (orientation === 'vertical') return to < from ? 'top' : 'bottom'
  return to > from ? 'right' : 'left'
}

// ---------------------------------------------------------------- hit testing

/** Index of the position nearest px (positions need not be sorted); -1 if none. */
export function nearestIndex(positions: readonly number[], px: number): number {
  let best = -1
  let bestD = Infinity
  positions.forEach((p, i) => {
    if (!isFiniteNumber(p)) return
    const d = Math.abs(p - px)
    if (d < bestD) {
      bestD = d
      best = i
    }
  })
  return best
}

/** Index of the point nearest (px, py) within maxDist px; -1 if none. */
export function nearestPoint(
  points: readonly { x: number; y: number }[],
  px: number,
  py: number,
  maxDist = Infinity,
): number {
  let best = -1
  let bestD = maxDist * maxDist
  points.forEach((p, i) => {
    const d = (p.x - px) ** 2 + (p.y - py) ** 2
    if (d <= bestD) {
      bestD = d
      best = i
    }
  })
  return best
}

/** Step a keyboard cursor through `count` items. Returns the new index, or
 *  -1 to clear (Escape) and `undefined` when the key isn't handled. */
export function stepIndex(current: number, count: number, key: string): number | undefined {
  if (count <= 0) return undefined
  switch (key) {
    case 'ArrowRight':
    case 'ArrowDown':
      return current < 0 ? 0 : Math.min(count - 1, current + 1)
    case 'ArrowLeft':
    case 'ArrowUp':
      return current < 0 ? count - 1 : Math.max(0, current - 1)
    case 'Home':
      return 0
    case 'End':
      return count - 1
    case 'Escape':
      return -1
    default:
      return undefined
  }
}

// ---------------------------------------------------------------- tooltip

/** Top-left for a tooltip of `size` anchored at `anchor`, kept wholly inside
 *  `box` (the chart's own box, so it's never clipped by a scrolling card).
 *  Prefers up-and-right of the anchor, flips left / below when it would
 *  overflow, then clamps. */
export function placeTooltip(
  anchor: { x: number; y: number },
  size: { width: number; height: number },
  box: { width: number; height: number },
  offset = 12,
): { left: number; top: number } {
  let left = anchor.x + offset
  let top = anchor.y - size.height - offset
  if (left + size.width > box.width) left = anchor.x - offset - size.width
  if (top < 0) top = anchor.y + offset
  left = Math.max(0, Math.min(left, box.width - size.width))
  top = Math.max(0, Math.min(top, box.height - size.height))
  return { left, top }
}

// ---------------------------------------------------------------- strip plot

/** Beeswarm-style vertical offsets for dots at the given x px, so dots of
 *  radius `r` (+ `pad`) don't overlap. Each dot takes the smallest |offset|
 *  that clears every earlier-placed neighbor, alternating above/below; offsets
 *  are clamped to ±maxOffset (overflowing dots may then overlap). Returned in
 *  input order. */
export function dodge(xs: readonly number[], r: number, maxOffset: number, pad = 1): number[] {
  const d = 2 * r + pad
  const order = xs.map((x, i) => ({ x, i })).sort((a, b) => a.x - b.x)
  const placed: { x: number; y: number }[] = []
  const out = new Array<number>(xs.length).fill(0)
  for (const { x, i } of order) {
    const near = placed.filter((p) => Math.abs(p.x - x) < d)
    let y = 0
    if (near.length > 0) {
      const collides = (cy: number) => near.some((p) => (p.x - x) ** 2 + (p.y - cy) ** 2 < d * d - 1e-9)
      // Candidate offsets: 0 and every tangent position to a neighbor.
      const cands = [0]
      for (const p of near) {
        const dy = Math.sqrt(Math.max(0, d * d - (p.x - x) ** 2))
        cands.push(p.y + dy, p.y - dy)
      }
      cands.sort((a, b) => Math.abs(a) - Math.abs(b) || b - a)
      y = cands.find((c) => !collides(c)) ?? 0
    }
    y = Math.max(-maxOffset, Math.min(maxOffset, y))
    placed.push({ x, y })
    out[i] = y
  }
  return out
}

/** Rough rendered width of a label (px) at the kit's 11px sans — used to
 *  decide whether a value label fits, never for layout that must be exact. */
export function approxTextWidth(text: string, fontSize = 11): number {
  return text.length * fontSize * 0.58
}

// ---------------------------------------------------------------- lines

export type MaybePoint = { x: number; y: number } | null

const r2 = (n: number) => Number(n.toFixed(2))

/** Line path that lifts the pen over missing points (null) instead of
 *  bridging them. '' when nothing is drawable. */
export function gappedLinePath(points: readonly MaybePoint[]): string {
  let d = ''
  let penUp = true
  for (const p of points) {
    if (!p || !isFiniteNumber(p.x) || !isFiniteNumber(p.y)) {
      penUp = true
      continue
    }
    d += `${d ? ' ' : ''}${penUp ? 'M' : 'L'}${r2(p.x)},${r2(p.y)}`
    penUp = false
  }
  return d
}

/** Area wash down to `baseY` for each unbroken run of ≥2 points. */
export function gappedAreaPath(points: readonly MaybePoint[], baseY: number): string {
  const runs: { x: number; y: number }[][] = [[]]
  for (const p of points) {
    if (!p || !isFiniteNumber(p.x) || !isFiniteNumber(p.y)) {
      if (runs[runs.length - 1].length > 0) runs.push([])
    } else runs[runs.length - 1].push(p)
  }
  return runs
    .filter((run) => run.length >= 2)
    .map((run) => {
      const first = run[0]
      const last = run[run.length - 1]
      const top = run.map((p) => `L${r2(p.x)},${r2(p.y)}`).join(' ')
      return `M${r2(first.x)},${r2(baseY)} ${top} L${r2(last.x)},${r2(baseY)} Z`
    })
    .join(' ')
}

/** Points with no drawn neighbor (a lone value between gaps) — a line can't
 *  show them, so the chart draws a marker instead. Returns their indices. */
export function isolatedIndices(points: readonly MaybePoint[]): number[] {
  const ok = (i: number) => {
    const p = points[i]
    return !!p && isFiniteNumber(p.x) && isFiniteNumber(p.y)
  }
  const out: number[] = []
  for (let i = 0; i < points.length; i++) if (ok(i) && !ok(i - 1) && !ok(i + 1)) out.push(i)
  return out
}

/** Show every k-th category label so labels of ~labelWidth px don't collide. */
export function labelStride(count: number, available: number, labelWidth: number, minGap = 8): number {
  if (count <= 0 || !(available > 0)) return 1
  const per = available / count
  return Math.max(1, Math.ceil((labelWidth + minGap) / per))
}

/** Shorten a label with an ellipsis so it fits ~maxPx (approximate). */
export function truncateLabel(text: string, maxPx: number, fontSize = 11): string {
  if (approxTextWidth(text, fontSize) <= maxPx) return text
  const chars = Math.max(1, Math.floor(maxPx / (fontSize * 0.58)) - 1)
  return `${text.slice(0, chars).trimEnd()}…`
}
