import type { SeriesSlot } from './types'

/** CSS color for a categorical slot (theme-aware via --viz-series-N). */
export function seriesColor(slot: SeriesSlot): string {
  return `var(--viz-series-${slot})`
}

/** Explicit slot if given, else the series' position (1-based, capped at 8 —
 *  the kit never cycles or generates a 9th hue). */
export function slotFor(index: number, slot?: SeriesSlot): SeriesSlot {
  if (slot) return slot
  return Math.min(8, Math.max(1, index + 1)) as SeriesSlot
}

export const VIZ = {
  surface: 'var(--viz-surface)',
  textPrimary: 'var(--viz-text-primary)',
  textSecondary: 'var(--viz-text-secondary)',
  textMuted: 'var(--viz-text-muted)',
  grid: 'var(--viz-grid)',
  axis: 'var(--viz-axis)',
  deemphasis: 'var(--viz-deemphasis)',
  divNeg: 'var(--viz-div-neg)',
  divMid: 'var(--viz-div-mid)',
  divPos: 'var(--viz-div-pos)',
} as const

