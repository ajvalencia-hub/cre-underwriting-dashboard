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
