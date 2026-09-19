import { bandScale, finiteExtent, isFiniteNumber, linearScale, niceTicks } from '../../lib/chartScale'
import {
  MARK,
  applyStackGap,
  approxTextWidth,
  barRect,
  dataEnd,
  groupedBarSlots,
  labelStride,
  roundedBarPath,
  stackExtent,
  stackValues,
} from '../../lib/chartLayout'
import { CategoryLabelsX, CategoryLabelsY, RefLine, XGrid, YGrid } from './Axes'
import { ChartFrame } from './ChartFrame'
import { seriesColor, slotFor, VIZ } from './color'
import { useActiveIndex } from './hooks'
import { PlotSurface } from './PlotSurface'
import type { Formatter, PlotTip, ReferenceLine, SeriesSlot } from './types'
import { capSeries, TICK_FONT, tickLabelWidth, tipText } from './util'

export interface BarSeries {
  key: string
  label: string
  /** One value per category; null/NaN = no bar. Negatives hang below zero. */
  values: readonly (number | null | undefined)[]
  slot?: SeriesSlot
}

export interface BarChartProps {
  title: string
  subtitle?: string
  categories: readonly string[]
  series: readonly BarSeries[]
  format: Formatter
  /** Value-axis tick format (e.g. formatMoneyCompact); defaults to `format`. */
  tickFormat?: Formatter
  /** 'vertical' columns (default) or 'horizontal' bars (long/many category names). */
  orientation?: 'vertical' | 'horizontal'
  /** Multi-series layout: side by side (default) or stacked (part-to-whole). */
  mode?: 'grouped' | 'stacked'
  /** Value at each bar tip — only for a few bars (≤ ~12); ignored when stacked. */
  showValues?: boolean
  /** Single series: color by sign with the diverging poles (e.g. cash flow). */
  diverging?: boolean
  /** Single series emphasis: this category in slot color, the rest de-emphasized. */
  highlight?: string
  referenceLine?: ReferenceLine
  /** Column header for categories in the table view. */
  categoryLabel?: string
  /** Vertical: total SVG height (default 240). Horizontal: default rows × 32. */
  height?: number
  emptyMessage?: string
  ariaLabel?: string
  className?: string
}

interface BarMark {
  cat: number
  series: number
  value: number
  d: string
  fill: string
  hit: { x: number; y: number; w: number; h: number }
  tip: { x: number; y: number }
  label?: { x: number; y: number; anchor: 'start' | 'middle' | 'end'; text: string }
}

export function BarChart(props: BarChartProps) {
  const { title, subtitle, categories, format, categoryLabel = 'Category', emptyMessage, className } = props
  const series = capSeries(props.series, 8, 'BarChart')
  const empty = categories.length === 0 || !series.some((s) => s.values.some(isFiniteNumber))
  const table = {
    columns: [categoryLabel, ...series.map((s) => s.label)],
    rows: categories.map((c, i) => [c, ...series.map((s) => (isFiniteNumber(s.values[i]) ? format(s.values[i] as number) : '—'))]),
  }
  const legend =
    series.length >= 2
      ? series.map((s, i) => ({ key: s.key, label: s.label, slot: slotFor(i, s.slot), shape: 'rect' as const }))
      : undefined
  return (
    <ChartFrame
      title={title}
      subtitle={subtitle}
      legend={legend}
      table={table}
      empty={empty}
      emptyMessage={emptyMessage ?? 'No values to chart.'}
      className={className}
    >
      {(width) => <BarPlot {...props} series={series} width={width} />}
    </ChartFrame>
  )
}

