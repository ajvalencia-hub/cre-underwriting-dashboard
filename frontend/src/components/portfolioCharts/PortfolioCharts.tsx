import { useMemo } from 'react'
import { BarChart, ScatterChart, StatTileRow } from '../charts'
import type { PortfolioRollup } from '../../lib/api'
import { foldTail, irrVsEquitySeries } from '../../lib/portfolioChartData'
import { CARD, fmtMoney, fmtMoneyCompact, fmtMultiple, fmtPct1 } from './format'

/** Headline numbers: the KPI row replaces the old boxed tiles (same six
 *  figures, plus the deal count with the excluded ones as a hint). */
export function PortfolioKpis({ data }: { data: PortfolioRollup }) {
  const tiles = [
    { key: 'equity', label: 'Equity committed', value: fmtMoneyCompact(data.totals.equity), hint: fmtMoney(data.totals.equity) },
    {
      key: 'irr',
      label: 'Blended levered IRR',
      value: data.blendedLeveredIrr === null ? '—' : fmtPct1(data.blendedLeveredIrr),
      hint: 'Equity-weighted',
    },
    {
      key: 'em',
      label: 'Blended multiple',
      value: data.blendedEquityMultiple === null ? '—' : fmtMultiple(data.blendedEquityMultiple),
      hint: 'Equity-weighted',
    },
    {
      key: 'deals',
      label: 'Deals',
      value: String(data.dealCount),
      hint: data.excludedCount > 0 ? `${data.excludedCount} not yet computable` : 'All computable',
    },
    { key: 'cost', label: 'Total cost', value: fmtMoneyCompact(data.totals.totalCost), hint: fmtMoney(data.totals.totalCost) },
    { key: 'units', label: 'Units', value: Math.round(data.totals.units).toLocaleString() },
    { key: 'sf', label: 'SF', value: Math.round(data.totals.sf).toLocaleString() },
  ]
  return (
    <div className={CARD}>
      <StatTileRow tiles={tiles} />
    </div>
  )
}

function ExposureBar({ title, rows }: { title: string; rows: { label: string; value: number }[] }) {
  const folded = useMemo(() => foldTail(rows, 8), [rows])
  return (
    <div className={CARD}>
      <BarChart
        title={title}
        subtitle="Committed equity, $ · largest first"
        orientation="horizontal"
        categories={folded.map((r) => r.label)}
        series={[{ key: 'equity', label: 'Equity', values: folded.map((r) => r.value), slot: 1 }]}
        format={fmtMoney}
        tickFormat={fmtMoneyCompact}
        showValues
        categoryLabel={title.endsWith('market') ? 'Market' : 'Asset class'}
        emptyMessage="No equity to chart yet."
      />
    </div>
  )
}

/** Equity exposure by market and by asset class (sorted; >8 folds to Other). */
export function PortfolioExposure({ data }: { data: PortfolioRollup }) {
  const markets = useMemo(() => data.exposureByMarket.map((r) => ({ label: r.market, value: r.equity })), [data])
  const classes = useMemo(
    () => data.exposureByAssetClass.map((r) => ({ label: r.assetClass, value: r.equity })),
    [data],
  )
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <ExposureBar title="Equity exposure by market" rows={markets} />
      <ExposureBar title="Equity exposure by asset class" rows={classes} />
    </div>
  )
}

/** Return vs size: each computed deal's levered IRR against its committed
 *  equity, colored by dealflow, with the portfolio's blended IRR marked. */
export function PortfolioIrrScatter({ data }: { data: PortfolioRollup }) {
  const { series, missing } = useMemo(() => irrVsEquitySeries(data.deals), [data])
  const blend = data.blendedLeveredIrr
  return (
    <div className={CARD}>
      <ScatterChart
        title="Levered IRR vs equity"
        subtitle={`Levered IRR, % (y) by committed equity, $ (x), one dot per deal${
          series.length === 1 ? ` (${series[0].label.toLowerCase()})` : ''
        }${
          missing > 0 ? ` · ${missing} deal(s) without an IRR not shown` : ''
        }`}
        series={series}
        xLabel="Equity"
        yLabel="Levered IRR"
        xFormat={fmtMoney}
        yFormat={fmtPct1}
        xTickFormat={fmtMoneyCompact}
        includeZeroX
        height={240}
        referenceY={blend === null ? undefined : { value: blend, label: `Blended ${fmtPct1(blend)}` }}
        emptyMessage="No deal has a levered IRR yet."
      />
    </div>
  )
}
