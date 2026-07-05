// Pure SVG-path geometry for the mini trend charts (H6). Framework-free for
// unit testing. Values scale into [pad, height-pad] with y inverted (SVG y
// grows downward); a flat or single-point series renders a mid-height line.

export interface SeriesPoint {
  period: string
  value: number
}

export function linePath(values: number[], width: number, height: number, pad = 3): string {
  if (values.length === 0) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min
  const innerH = height - 2 * pad
  const y = (v: number) => (span === 0 ? height / 2 : pad + innerH * (1 - (v - min) / span))
  if (values.length === 1) {
    return `M0,${y(values[0]).toFixed(2)} L${width},${y(values[0]).toFixed(2)}`
  }
  const step = width / (values.length - 1)
  return values
    .map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(2)},${y(v).toFixed(2)}`)
    .join(' ')
}

/** Bar geometry: x/y/height per value, bars always anchored to the chart
 *  floor. Returns [] for an empty series. */
export function barRects(
  values: number[],
  width: number,
  height: number,
  gap = 2,
): { x: number; y: number; w: number; h: number }[] {
  if (values.length === 0) return []
  const max = Math.max(...values)
  const min = Math.min(0, ...values)
  const span = max - min || 1
  const w = Math.max(1, width / values.length - gap)
  return values.map((v, i) => {
    const h = Math.max(1, ((v - min) / span) * height)
    return { x: (width / values.length) * i + gap / 2, y: height - h, w, h }
  })
}

/** Compact value label: 1.2M, 84k, 5.3%, $71,400 — the caller picks kind. */
export function compactValue(v: number, kind: 'count' | 'money' | 'percent'): string {
  if (kind === 'percent') return `${(v * 100).toFixed(1)}%`
  const prefix = kind === 'money' ? '$' : ''
  if (Math.abs(v) >= 1_000_000) return `${prefix}${(v / 1_000_000).toFixed(2)}M`
  if (Math.abs(v) >= 10_000) return `${prefix}${Math.round(v / 1000)}k`
  return `${prefix}${Math.round(v).toLocaleString()}`
}
