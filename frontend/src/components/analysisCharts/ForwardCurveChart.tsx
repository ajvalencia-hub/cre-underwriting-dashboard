import { useMemo } from 'react'
import { LineChart } from '../charts'
import { forwardCurvePath } from '../../lib/analysisChartData'
import { pct1, pct2 } from './format'

/** J5 floating debt: the index path the engine will read (step function,
 *  current index before the first curve point) and, when the floor or cap
 *  changes it, the index the loan actually pays. Client-side from the
 *  inputs only — no compute. */
export function ForwardCurveChart({
  rateMode,
  currentIndexPct,
  floorPct,
  forwardCurve,
  rateCapStrikePct,
  rateCapTermMonths,
  holdPeriodYears,
}: {
  rateMode: unknown
  currentIndexPct: unknown
  floorPct: unknown
  forwardCurve: unknown
  rateCapStrikePct: unknown
  rateCapTermMonths: unknown
  holdPeriodYears: unknown
}) {
  const path = useMemo(() => {
    const hold = typeof holdPeriodYears === 'number' && holdPeriodYears > 0 ? Math.round(holdPeriodYears * 12) : 0
    const lastPoint = Array.isArray(forwardCurve)
      ? Math.max(0, ...forwardCurve.map((r) => (r && typeof r.month === 'number' ? r.month : 0)))
      : 0
    const months = Math.min(600, hold || Math.max(60, lastPoint + 12))
    return forwardCurvePath(
      { rateMode, currentIndexPct, floorPct, forwardCurve, rateCapStrikePct, rateCapTermMonths },
      months,
    )
  }, [rateMode, currentIndexPct, floorPct, forwardCurve, rateCapStrikePct, rateCapTermMonths, holdPeriodYears])
  if (!path) return null
  const notes = [
    path.floor !== null ? `floor ${pct2(path.floor)}` : null,
    path.strike !== null
      ? `cap strike ${pct2(path.strike)} through M${Math.trunc(Number(rateCapTermMonths))}`
      : null,
  ].filter(Boolean)
  const reference =
    path.strike !== null
      ? { value: path.strike, label: `Cap ${pct2(path.strike)}` }
      : path.floor !== null
        ? { value: path.floor, label: `Floor ${pct2(path.floor)}` }
        : undefined
  return (
    <div className="py-2">
      <LineChart
        title="Index path over the hold"
        subtitle={`% by month (step function)${notes.length ? ` · ${notes.join(' · ')}` : ''}`}
        x={path.months}
        xFormat={(m) => `M${m}`}
        xLabel="Month"
        series={[
          { key: 'index', label: 'Index (curve)', values: path.index, slot: 1 },
          ...(path.bites
            ? [{ key: 'paid', label: 'Index the loan pays (after floor/cap)', values: path.effective, slot: 2 as const }]
            : []),
        ]}
        format={pct2}
        tickFormat={pct1}
        referenceLine={reference}
        height={180}
      />
    </div>
  )
}
