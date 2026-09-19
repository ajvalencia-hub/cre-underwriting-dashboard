import type { LinearScale } from '../../lib/chartScale'
import { truncateLabel } from '../../lib/chartLayout'
import type { Formatter, ReferenceLine } from './types'
import { TICK_FONT, crisp } from './util'

/** Horizontal hairline gridlines + value labels on the left (value axis of
 *  vertical charts). Solid, never dashed. */
export function YGrid({
  ticks,
  scale,
  x0,
  x1,
  format,
}: {
  ticks: number[]
  scale: LinearScale
  x0: number
  x1: number
  format: Formatter
}) {
  return (
    <g aria-hidden="true">
      {ticks.map((t) => {
        const y = crisp(scale(t))
        return (
          <g key={t}>
            <line x1={x0} x2={x1} y1={y} y2={y} strokeWidth={1} className="stroke-viz-grid" />
            <text x={x0 - 6} y={y} dy="0.32em" textAnchor="end" fontSize={TICK_FONT} className="fill-viz-muted viz-tabular">
              {format(t)}
            </text>
          </g>
        )
      })}
    </g>
  )
}

/** Vertical hairline gridlines + value labels along the bottom (value axis of
 *  horizontal bars, strip plots, scatter x). */
export function XGrid({
  ticks,
  scale,
  y0,
  y1,
  format,
}: {
  ticks: number[]
  scale: LinearScale
  y0: number
  y1: number
  format: Formatter
}) {
  return (
    <g aria-hidden="true">
      {ticks.map((t, i) => {
        const x = crisp(scale(t))
        const anchor = ticks.length > 1 && i === 0 ? 'start' : ticks.length > 1 && i === ticks.length - 1 ? 'end' : 'middle'
        return (
          <g key={t}>
            <line x1={x} x2={x} y1={y0} y2={y1} strokeWidth={1} className="stroke-viz-grid" />
            <text x={x} y={y1 + 14} textAnchor={anchor} fontSize={TICK_FONT} className="fill-viz-muted viz-tabular">
              {format(t)}
            </text>
          </g>
        )
      })}
    </g>
  )
}

/** Category labels under a vertical chart, thinned by `stride`. */
export function CategoryLabelsX({
  labels,
  center,
  y,
  stride,
  maxWidth,
}: {
  labels: string[]
  center: (i: number) => number
  y: number
  stride: number
  maxWidth: number
}) {
  return (
    <g aria-hidden="true">
      {labels.map((label, i) =>
        i % stride === 0 ? (
          <text key={i} x={center(i)} y={y} textAnchor="middle" fontSize={TICK_FONT} className="fill-viz-muted">
            {truncateLabel(label, maxWidth * stride)}
          </text>
        ) : null,
      )}
    </g>
  )
}

/** Category labels left of a horizontal chart (ellipsized, full text in <title>). */
export function CategoryLabelsY({
  labels,
  center,
  x,
  maxWidth,
}: {
  labels: string[]
  center: (i: number) => number
  x: number
  maxWidth: number
}) {
  return (
    <g aria-hidden="true">
      {labels.map((label, i) => {
        const shown = truncateLabel(label, maxWidth)
        return (
          <text key={i} x={x} y={center(i)} dy="0.32em" textAnchor="end" fontSize={TICK_FONT} className="fill-viz-secondary">
            {shown !== label && <title>{label}</title>}
            {shown}
          </text>
        )
      })}
    </g>
  )
}

const HALO = { paintOrder: 'stroke', stroke: 'var(--viz-surface)', strokeWidth: 3, strokeLinejoin: 'round' } as const

/** Dashed reference/threshold line (hurdle, 1.25x DSCR, subject value) with a
 *  muted label. Dashing here means "threshold" — gridlines stay solid. */
export function RefLine({
  line,
  orientation,
  pos,
  from,
  to,
}: {
  line: ReferenceLine
  /** 'h' = horizontal line at y=pos spanning x from..to; 'v' = vertical at x=pos. */
  orientation: 'h' | 'v'
  pos: number
  from: number
  to: number
}) {
  if (!Number.isFinite(pos)) return null
  const p = crisp(pos)
  return orientation === 'h' ? (
    <g aria-hidden="true">
      <line x1={from} x2={to} y1={p} y2={p} strokeWidth={1} strokeDasharray="4 3" style={{ stroke: 'var(--viz-text-muted)' }} />
      <text x={to} y={p - 4} textAnchor="end" fontSize={TICK_FONT} className="fill-viz-secondary" style={HALO}>
        {line.label}
      </text>
    </g>
  ) : (
    <g aria-hidden="true">
      <line x1={p} x2={p} y1={from} y2={to} strokeWidth={1} strokeDasharray="4 3" style={{ stroke: 'var(--viz-text-muted)' }} />
      <text x={p + 4} y={from + 10} textAnchor="start" fontSize={TICK_FONT} className="fill-viz-secondary" style={HALO}>
        {line.label}
      </text>
    </g>
  )
}

