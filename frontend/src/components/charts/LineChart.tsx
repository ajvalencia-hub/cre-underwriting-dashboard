import { finiteExtent, isFiniteNumber, linearScale, niceTicks } from '../../lib/chartScale'
import {
  MARK,
  gappedAreaPath,
  gappedLinePath,
  isolatedIndices,
  labelStride,
  nearestIndex,
  type MaybePoint,
} from '../../lib/chartLayout'
import { CategoryLabelsX, RefLine, YGrid } from './Axes'
import { ChartFrame } from './ChartFrame'
import { seriesColor, slotFor, VIZ } from './color'
import { useActiveIndex } from './hooks'
import { PlotSurface } from './PlotSurface'
import type { Formatter, PlotTip, ReferenceLine, SeriesSlot } from './types'
import { capSeries, spanText, tickLabelWidth, tipText } from './util'

export interface LineSeries {
  key: string
  label: string
  /** One value per `x`; null/NaN = gap (the line lifts, it never bridges). */
  values: readonly (number | null | undefined)[]
  slot?: SeriesSlot
}

export interface LineChartProps {
  title: string
  subtitle?: string
  /** Ordered, evenly spaced x positions (hold years, months, periods). */
  x: readonly (string | number)[]
  /** 1–4 series on ONE y-axis (different units -> two charts, never dual-axis). */
  series: readonly LineSeries[]
  /** Formats values in the tooltip and table. */
  format: Formatter
  /** Formats y-axis ticks (e.g. formatMoneyCompact); defaults to `format`. */
  tickFormat?: Formatter
  /** Formats x labels; defaults to String(x). */
  xFormat?: (x: string | number) => string
  /** Column header for x in the table view. */
  xLabel?: string
  /** Horizontal threshold, e.g. { value: 1.25, label: '1.25x DSCR' }. */
  referenceLine?: ReferenceLine
  /** ~10% wash under the line — single series only. */
  area?: boolean
  /** Force 0 into the y-domain (sensible for money/areas). */
  includeZero?: boolean
  /** Total SVG height in px (includes the x-axis band). Default 220. */
  height?: number
  emptyMessage?: string
  ariaLabel?: string
  className?: string
}

export function LineChart(props: LineChartProps) {
  const { title, subtitle, x, format, xLabel = 'Period', emptyMessage, className } = props
  const xf = props.xFormat ?? ((v: string | number) => String(v))
  const series = capSeries(props.series, 4, 'LineChart')
  const finiteCount = series.reduce((n, s) => n + s.values.filter(isFiniteNumber).length, 0)
  const empty = x.length < 2 || finiteCount < 2

  const table = {
    columns: [xLabel, ...series.map((s) => s.label)],
    rows: x.map((xv, i) => [xf(xv), ...series.map((s) => (isFiniteNumber(s.values[i]) ? format(s.values[i] as number) : '—'))]),
  }
  const legend =
    series.length >= 2
      ? series.map((s, i) => ({ key: s.key, label: s.label, slot: slotFor(i, s.slot), shape: 'line' as const }))
      : undefined

  return (
    <ChartFrame
      title={title}
      subtitle={subtitle}
      legend={legend}
      table={table}
      empty={empty}
      emptyMessage={emptyMessage ?? 'Not enough points to draw a trend.'}
      className={className}
    >
      {(width) => <LinePlot {...props} series={series} width={width} xf={xf} />}
    </ChartFrame>
  )
}

