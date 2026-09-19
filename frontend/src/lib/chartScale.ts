// Pure scale + tick math for the chart kit (src/components/charts). No DOM,
// no React: everything here is unit-tested in chartScale.test.ts.

export type Domain = [number, number]
export type Range = [number, number]

/** True for real, finite numbers (rejects null/undefined/NaN/±Infinity). */
export function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

/** [min, max] over the finite values, or null when there are none. */
export function finiteExtent(values: Iterable<number | null | undefined>): Domain | null {
  let min = Infinity
  let max = -Infinity
  for (const v of values) {
    if (!isFiniteNumber(v)) continue
    if (v < min) min = v
    if (v > max) max = v
  }
  return min === Infinity ? null : [min, max]
}

export interface LinearScale {
  (v: number): number
  invert: (px: number) => number
  domain: Domain
  range: Range
}

/** Linear map domain -> range. A degenerate domain maps everything to the
 *  middle of the range (never NaN). */
export function linearScale(domain: Domain, range: Range): LinearScale {
  const [d0, d1] = domain
  const [r0, r1] = range
  const span = d1 - d0
  const f = ((v: number) =>
    span === 0 || !Number.isFinite(span) ? (r0 + r1) / 2 : r0 + ((v - d0) / span) * (r1 - r0)) as LinearScale
  f.invert = (px: number) => (r1 === r0 || span === 0 ? d0 : d0 + ((px - r0) / (r1 - r0)) * span)
  f.domain = domain
  f.range = range
  return f
}

/** Snap a raw step to the nearest "nice" 1 / 2 / 5 × 10^k value (geometric
 *  midpoints as thresholds, like d3), so the axis lands near the requested
 *  tick count instead of always rounding up to a loose domain. No 2.5 steps:
 *  compact formatters ($1.3M, 3%) would print them wrong. */
export function niceStep(rough: number): number {
  if (!(rough > 0) || !Number.isFinite(rough)) return 1
  const exp = Math.floor(Math.log10(rough))
  const base = 10 ** exp
  const f = rough / base
  const nice = f < Math.SQRT2 ? 1 : f < Math.sqrt(10) ? 2 : f < Math.sqrt(50) ? 5 : 10
  return nice * base
}

function decimalsFor(step: number): number {
  for (let d = 0; d <= 12; d++) {
    if (Math.abs(Number(step.toFixed(d)) - step) <= step * 1e-9) return d
  }
  return 12
}

export interface NiceTicks {
  domain: Domain
  ticks: number[]
  step: number
}

/** Nice axis: expands [min, max] outward to whole steps and lists the ticks.
 *  `count` is a target, not a promise. Non-finite input -> [0, 1]; a flat
 *  range is padded so the single value sits mid-axis (or 0..v with zero). */
export function niceTicks(
  min: number,
  max: number,
  count = 5,
  { includeZero = false }: { includeZero?: boolean } = {},
): NiceTicks {
  let lo = Number.isFinite(min) ? min : NaN
  let hi = Number.isFinite(max) ? max : NaN
  if (Number.isNaN(lo) && Number.isNaN(hi)) {
    lo = 0
    hi = 1
  } else if (Number.isNaN(lo)) lo = hi
  else if (Number.isNaN(hi)) hi = lo
  if (lo > hi) [lo, hi] = [hi, lo]
  if (includeZero) {
    lo = Math.min(lo, 0)
    hi = Math.max(hi, 0)
  }
  if (lo === hi) {
    if (lo === 0) hi = 1
    else {
      const pad = Math.abs(lo) * 0.1
      lo -= pad
      hi += pad
    }
  }
  const step = niceStep((hi - lo) / Math.max(1, count))
  const dec = decimalsFor(step)
  const round = (v: number) => Number(v.toFixed(dec))
  const nMin = round(Math.floor(lo / step + 1e-9) * step)
  const nMax = round(Math.ceil(hi / step - 1e-9) * step)
  const ticks: number[] = []
  const n = Math.round((nMax - nMin) / step)
  for (let i = 0; i <= n && i <= 1000; i++) {
    const t = round(nMin + i * step)
    ticks.push(Object.is(t, -0) ? 0 : t)
  }
  return { domain: [ticks[0], ticks[ticks.length - 1]], ticks, step }
}

export interface BandScale {
  /** Width of one category band (includes its outer padding). */
  band: number
  /** Start px of band i. */
  start: (i: number) => number
  /** Center px of band i. */
  center: (i: number) => number
  /** Band index under px (clamped), or -1 when count is 0. */
  indexAt: (px: number) => number
}

/** Equal-width category bands over [r0, r1]. */
export function bandScale(count: number, range: Range): BandScale {
  const [r0, r1] = range
  const band = count > 0 ? (r1 - r0) / count : 0
  return {
    band,
    start: (i) => r0 + i * band,
    center: (i) => r0 + (i + 0.5) * band,
    indexAt: (px) => (count <= 0 || band === 0 ? -1 : Math.max(0, Math.min(count - 1, Math.floor((px - r0) / band)))),
  }
}

/** Median of the finite values; NaN when there are none. */
export function median(values: readonly (number | null | undefined)[]): number {
  return quantile(values, 0.5)
}

/** Linear-interpolated quantile (type 7, same as Excel PERCENTILE.INC). */
export function quantile(values: readonly (number | null | undefined)[], q: number): number {
  const xs = values.filter(isFiniteNumber).sort((a, b) => a - b)
  if (xs.length === 0) return NaN
  const pos = (xs.length - 1) * Math.max(0, Math.min(1, q))
  const lo = Math.floor(pos)
  const hi = Math.ceil(pos)
  return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)
}
