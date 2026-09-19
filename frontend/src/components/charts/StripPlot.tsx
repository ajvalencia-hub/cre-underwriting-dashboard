import { bandScale, finiteExtent, isFiniteNumber, linearScale, median, niceTicks } from '../../lib/chartScale'
import { MARK, approxTextWidth, dodge, nearestPoint } from '../../lib/chartLayout'
import { CategoryLabelsY, RefLine, XGrid } from './Axes'
import { ChartFrame } from './ChartFrame'
import { seriesColor, slotFor, VIZ } from './color'
import { useActiveIndex } from './hooks'
import { PlotSurface } from './PlotSurface'
import type { Formatter, PlotTip, ReferenceLine, SeriesSlot } from './types'
import { tipText } from './util'

export interface StripValue {
  value: number
  /** Shown in the tooltip/table (e.g. comp name, trial #). */
  label?: string
}

export interface StripRow {
  key: string
  label: string
  values: readonly (number | StripValue | null | undefined)[]
  slot?: SeriesSlot
}

export interface StripPlotProps {
  title: string
  subtitle?: string
  /** One row per group (e.g. comp set by property type, one metric's trials). */
  rows: readonly StripRow[]
  format: Formatter
  tickFormat?: Formatter
  /** Median tick per row (default true). */
  showMedian?: boolean
  /** A value to mark across every row — the subject deal, a hurdle. */
  referenceLine?: ReferenceLine
  /** Column header for the value in the table view. */
  valueLabel?: string
  /** Height of each row band, px (default 48). */
  rowHeight?: number
  emptyMessage?: string
  ariaLabel?: string
  className?: string
}

interface Dot {
  row: number
  value: number
  label?: string
}

function flatten(rows: readonly StripRow[]): Dot[] {
  return rows.flatMap((r, ri) =>
    r.values
      .map((v) => (typeof v === 'number' || v == null ? { value: v as number, label: undefined } : v))
      .filter((v) => isFiniteNumber(v.value))
      .map((v) => ({ row: ri, value: v.value, label: v.label })),
  )
}

/** Distribution of a few dozen values per row, with a median tick. Also
 *  exported as DotPlot. */
export function StripPlot(props: StripPlotProps) {
  const { title, subtitle, rows, format, showMedian = true, valueLabel = 'Value', emptyMessage, className } = props
  const dots = flatten(rows)
  const multi = rows.length > 1
  const tableRows: string[][] = []
  rows.forEach((r, ri) => {
    const mine = dots.filter((d) => d.row === ri).sort((p, q) => p.value - q.value)
    mine.forEach((d, i) => tableRows.push([...(multi ? [r.label] : []), d.label ?? `#${i + 1}`, format(d.value)]))
    if (showMedian && mine.length > 0) tableRows.push([...(multi ? [r.label] : []), 'Median', format(median(mine.map((d) => d.value)))])
  })
  const table = { columns: [...(multi ? ['Group'] : []), 'Item', valueLabel], rows: tableRows }
  const legend = showMedian
    ? [{ key: 'median', label: 'Median', color: VIZ.textPrimary, shape: 'line' as const }]
    : undefined
  return (
    <ChartFrame
      title={title}
      subtitle={subtitle}
      legend={legend}
      table={table}
      empty={dots.length === 0}
      emptyMessage={emptyMessage ?? 'No values to plot.'}
      className={className}
    >
      {(width) => <StripInner {...props} dots={dots} width={width} />}
    </ChartFrame>
  )
}

export const DotPlot = StripPlot