function LinePlot({
  title,
  x,
  series,
  format,
  tickFormat,
  referenceLine,
  area,
  includeZero,
  height = 220,
  ariaLabel,
  width,
  xf,
}: LineChartProps & { width: number; xf: (v: string | number) => string }) {
  const cursor = useActiveIndex(x.length)
  const tf = tickFormat ?? format
  const all = series.flatMap((s) => s.values)
  const ext = finiteExtent(referenceLine ? [...all, referenceLine.value] : all) ?? [0, 1]
  const top = 12
  const bottom = 24
  const plotH = Math.max(40, height - top - bottom)
  const nt = niceTicks(ext[0], ext[1], Math.max(2, Math.floor(plotH / 45)), { includeZero: includeZero || area })
  const left = Math.ceil(tickLabelWidth(nt.ticks, tf)) + 10
  const right = 12
  const plotW = Math.max(40, width - left - right)
  const y = linearScale(nt.domain, [top + plotH, top])
  const xs = x.map((_, i) => left + (x.length === 1 ? plotW / 2 : (i / (x.length - 1)) * plotW))

  const pts = series.map((s) => x.map((_, i): MaybePoint => (isFiniteNumber(s.values[i]) ? { x: xs[i], y: y(s.values[i] as number) } : null)))
  const colors = series.map((s, i) => seriesColor(slotFor(i, s.slot)))
  const labels = x.map((v) => xf(v))
  const maxLabel = Math.max(...labels.map((l) => l.length)) * 6.4
  const stride = labelStride(x.length, plotW, Math.min(maxLabel, 80))

  const summary =
    ariaLabel ??
    `${title}. Line chart, ${spanText(labels[0], labels[labels.length - 1])}. ` +
      series
        .map((s) => {
          const f = s.values.filter(isFiniteNumber)
          return f.length ? `${s.label}: ${spanText(format(f[0]), format(f[f.length - 1]))}.` : `${s.label}: no data.`
        })
        .join(' ')

  const a = cursor.active
  let tip: PlotTip | null = null
  if (a >= 0) {
    const rows = series.map((s, i) => ({
      key: s.key,
      label: s.label,
      value: isFiniteNumber(s.values[a]) ? format(s.values[a] as number) : '—',
      color: colors[i],
    }))
    const ys = pts.map((p) => p[a]?.y).filter(isFiniteNumber)
    tip = {
      x: xs[a],
      y: ys.length ? Math.min(...ys) : top + plotH / 2,
      content: { title: labels[a], rows },
      text: tipText(labels[a], rows),
    }
  }

  const baseY = y(Math.max(nt.domain[0], Math.min(0, nt.domain[1])))
  return (
    <PlotSurface
      width={width}
      height={height}
      summary={summary}
      count={x.length}
      cursor={cursor}
      hitTest={(px) => nearestIndex(xs, px)}
      tip={tip}
    >
      <YGrid ticks={nt.ticks} scale={y} x0={left} x1={left + plotW} format={tf} />
      <CategoryLabelsX labels={labels} center={(i) => xs[i]} y={height - 6} stride={stride} maxWidth={plotW / x.length} />
      {area && series.length === 1 && (
        <path d={gappedAreaPath(pts[0], baseY)} style={{ fill: colors[0] }} fillOpacity={0.1} aria-hidden="true" />
      )}
      {referenceLine && (
        <RefLine line={referenceLine} orientation="h" pos={y(referenceLine.value)} from={left} to={left + plotW} />
      )}
      {pts.map((p, si) => (
        <g key={series[si].key} aria-hidden="true">
          <path
            d={gappedLinePath(p)}
            fill="none"
            strokeWidth={MARK.lineWidth}
            strokeLinejoin="round"
            strokeLinecap="round"
            style={{ stroke: colors[si] }}
          />
          {isolatedIndices(p).map((i) => (
            <circle key={i} cx={p[i]!.x} cy={p[i]!.y} r={MARK.markerRadius + MARK.ringWidth / 2} strokeWidth={MARK.ringWidth} style={{ fill: colors[si], stroke: VIZ.surface }} />
          ))}
        </g>
      ))}
      {a >= 0 && (
        <g aria-hidden="true" pointerEvents="none">
          <line x1={Math.round(xs[a]) + 0.5} x2={Math.round(xs[a]) + 0.5} y1={top} y2={top + plotH} strokeWidth={1} className="stroke-viz-axis" />
          {pts.map((p, si) =>
            p[a] ? (
              <circle
                key={si}
                cx={p[a]!.x}
                cy={p[a]!.y}
                r={MARK.markerRadius + MARK.ringWidth / 2}
                strokeWidth={MARK.ringWidth}
                style={{ fill: colors[si], stroke: VIZ.surface }}
              />
            ) : null,
          )}
        </g>
      )}
    </PlotSurface>
  )
}