function BarPlot({
  title,
  categories,
  series,
  format,
  tickFormat,
  orientation = 'vertical',
  mode = 'grouped',
  showValues = false,
  diverging = false,
  highlight,
  referenceLine,
  height: heightProp,
  ariaLabel,
  width,
}: BarChartProps & { width: number }) {
  const n = categories.length
  const stacked = mode === 'stacked' && series.length > 1
  const vertical = orientation === 'vertical'
  const tf = tickFormat ?? format
  const labelsOn = showValues && !stacked

  // Value domain (always includes the zero baseline).
  const rows = categories.map((_, i) => series.map((s) => s.values[i]))
  let [lo, hi] = stacked ? stackExtent(rows) : (finiteExtent(series.flatMap((s) => s.values)) ?? [0, 1])
  if (referenceLine && isFiniteNumber(referenceLine.value)) {
    lo = Math.min(lo, referenceLine.value)
    hi = Math.max(hi, referenceLine.value)
  }

  const valueLabelW = labelsOn
    ? Math.max(...series.flatMap((s) => s.values.filter(isFiniteNumber).map((v) => approxTextWidth(format(v)))))
    : 0

  // Layout.
  const height = heightProp ?? (vertical ? 240 : n * 32 + 32)
  let left: number, right: number, top: number, bottom: number
  let nt
  if (vertical) {
    top = labelsOn ? 20 : 12
    bottom = 24
    const plotH0 = Math.max(40, height - top - bottom)
    nt = niceTicks(lo, hi, Math.max(2, Math.floor(plotH0 / 45)), { includeZero: true })
    left = Math.ceil(tickLabelWidth(nt.ticks, tf)) + 10
    right = 12
  } else {
    top = 8
    bottom = 24
    const catW = Math.max(...categories.map((c) => approxTextWidth(c)))
    left = Math.min(Math.ceil(catW) + 12, Math.round(width * 0.4))
    right = 12 + (labelsOn ? Math.ceil(valueLabelW) + 6 : 0)
    const plotW0 = Math.max(40, width - left - right)
    nt = niceTicks(lo, hi, Math.max(2, Math.floor(plotW0 / 80)), { includeZero: true })
  }
  const plotW = Math.max(40, width - left - right)
  const plotH = Math.max(20, height - top - bottom)
  const value = vertical ? linearScale(nt.domain, [top + plotH, top]) : linearScale(nt.domain, [left, left + plotW])
  const band = vertical ? bandScale(n, [left, left + plotW]) : bandScale(n, [top, top + plotH])
  const slots = groupedBarSlots(band.band, stacked ? 1 : series.length, {
    maxThickness: MARK.barMaxThickness,
    fill: vertical ? 0.8 : 0.75,
  })
  const base = value(0)
  const orient = vertical ? 'vertical' : 'horizontal'

  const colorFor = (si: number, v: number, ci: number) => {
    if (series.length === 1 && diverging) return v < 0 ? VIZ.divNeg : VIZ.divPos
    if (series.length === 1 && highlight !== undefined && categories[ci] !== highlight) return VIZ.deemphasis
    return seriesColor(slotFor(si, series[si].slot))
  }

  const marks: BarMark[] = []
  categories.forEach((_, ci) => {
    const b0 = band.start(ci)
    if (stacked) {
      const c = b0 + slots.offsets[0]
      for (const seg of stackValues(rows[ci])) {
        const p0 = value(seg.start)
        const p1 = value(seg.end)
        const span = applyStackGap({ from: p0, to: p1 }, seg.first)
        let d = ''
        if (span) {
          const r = barRect(span.from, span.to, c, slots.thickness, orient)
          d = roundedBarPath(r.x, r.y, r.w, r.h, dataEnd(span.from, span.to, orient), seg.outermost ? MARK.barRadius : 0)
        }
        const lo2 = Math.min(p0, p1) - 1
        const len = Math.max(6, Math.abs(p1 - p0) + 2)
        marks.push({
          cat: ci,
          series: seg.series,
          value: seg.value,
          d,
          fill: colorFor(seg.series, seg.value, ci),
          hit: vertical ? { x: b0, y: lo2, w: band.band, h: len } : { x: lo2, y: b0, w: len, h: band.band },
          tip: vertical ? { x: c + slots.thickness / 2, y: Math.min(p0, p1) } : { x: Math.max(p0, p1), y: c + slots.thickness / 2 },
        })
      }
      return
    }
    const hitSize = band.band / series.length
    series.forEach((s, si) => {
      const v = s.values[ci]
      if (!isFiniteNumber(v)) return
      const c = b0 + slots.offsets[si]
      const p1 = value(v)
      const r = barRect(base, p1, c, slots.thickness, orient)
      const d = v === 0 ? '' : roundedBarPath(r.x, r.y, r.w, r.h, dataEnd(base, p1, orient))
      const mark: BarMark = {
        cat: ci,
        series: si,
        value: v,
        d,
        fill: colorFor(si, v, ci),
        hit: vertical
          ? { x: b0 + si * hitSize, y: top, w: hitSize, h: plotH }
          : { x: left, y: b0 + si * hitSize, w: plotW, h: hitSize },
        tip: vertical ? { x: c + slots.thickness / 2, y: Math.min(base, p1) } : { x: Math.max(base, p1), y: c + slots.thickness / 2 },
      }
      if (labelsOn) {
        const text = format(v)
        const tw = approxTextWidth(text)
        if (vertical) {
          const ly = v >= 0 ? p1 - 5 : p1 + TICK_FONT + 3
          const fits = v >= 0 ? ly - TICK_FONT >= 0 : ly <= top + plotH - 2
          if (fits) mark.label = { x: c + slots.thickness / 2, y: ly, anchor: 'middle', text }
        } else {
          const lx = v >= 0 ? p1 + 5 : p1 - 5
          const fits = v >= 0 ? lx + tw <= width : lx - tw >= left
          if (fits) mark.label = { x: lx, y: c + slots.thickness / 2, anchor: v >= 0 ? 'start' : 'end', text }
        }
      }
      marks.push(mark)
    })
  })

  const cursor = useActiveIndex(marks.length)
  const hitTest = (px: number, py: number) => {
    const ci = band.indexAt(vertical ? px : py)
    let best = -1
    let bestD = Infinity
    marks.forEach((m, i) => {
      if (m.cat !== ci) return
      const dx = Math.max(m.hit.x - px, 0, px - (m.hit.x + m.hit.w))
      const dy = Math.max(m.hit.y - py, 0, py - (m.hit.y + m.hit.h))
      const dist = dx * dx + dy * dy
      if (dist < bestD) {
        bestD = dist
        best = i
      }
    })
    return best
  }

  const a = cursor.active
  let tip: PlotTip | null = null
  if (a >= 0 && marks[a]) {
    const m = marks[a]
    const rowsT = [{ key: series[m.series].key, value: format(m.value), label: series[m.series].label, color: m.fill }]
    tip = { ...m.tip, content: { title: categories[m.cat], rows: rowsT }, text: tipText(categories[m.cat], rowsT) }
  }

  const finiteMarks = marks.filter((m) => isFiniteNumber(m.value))
  const maxM = finiteMarks.reduce<BarMark | null>((b, m) => (!b || m.value > b.value ? m : b), null)
  const minM = finiteMarks.reduce<BarMark | null>((b, m) => (!b || m.value < b.value ? m : b), null)
  const summary =
    ariaLabel ??
    `${title}. ${stacked ? 'Stacked' : series.length > 1 ? 'Grouped' : ''} bar chart, ${n} categor${n === 1 ? 'y' : 'ies'}` +
      (series.length > 1 ? ` × ${series.length} series` : '') +
      (maxM && minM
        ? `. Highest ${categories[maxM.cat]} ${format(maxM.value)}; lowest ${categories[minM.cat]} ${format(minM.value)}.`
        : '.')

  const catLabels = [...categories]
  const stride = vertical ? labelStride(n, plotW, Math.min(Math.max(...catLabels.map((c) => approxTextWidth(c))), 90)) : 1

  return (
    <PlotSurface width={width} height={height} summary={summary} count={marks.length} cursor={cursor} hitTest={hitTest} tip={tip}>
      {vertical ? (
        <>
          <YGrid ticks={nt.ticks} scale={value} x0={left} x1={left + plotW} format={tf} />
          <CategoryLabelsX labels={catLabels} center={band.center} y={height - 6} stride={stride} maxWidth={band.band} />
        </>
      ) : (
        <>
          <XGrid ticks={nt.ticks} scale={value} y0={top} y1={top + plotH} format={tf} />
          <CategoryLabelsY labels={catLabels} center={band.center} x={left - 8} maxWidth={left - 12} />
        </>
      )}
      <g aria-hidden="true">
        {marks.map((m, i) =>
          m.d ? <path key={i} d={m.d} style={{ fill: m.fill }} opacity={a === i ? 0.78 : 1} /> : null,
        )}
      </g>
      {/* zero baseline */}
      {vertical ? (
        <line x1={left} x2={left + plotW} y1={Math.round(base) + 0.5} y2={Math.round(base) + 0.5} strokeWidth={1} className="stroke-viz-axis" aria-hidden="true" />
      ) : (
        <line y1={top} y2={top + plotH} x1={Math.round(base) + 0.5} x2={Math.round(base) + 0.5} strokeWidth={1} className="stroke-viz-axis" aria-hidden="true" />
      )}
      {referenceLine && (
        <RefLine
          line={referenceLine}
          orientation={vertical ? 'h' : 'v'}
          pos={value(referenceLine.value)}
          from={vertical ? left : top}
          to={vertical ? left + plotW : top + plotH}
        />
      )}
      <g aria-hidden="true">
        {marks.map((m, i) =>
          m.label ? (
            <text
              key={i}
              x={m.label.x}
              y={m.label.y}
              dy={vertical ? undefined : '0.32em'}
              textAnchor={m.label.anchor}
              fontSize={TICK_FONT}
              className="fill-viz-secondary viz-tabular"
            >
              {m.label.text}
            </text>
          ) : null,
        )}
      </g>
    </PlotSurface>
  )
}