function StripInner({
  title,
  rows,
  format,
  tickFormat,
  showMedian = true,
  referenceLine,
  rowHeight = 48,
  ariaLabel,
  dots,
  width,
}: StripPlotProps & { dots: Dot[]; width: number }) {
  const cursor = useActiveIndex(dots.length)
  const tf = tickFormat ?? format
  const multi = rows.length > 1
  const ext = finiteExtent([...dots.map((d) => d.value), referenceLine?.value]) ?? [0, 1]
  const top = referenceLine ? 16 : 4
  const bottom = 24
  const height = top + rows.length * rowHeight + bottom
  const left = multi ? Math.min(Math.ceil(Math.max(...rows.map((r) => approxTextWidth(r.label)))) + 12, Math.round(width * 0.35)) : 12
  const right = 16
  const plotW = Math.max(40, width - left - right)
  const nt = niceTicks(ext[0], ext[1], Math.max(2, Math.floor(plotW / 80)))
  const x = linearScale(nt.domain, [left, left + plotW])
  const band = bandScale(rows.length, [top, top + rows.length * rowHeight])
  const R = MARK.markerRadius + MARK.ringWidth / 2

  const px: { x: number; y: number }[] = new Array(dots.length)
  const medians = rows.map((_, ri) => median(dots.filter((d) => d.row === ri).map((d) => d.value)))
  rows.forEach((_, ri) => {
    const idx = dots.map((d, i) => (d.row === ri ? i : -1)).filter((i) => i >= 0)
    const offs = dodge(
      idx.map((i) => x(dots[i].value)),
      R,
      rowHeight / 2 - R - 2,
    )
    idx.forEach((i, k) => {
      px[i] = { x: x(dots[i].value), y: band.center(ri) + offs[k] }
    })
  })

  const order = dots.map((_, i) => i).sort((i, j) => dots[i].row - dots[j].row || dots[i].value - dots[j].value)
  const a = cursor.active >= 0 ? order[cursor.active] : -1
  let tip: PlotTip | null = null
  if (a >= 0) {
    const d = dots[a]
    const t = d.label ?? rows[d.row].label
    const rowsT = [
      { key: 'v', value: format(d.value), label: d.label ? rows[d.row].label : 'value', color: seriesColor(slotFor(0, rows[d.row].slot)) },
      ...(showMedian ? [{ key: 'm', value: format(medians[d.row]), label: 'median' }] : []),
    ]
    tip = { x: px[a].x, y: px[a].y, content: { title: t, rows: rowsT }, text: tipText(t, rowsT) }
  }

  const summary =
    ariaLabel ??
    `${title}. Dot plot. ` +
      rows
        .map((r, ri) => {
          const vs = dots.filter((d) => d.row === ri).map((d) => d.value)
          if (!vs.length) return `${r.label}: no values.`
          return `${r.label}: ${vs.length} values, ${format(Math.min(...vs))} to ${format(Math.max(...vs))}, median ${format(medians[ri])}.`
        })
        .join(' ')

  return (
    <PlotSurface
      width={width}
      height={height}
      summary={summary}
      count={dots.length}
      cursor={cursor}
      hitTest={(hx, hy) => {
        const i = nearestPoint(px, hx, hy, 24)
        return i < 0 ? -1 : order.indexOf(i)
      }}
      tip={tip}
    >
      <XGrid ticks={nt.ticks} scale={x} y0={top} y1={top + rows.length * rowHeight} format={tf} />
      {multi && <CategoryLabelsY labels={rows.map((r) => r.label)} center={band.center} x={left - 8} maxWidth={left - 12} />}
      {referenceLine && (
        <RefLine line={referenceLine} orientation="v" pos={x(referenceLine.value)} from={top - 12} to={top + rows.length * rowHeight} />
      )}
      <g aria-hidden="true">
        {dots.map((d, i) => (
          <circle
            key={i}
            cx={px[i].x}
            cy={px[i].y}
            r={R}
            strokeWidth={MARK.ringWidth}
            style={{ fill: seriesColor(slotFor(0, rows[d.row].slot)), stroke: VIZ.surface }}
            opacity={0.9}
          />
        ))}
        {showMedian &&
          medians.map((m, ri) =>
            isFiniteNumber(m) ? (
              <line
                key={ri}
                x1={x(m)}
                x2={x(m)}
                y1={band.center(ri) - rowHeight * 0.38}
                y2={band.center(ri) + rowHeight * 0.38}
                strokeWidth={2}
                strokeLinecap="round"
                style={{ stroke: VIZ.textPrimary }}
              />
            ) : null,
          )}
        {a >= 0 && (
          <circle cx={px[a].x} cy={px[a].y} r={R + 1} strokeWidth={2} style={{ fill: seriesColor(slotFor(0, rows[dots[a].row].slot)), stroke: VIZ.textPrimary }} />
        )}
      </g>
    </PlotSurface>
  )
}
