import { finiteExtent, isFiniteNumber, linearScale, niceTicks } from '../../lib/chartScale'
import { MARK, nearestPoint } from '../../lib/chartLayout'
import { RefLine, XGrid, YGrid } from './Axes'
import { ChartFrame } from './ChartFrame'
import { seriesColor, slotFor, VIZ } from './color'
import { useActiveIndex } from './hooks'
import { PlotSurface } from './PlotSurface'
import type { Formatter, PlotTip, ReferenceLine, SeriesSlot } from './types'
import { capSeries, TICK_FONT, tickLabelWidth, tipText } from './util'

export interface ScatterPoint {
  x: number
  y: number
  /** Shown in the tooltip/table (e.g. comp name). */
  label?: string
}

export interface ScatterSeries {
  key: string
  label: string
  points: readonly ScatterPoint[]
  slot?: SeriesSlot
}

export interface ScatterChartProps {
  title: string
  subtitle?: string
  /** ≤3 series: any two dots can sit side by side, so only the first three
   *  slots are validated all-pairs. More -> fold to "Other" or facet. */
  series: readonly ScatterSeries[]
  xLabel: string
  yLabel: string
  xFormat: Formatter
  yFormat: Formatter
  xTickFormat?: Formatter
  yTickFormat?: Formatter
  /** Vertical reference at an x value (quadrant split). */
  referenceX?: ReferenceLine
  /** Horizontal reference at a y value (quadrant split). */
  referenceY?: ReferenceLine
  includeZeroX?: boolean
  includeZeroY?: boolean
  /** Total SVG height (default 280). */
  height?: number
  emptyMessage?: string
  ariaLabel?: string
  className?: string
}

interface FlatPoint extends ScatterPoint {
  series: number
}

function flatten(series: readonly ScatterSeries[]): FlatPoint[] {
  return series.flatMap((s, si) =>
    s.points.filter((p) => isFiniteNumber(p.x) && isFiniteNumber(p.y)).map((p) => ({ ...p, series: si })),
  )
}

export function ScatterChart(props: ScatterChartProps) {
  const { title, subtitle, xLabel, yLabel, xFormat, yFormat, emptyMessage, className } = props
  const series = capSeries(props.series, 3, 'ScatterChart')
  const pts = flatten(series)
  const multi = series.length > 1
  const hasLabels = pts.some((p) => p.label)
  const table = {
    columns: [...(hasLabels ? ['Point'] : []), ...(multi ? ['Series'] : []), xLabel, yLabel],
    rows: pts.map((p, i) => [
      ...(hasLabels ? [p.label ?? `#${i + 1}`] : []),
      ...(multi ? [series[p.series].label] : []),
      xFormat(p.x),
      yFormat(p.y),
    ]),
  }
  // Table's first column is the row header; without labels, number the rows.
  if (!hasLabels && !multi) {
    table.columns.unshift('#')
    table.rows.forEach((r, i) => r.unshift(String(i + 1)))
  }
  const legend = multi
    ? series.map((s, i) => ({ key: s.key, label: s.label, slot: slotFor(i, s.slot), shape: 'dot' as const }))
    : undefined
  return (
    <ChartFrame
      title={title}
      subtitle={subtitle}
      legend={legend}
      table={table}
      empty={pts.length === 0}
      emptyMessage={emptyMessage ?? 'No points to plot.'}
      className={className}
    >
      {(width) => <ScatterPlot {...props} series={series} points={pts} width={width} />}
    </ChartFrame>
  )
}

