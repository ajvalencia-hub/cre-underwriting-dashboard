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

// Interpolates rose-100 (low) -> emerald-100 (high) for a simple heatmap scale.
export function heatColor(t: number): string {
  const from = [255, 228, 230]
  const to = [209, 250, 229]
  const clamped = Math.max(0, Math.min(1, t))
  const rgb = from.map((c, i) => Math.round(c + (to[i] - c) * clamped))
  return `rgb(${rgb[0]} ${rgb[1]} ${rgb[2]})`
}
