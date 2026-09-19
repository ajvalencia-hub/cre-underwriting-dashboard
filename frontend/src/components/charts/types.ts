/** Number -> display string. Pass the app's formatters (formatMoney,
 *  formatMoneyCompact, a percent/multiple helper…); the kit never formats
 *  numbers on its own. */
export type Formatter = (v: number) => string

/** Categorical slot 1..8 (maps to --viz-series-N). Give each entity a fixed
 *  slot so its color survives filtering — color follows the entity, not the
 *  row index. */
export type SeriesSlot = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8

export interface LegendItem {
  key: string
  label: string
  /** Categorical slot, or `color` for a non-categorical role (e.g. deemphasis). */
  slot?: SeriesSlot
  color?: string
  /** Mirror the mark: 'line' for lines, 'rect' for bars/areas, 'dot' for scatter. */
  shape: 'line' | 'rect' | 'dot'
}

/** The accessible table twin of a chart (already-formatted strings). */
export interface ChartTable {
  columns: string[]
  rows: string[][]
}

/** A horizontal/vertical reference line (hurdle rate, 1.25x DSCR, subject deal). */
export interface ReferenceLine {
  value: number
  label: string
}

export interface TooltipRow {
  key: string
  /** Formatted value — rendered strong (values lead, labels follow). */
  value: string
  label: string
  /** CSS color of the line key (a short stroke, not a box). */
  color?: string
}

export interface TooltipContentData {
  title?: string
  rows: TooltipRow[]
}

export interface PlotTip {
  /** Anchor in plot px (same box as the SVG). */
  x: number
  y: number
  content: TooltipContentData
  /** Plain-text announcement for keyboard users (aria-live). */
  text: string
}