function ScatterPlot({
  title,
  series,
  points,
  xLabel,
  yLabel,
  xFormat,
  yFormat,
  xTickFormat,
  yTickFormat,
  referenceX,
  referenceY,
  includeZeroX,
  includeZeroY,
  height = 280,
  ariaLabel,
  width,
}: ScatterChartProps & { points: FlatPoint[]; width: number }) {
  const cursor = useActiveIndex(points.length)
  const xtf = xTickFormat ?? xFormat
  const ytf = yTickFormat ?? yFormat
  const xe = finiteExtent([...points.map((p) => p.x), referenceX?.value]) ?? [0, 1]
  const ye = finiteExtent([...points.map((p) => p.y), referenceY?.value]) ?? [0, 1]
  const top = 26 // y-axis title row
  const bottom = 40 // tick labels + x-axis title
  const plotH = Math.max(40, height - top - bottom)
  const yt = niceTicks(ye[0], ye[1], Math.max(2, Math.floor(plotH / 45)), { includeZero: includeZeroY })
  const left = Math.ceil(tickLabelWidth(yt.ticks, ytf)) + 10
  const right = 16
  const plotW = Math.max(40, width - left - right)
  const xt = niceTicks(xe[0], xe[1], Math.max(2, Math.floor(plotW / 80)), { includeZero: includeZeroX })
  const x = linearScale(xt.domain, [left, left + plotW])
  const y = linearScale(yt.domain, [top + plotH, top])
  const px = points.map((p) => ({ x: x(p.x), y: y(p.y) }))
  const colors = series.map((s, i) => seriesColor(slotFor(i, s.slot)))

  // Keyboard order: left to right.
  const order = points.map((_, i) => i).sort((i, j) => points[i].x - points[j].x || points[i].y - points[j].y)
  const a = cursor.active >= 0 ? order[cursor.active] : -1
  let tip: PlotTip | null = null
  if (a >= 0) {
    const p = points[a]
    const title = p.label ?? series[p.series].label
    const rows = [
      { key: 'x', value: xFormat(p.x), label: xLabel, color: colors[p.series] },
      { key: 'y', value: yFormat(p.y), label: yLabel },
    ]
    tip = { x: px[a].x, y: px[a].y, content: { title, rows }, text: tipText(title, rows) }
  }

  const summary =
    ariaLabel ??
    `${title}. Scatter plot of ${points.length} point${points.length === 1 ? '' : 's'}${
      series.length > 1 ? ` in ${series.length} series` : ''
    }: ${xLabel} ${xFormat(xe[0])}–${xFormat(xe[1])}, ${yLabel} ${yFormat(ye[0])}–${yFormat(ye[1])}.`

  const R = MARK.markerRadius + MARK.ringWidth / 2
  return (
    <PlotSurface
      width={width}
      height={height}
      summary={summary}
      count={points.length}
      cursor={cursor}
      hitTest={(hx, hy) => {
        const i = nearestPoint(px, hx, hy, 32)
        return i < 0 ? -1 : order.indexOf(i)
      }}
      tip={tip}
    >
      <text x={left} y={12} fontSize={TICK_FONT} className="fill-viz-secondary" aria-hidden="true">
        {yLabel}
      </text>
      <YGrid ticks={yt.ticks} scale={y} x0={left} x1={left + plotW} format={ytf} />
      <XGrid ticks={xt.ticks} scale={x} y0={top} y1={top + plotH} format={xtf} />
      <text x={left + plotW} y={height - 4} textAnchor="end" fontSize={TICK_FONT} className="fill-viz-secondary" aria-hidden="true">
        {xLabel}
      </text>
      {referenceX && <RefLine line={referenceX} orientation="v" pos={x(referenceX.value)} from={top} to={top + plotH} />}
      {referenceY && <RefLine line={referenceY} orientation="h" pos={y(referenceY.value)} from={left} to={left + plotW} />}
      <g aria-hidden="true">
        {points.map((p, i) => (
          <circle
            key={i}
            cx={px[i].x}
            cy={px[i].y}
            r={R}
            strokeWidth={MARK.ringWidth}
            style={{ fill: colors[p.series], stroke: VIZ.surface }}
          />
        ))}
        {a >= 0 && (
          <circle
            cx={px[a].x}
            cy={px[a].y}
            r={R + 1}
            strokeWidth={2}
            style={{ fill: colors[points[a].series], stroke: VIZ.textPrimary }}
          />
        )}
      </g>
    </PlotSurface>
  )
}
