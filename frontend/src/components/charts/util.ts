import { approxTextWidth } from '../../lib/chartLayout'
import type { Formatter } from './types'

/** Cap a series list at `max`, warning in dev (fold the tail into "Other" or
 *  facet instead of adding hues). */
export function capSeries<T>(series: readonly T[], max: number, chart: string): T[] {
  if (series.length > max && import.meta.env?.DEV) {
    console.warn(`[charts] ${chart} shows at most ${max} series; got ${series.length}. Fold the rest into "Other" or facet.`)
  }
  return series.slice(0, max)
}

/** Plain-text version of a tooltip, for the keyboard live region. */
export function tipText(title: string | undefined, rows: { value: string; label: string }[]): string {
  return [title, ...rows.map((r) => `${r.label} ${r.value}`)].filter(Boolean).join(', ')
}

/** "first to last" for aria summaries. */
export function spanText(a: string, b: string): string {
  return a === b ? a : `${a} to ${b}`
}

export const TICK_FONT = 11

/** Crisp 1px hairline: snap to the half-pixel. */
export const crisp = (v: number) => Math.round(v) + 0.5

/** Widest formatted tick label, px (approx), for the left margin. */
export function tickLabelWidth(ticks: number[], format: Formatter): number {
  return Math.max(0, ...ticks.map((t) => approxTextWidth(format(t), TICK_FONT)))
}
