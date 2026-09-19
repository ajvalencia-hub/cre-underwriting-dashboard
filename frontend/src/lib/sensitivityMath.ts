export interface DriverBounds {
  min: string
  max: string
  steps: string
}

// Number('') === 0, so an empty min/max draft used to coerce into a sweep
// from 0 (e.g. a 0% exit cap grid point) if the run fired anyway. A driver's
// sweep is only usable once both bounds parse to finite numbers and steps is
// an integer >= 2.
export function boundsReady(bounds: DriverBounds): boolean {
  const min = Number(bounds.min)
  const max = Number(bounds.max)
  const steps = Number(bounds.steps)
  return (
    bounds.min.trim() !== '' &&
    bounds.max.trim() !== '' &&
    Number.isFinite(min) &&
    Number.isFinite(max) &&
    Number.isInteger(steps) &&
    steps >= 2
  )
}

export function linspace(min: number, max: number, steps: number): number[] {
  if (steps <= 1) return [min]
  const result: number[] = []
  for (let i = 0; i < steps; i++) {
    result.push(min + ((max - min) * i) / (steps - 1))
  }
  return result
}

/** A starting range centred on the deal's current value (roadmap #17):
 *  ±100 bps for rates, ±10% otherwise. `current` is in display units (a
 *  percent field's 6.5 means 6.5%). Returns null without a current value. */
export function defaultRange(type: string, current: number | null): { min: string; max: string } | null {
  if (current === null || !Number.isFinite(current)) return null
  const round = (v: number) => String(Math.round(v * 1e6) / 1e6)
  if (type === 'percent') return { min: round(current - 1), max: round(current + 1) }
  const delta = Math.abs(current) * 0.1 || 1
  return { min: round(current - delta), max: round(current + delta) }
}

/** Colour-blind-safe diverging scale centred on the base case: white at the
 *  base value, blue above it, orange below, by how far relative to the
 *  largest deviation in the grid. (It was red→green between the grid's own
 *  min and max, so a grid that entirely misses a target still showed green.) */
export function divergingColor(value: number, base: number, maxAbsDelta: number): string {
  if (!Number.isFinite(value) || !Number.isFinite(base) || maxAbsDelta <= 0) return 'rgb(255 255 255)'
  const t = Math.max(-1, Math.min(1, (value - base) / maxAbsDelta))
  const to = t >= 0 ? [191, 219, 254] : [254, 215, 170] // blue-200 / orange-200
  const rgb = to.map((c) => Math.round(255 + (c - 255) * Math.abs(t)))
  return `rgb(${rgb[0]} ${rgb[1]} ${rgb[2]})`
}
