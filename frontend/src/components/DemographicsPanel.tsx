import { useState } from 'react'
import { fetchDemographics, type DemographicTrends, type TrendPoint, type TrendSection } from '../lib/api'
import { compactValue, linePath } from '../lib/chartGeometry'

interface DemographicsPanelProps {
  market: string
  submarket: string
  address: string
}

const W = 220
const H = 48

function TrendChart({
  title,
  source,
  points,
  kind,
}: {
  title: string
  source: string
  points: TrendPoint[] | undefined
  kind: 'count' | 'money' | 'percent'
}) {
  if (!points || points.length === 0) return null
  const values = points.map((p) => p.value)
  const first = points[0]
  const last = points[points.length - 1]
  const change = first.value !== 0 ? last.value / first.value - 1 : null
  return (
    <div className="rounded border border-slate-200 p-3">
      <div className="flex items-baseline justify-between">
        <div className="text-xs font-semibold text-slate-500">{title}</div>
        <span className="rounded bg-emerald-100 px-1.5 py-0.5 text-[10px] text-emerald-700">
          {source}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full" role="img" aria-label={title}>
        <path d={linePath(values, W, H)} fill="none" stroke="#0369a1" strokeWidth="1.5" />
      </svg>
      <div className="mt-1 flex justify-between text-[11px] text-slate-400">
        <span>
          {first.period}: {compactValue(first.value, kind)}
        </span>
        <span className="text-slate-600">
          {last.period}: {compactValue(last.value, kind)}
          {change !== null && (
            <span className={change >= 0 ? 'text-emerald-600' : 'text-red-600'}>
              {' '}
              ({change >= 0 ? '+' : ''}
              {(change * 100).toFixed(1)}%)
            </span>
          )}
        </span>
      </div>
    </div>
  )
}

function unavailableNote(section: TrendSection | undefined): string | null {
  return section && section.dataSource === 'unavailable' ? (section.note ?? 'unavailable') : null
}

/** Lazy demographics trend charts — fetched only when the user expands the
 *  section (four upstream APIs; no reason to hit them on every keystroke). */
export default function DemographicsPanel({ market, submarket, address }: DemographicsPanelProps) {
  const [trends, setTrends] = useState<DemographicTrends | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loadedFor, setLoadedFor] = useState<string | null>(null)

  const key = `${market}|${submarket}|${address}`

  function handleToggle(open: boolean) {
    if (!open || loading || loadedFor === key) return
    setLoading(true)
    setError(null)
    fetchDemographics(market, submarket, address)
      .then((t) => {
        setTrends(t)
        setLoadedFor(key)
      })
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load demographics'))
      .finally(() => setLoading(false))
  }

  const unavailable = trends
    ? (
        [
          ['census_acs', trends.population],
          ['bls', trends.employment],
          ['fhfa', trends.homePrices],
          ['bea', trends.income],
        ] as const
      )
        .flatMap(([source, section]) => {
          const note = unavailableNote(section)
          return note ? [{ source, note }] : []
        })
    : []

  return (
    <details onToggle={(e) => handleToggle((e.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer select-none text-xs font-medium text-slate-400 hover:text-slate-600">
        DEMOGRAPHIC TRENDS — population, employment, home prices, income
        {loading ? ' (loading…)' : ''}
      </summary>
      {error && <div className="mt-2 text-xs text-red-600">{error}</div>}
      {trends && (
        <div className="mt-2 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <TrendChart
            title="POPULATION (county)"
            source="census_acs"
            points={trends.population.population}
            kind="count"
          />
          <TrendChart
            title="MEDIAN HH INCOME (county)"
            source="census_acs"
            points={trends.population.medianHouseholdIncome}
            kind="money"
          />
          <TrendChart
            title="EMPLOYMENT (county)"
            source="bls"
            points={trends.employment.employmentLevel}
            kind="count"
          />
          <TrendChart
            title="UNEMPLOYMENT RATE"
            source="bls"
            points={trends.employment.unemploymentRatePct}
            kind="percent"
          />
          <TrendChart
            title={`HOME PRICE INDEX${trends.homePrices.metroName ? ` (${trends.homePrices.metroName})` : ''}`}
            source="fhfa"
            points={trends.homePrices.hpiIndex}
            kind="count"
          />
          <TrendChart
            title="PER-CAPITA INCOME (county)"
            source="bea"
            points={trends.income.perCapitaPersonalIncome}
            kind="money"
          />
        </div>
      )}
      {unavailable.length > 0 && (
        <details className="mt-1.5 text-[11px] text-slate-400">
          <summary className="cursor-pointer select-none">
            {unavailable.length} source(s) unavailable
          </summary>
          <ul className="mt-1 space-y-0.5 pl-4">
            {unavailable.map((u) => (
              <li key={u.source}>
                {u.source}: {u.note}
              </li>
            ))}
          </ul>
        </details>
      )}
    </details>
  )
}
