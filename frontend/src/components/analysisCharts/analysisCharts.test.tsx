import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { HoldSweepCharts, LeaseExpiryChart } from './CashFlowCharts'
import { ForwardCurveChart } from './ForwardCurveChart'
import { MonteCarloCharts } from './MonteCarloCharts'
import { DevCostChart, NoiSplitChart } from './QuickScreenCharts'
import { ScenarioMetricCharts } from './ScenarioMetricCharts'

// Server-render smoke tests: each section chart renders (or stays quiet)
// without leaking NaN/undefined into the markup.
const clean = (html: string) => expect(html).not.toMatch(/NaN|Infinity|undefined/)

describe('analysis charts', () => {
  it('hold sweep splits IRR and multiple into two charts', () => {
    const html = renderToStaticMarkup(
      <HoldSweepCharts
        modeledHoldYears={5}
        rows={[
          { holdYear: 4, leveredIrr: 0.1, unleveredIrr: 0.07, equityMultiple: 1.4 },
          { holdYear: 5, leveredIrr: 0.12, unleveredIrr: 0.08, equityMultiple: 1.6 },
        ]}
      />,
    )
    clean(html)
    expect(html).toContain('IRR by exit year')
    expect(html).toContain('Equity multiple by exit year')
    expect(html).toContain('modeled hold: Y5')
  })
  it('lease expiry renders bars', () => {
    const html = renderToStaticMarkup(
      <LeaseExpiryChart schedule={[{ year: 2027, sfExpiring: 1000, pctOfSf: 0.2, pctOfRent: 0.25 }]} />,
    )
    clean(html)
    expect(html).toContain('Rent rolling by year')
  })
  it('Monte Carlo shows tiles and the empty state when every trial failed', () => {
    const stats = { p5: 0.05, p25: 0.08, p50: 0.1, p75: 0.12, p95: 0.15, mean: 0.1, min: 0, max: 0.2 }
    const html = renderToStaticMarkup(
      <MonteCarloCharts leveredIrr={stats} bins={[]} hurdleIrr={0.12} probIrrNegative={0} probIrrBelowHurdle={1} />,
    )
    clean(html)
    expect(html).toContain('Median levered IRR (P50)')
    expect(html).toContain('every trial failed')
  })
  it('quick screen charts render and stay quiet on bad data', () => {
    clean(
      renderToStaticMarkup(
        <DevCostChart results={{ hardCosts: 10, softCosts: 2, contingency: 1, developerFee: 1, financingCost: 1 }} landCost={3} />,
      ),
    )
    expect(
      renderToStaticMarkup(
        <NoiSplitChart results={{ stabilizedNoi: NaN, annualDebtService: 1, leveredCashFlow: 1, minDscr: null }} />,
      ),
    ).toBe('')
  })
  it('scenario charts group by unit and render nothing without values', () => {
    const metrics = [
      { id: 'leveredIrr', label: 'Levered IRR', type: 'percent' as const },
      { id: 'equityMultiple', label: 'Equity Multiple', type: 'multiple' as const },
    ]
    const html = renderToStaticMarkup(
      <ScenarioMetricCharts
        metrics={metrics}
        scenarios={[
          { id: 'a', name: 'Base', slot: 1, values: { leveredIrr: 0.1, equityMultiple: 1.5 } },
          { id: 'b', name: 'Upside', slot: 3, values: { leveredIrr: 0.14, equityMultiple: null } },
        ]}
      />,
    )
    clean(html)
    expect(html).toContain('var(--viz-series-3)')
    expect(html).toContain('Multiples by scenario')
    expect(
      renderToStaticMarkup(
        <ScenarioMetricCharts metrics={metrics} scenarios={[{ id: 'a', name: 'A', slot: 1, values: { leveredIrr: null } }]} />,
      ),
    ).toBe('')
  })
  it('forward curve renders only for a floating loan', () => {
    const common = { floorPct: 0.03, forwardCurve: [{ month: 13, indexPct: 0.035 }], rateCapStrikePct: 0.05, rateCapTermMonths: 24, holdPeriodYears: 3 }
    const html = renderToStaticMarkup(<ForwardCurveChart rateMode="floating" currentIndexPct={0.043} {...common} />)
    clean(html)
    expect(html).toContain('Cap 5.00%')
    expect(renderToStaticMarkup(<ForwardCurveChart rateMode="fixed" currentIndexPct={0.043} {...common} />)).toBe('')
  })
})
