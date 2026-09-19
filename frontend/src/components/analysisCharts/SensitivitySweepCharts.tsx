import { useMemo } from 'react'
import { LineChart } from '../charts'
import { sweepLine } from '../../lib/analysisChartData'
import { formatOutputValue } from '../../lib/formatValue'
import type { OutputMetric } from '../../types/schema'
import type { SensitivityPoint } from '../../types/sensitivity'

const UNIT: Record<OutputMetric['type'], string> = {
  percent: '%',
  multiple: 'x',
  currency: '$',
  years: 'years',
  number: 'value',
}

function unitOf(metric: OutputMetric): string {
  return metric.id === 'developmentSpreadBps' ? 'bps' : UNIT[metric.type] ?? 'value'
}

/** One-driver sweep: each tracked output against the driver, one chart per
 *  output (outputs have different units — never a shared axis), with the
 *  deal's current result as the reference line when it's on the sweep. */
export function SensitivitySweepCharts({
  points,
  driverId,
  driverLabel,
  rawDriverValues,
  formatDriver,
  outputs,
  basePoint,
}: {
  points: SensitivityPoint[]
  driverId: string
  driverLabel: string
  /** Driver steps in engine units (a percent as a fraction). */
  rawDriverValues: number[]
  formatDriver: (raw: number) => string
  outputs: OutputMetric[]
  basePoint: SensitivityPoint | undefined
}) {
  const lines = useMemo(
    () => outputs.map((m) => ({ metric: m, values: sweepLine(points, driverId, rawDriverValues, m.id) })),
    [outputs, points, driverId, rawDriverValues],
  )
  if (lines.length === 0) return null
  return (
    <div className="mt-4 grid grid-cols-1 gap-x-8 gap-y-6 md:grid-cols-2">
      {lines.map(({ metric, values }) => {
        const fmt = (v: number) => formatOutputValue(metric, v)
        const baseRaw = basePoint ? Number(basePoint.outputs[metric.id]) : NaN
        return (
          <LineChart
            key={metric.id}
            title={`${metric.label} vs ${driverLabel}`}
            subtitle={`${unitOf(metric)} at each ${driverLabel.toLowerCase()} step`}
            x={rawDriverValues}
            xFormat={(v) => formatDriver(Number(v))}
            xLabel={driverLabel}
            series={[{ key: metric.id, label: metric.label, values, slot: 1 }]}
            format={fmt}
            referenceLine={Number.isFinite(baseRaw) ? { value: baseRaw, label: `Base ${fmt(baseRaw)}` } : undefined}
            height={200}
          />
        )
      })}
    </div>
  )
}
