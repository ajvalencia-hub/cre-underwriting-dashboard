import { useMemo } from 'react'
import { BarChart, LineChart } from '../charts'
import {
  annualOperating,
  cumulativeLevered,
  hasAnyDebt,
  loanBalanceByYear,
  paybackLabel,
  renovationByMonth,
  holdSweepSeries,
  type HoldSweepRowLike,
} from '../../lib/analysisChartData'
import type { Statement } from '../../lib/cashflowStatement'
import { count, money, moneyCompact, mult, pct1, pct2 } from './format'

/** Annual operations, coverage, leverage and the equity J-curve for the
 *  computed statement. Derived with useMemo from the statement the tab
 *  already holds — never triggers a compute. */
export function CashFlowCharts({ statement, blended }: { statement: Statement; blended: boolean }) {
  const ops = useMemo(() => annualOperating(statement), [statement])
  const loan = useMemo(() => (hasAnyDebt(statement) ? loanBalanceByYear(statement) : null), [statement])
  const cumulative = useMemo(() => cumulativeLevered(statement), [statement])
  const payback = paybackLabel(cumulative)
  const note = blended ? ' · blended (all components)' : ''

  return (
    <div className="grid grid-cols-1 gap-x-8 gap-y-6 lg:grid-cols-2">
      {ops.hasOperations && (
        <LineChart
          title="Operations by year"
          subtitle={`$ per year · levered cash flow excludes the exit sale${note}`}
          x={ops.years}
          xLabel="Year"
          series={[
            { key: 'noi', label: 'NOI', values: ops.noi, slot: 1 },
            ...(ops.hasDebt ? [{ key: 'ds', label: 'Debt service', values: ops.debtService, slot: 2 as const }] : []),
            { key: 'lev', label: 'Levered cash flow', values: ops.leveredOperating, slot: 3 },
          ]}
          format={money}
          tickFormat={moneyCompact}
          includeZero
        />
      )}
      {ops.hasOperations && ops.hasDebt && (
        <LineChart
          title="Debt service coverage by year"
          subtitle={`DSCR (x) = annual NOI ÷ annual debt service${note}`}
          x={ops.years}
          xLabel="Year"
          series={[{ key: 'dscr', label: 'DSCR', values: ops.dscr, slot: 1 }]}
          format={mult}
          referenceLine={{ value: 1.25, label: '1.25x' }}
        />
      )}
      {loan && (
        <LineChart
          title="Loan balance"
          subtitle="$ outstanding at close and each year end"
          x={loan.x}
          xLabel="Period"
          series={[{ key: 'bal', label: 'Loan balance', values: loan.values, slot: 1 }]}
          format={money}
          tickFormat={moneyCompact}
          area
        />
      )}
      <LineChart
        title="Cumulative levered cash flow"
        subtitle={`$ to equity, running total at close and each year end, sale included · ${
          payback ? `paid back in ${payback}` : 'not paid back within the hold'
        }`}
        x={cumulative.x}
        xLabel="Period"
        series={[{ key: 'cum', label: 'Cumulative levered cash flow', values: cumulative.values, slot: 1 }]}
        format={money}
        tickFormat={moneyCompact}
        referenceLine={{ value: 0, label: 'Break-even' }}
        area
      />
    </div>
  )
}

/** Hold-period sweep: IRRs and the equity multiple are different units, so
 *  they get two charts on their own axes (the old chart used two scales). */
export function HoldSweepCharts({ rows, modeledHoldYears }: { rows: HoldSweepRowLike[]; modeledHoldYears: number }) {
  const s = useMemo(() => holdSweepSeries(rows), [rows])
  const modeled = `modeled hold: Y${modeledHoldYears}`
  return (
    <div className="grid grid-cols-1 gap-x-8 gap-y-6 lg:grid-cols-2">
      <LineChart
        title="IRR by exit year"
        subtitle={`% annualized · ${modeled}`}
        x={s.x}
        xLabel="Exit year"
        series={[
          { key: 'lev', label: 'Levered IRR', values: s.levered, slot: 1 },
          { key: 'unlev', label: 'Unlevered IRR', values: s.unlevered, slot: 2 },
        ]}
        format={pct2}
        tickFormat={pct1}
      />
      <LineChart
        title="Equity multiple by exit year"
        subtitle={`x of equity invested · ${modeled}`}
        x={s.x}
        xLabel="Exit year"
        series={[{ key: 'em', label: 'Equity multiple', values: s.equityMultiple, slot: 1 }]}
        format={mult}
      />
    </div>
  )
}

/** Lease expirations: share of rent rolling each year. */
export function LeaseExpiryChart({
  schedule,
}: {
  schedule: { year: number; sfExpiring: number; pctOfSf: number; pctOfRent: number }[]
}) {
  return (
    <BarChart
      title="Rent rolling by year"
      subtitle="% of in-place rent expiring each year"
      categories={schedule.map((r) => String(r.year))}
      categoryLabel="Year"
      series={[{ key: 'rent', label: '% of rent', values: schedule.map((r) => r.pctOfRent), slot: 1 }]}
      format={pct1}
      showValues={schedule.length <= 12}
      height={200}
    />
  )
}

/** J1 renovation program progress (units), complete vs in progress. */
export function RenovationChart({ renovation }: { renovation: NonNullable<Statement['renovation']> }) {
  const r = useMemo(() => renovationByMonth(renovation), [renovation])
  return (
    <BarChart
      title="Renovation progress"
      subtitle="Units per operating month"
      categories={r.months}
      categoryLabel="Month"
      mode="stacked"
      series={[
        { key: 'done', label: 'Complete', values: r.complete, slot: 1 },
        { key: 'wip', label: 'In progress', values: r.inProgress, slot: 2 },
      ]}
      format={count}
      height={180}
    />
  )
}
