import { useEffect, useState } from 'react'
import { fetchMarketContext, type BenchmarkResult, type BenchmarkVerdict } from '../lib/api'
import type { DataSection, MarketContext } from '../types/marketContext'

interface MarketContextPanelProps {
  market: string
  submarket: string
  assetClass: string
  benchmarks?: BenchmarkResult | null
  benchmarksLoading?: boolean
}

const VERDICT_STYLE: Record<BenchmarkVerdict, { icon: string; className: string }> = {
  ok: { icon: '✓', className: 'border-emerald-200 bg-emerald-50 text-emerald-700' },
  caution: { icon: '△', className: 'border-amber-200 bg-amber-50 text-amber-700' },
  warning: { icon: '✕', className: 'border-red-200 bg-red-50 text-red-700' },
}

const METRIC_LABELS: Record<string, string> = {
  rent_vs_market: 'Subject rent vs market',
  rent_growth_vs_hpa: 'Rent growth assumption',
  expense_ratio: 'Expense ratio',
  flood_zone: 'Flood zone',
  employment_trend: 'Employment trend',
  rent_vs_comps: 'Subject rent vs comps DB',
  exit_cap_vs_comps: 'Exit cap vs sale comps',
}

function BenchmarkChecklist({ result }: { result: BenchmarkResult }) {
  if (result.flags.length === 0 && result.unavailable.length === 0) return null
  return (
    <div>
      <div className="mb-1 text-xs font-medium text-slate-400">
        ADDRESS BENCHMARKS — context only, never applied to inputs
      </div>
      <div className="space-y-1.5">
        {result.flags.map((flag) => {
          const style = VERDICT_STYLE[flag.verdict]
          return (
            <div
              key={flag.metric}
              className={`rounded-md border px-3 py-2 text-xs ${style.className}`}
            >
              <span className="font-semibold">
                {style.icon} {METRIC_LABELS[flag.metric] ?? flag.metric}
              </span>{' '}
              — {flag.explanation}{' '}
              <span className="opacity-70">
                [{flag.source}
                {flag.asOf ? `, as of ${flag.asOf}` : ''}]
              </span>
            </div>
          )
        })}
      </div>
      {result.unavailable.length > 0 && (
        <details className="mt-1.5 text-[11px] text-slate-400">
          <summary className="cursor-pointer select-none">
            {result.unavailable.length} source(s) unavailable
          </summary>
          <ul className="mt-1 space-y-0.5 pl-4">
            {result.unavailable.map((u) => (
              <li key={u.source}>
                {u.source}: {u.note}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

const DEBOUNCE_MS = 500

function pct(v: number): string {
  return `${(v * 100).toFixed(2)}%`
}

function money(v: number): string {
  return `$${Math.round(v).toLocaleString()}`
}

type FieldFormat = 'percent' | 'money' | 'text'

const FIELD_LABELS: Record<string, { label: string; format: FieldFormat }> = {
  population: { label: 'Population', format: 'text' },
  medianHouseholdIncome: { label: 'Median HH Income', format: 'money' },
  acsYear: { label: 'ACS Year', format: 'text' },
  unemploymentRatePct: { label: 'Unemployment Rate', format: 'percent' },
  perCapitaPersonalIncome: { label: 'Per Capita Personal Income', format: 'money' },
  personalIncomeGrowthYoY: { label: 'Personal Income Growth YoY', format: 'percent' },
  hpiYoYAppreciation: { label: 'Home Price Appreciation YoY', format: 'percent' },
  metroName: { label: 'Metro', format: 'text' },
  fmrStudio: { label: 'FMR Studio', format: 'money' },
  fmr1BR: { label: 'FMR 1BR', format: 'money' },
  fmr2BR: { label: 'FMR 2BR', format: 'money' },
  fmr3BR: { label: 'FMR 3BR', format: 'money' },
  year: { label: 'Year', format: 'text' },
  mortgageRate30yrPct: { label: '30yr Mortgage Rate', format: 'percent' },
  treasuryYield10yrPct: { label: '10yr Treasury Yield', format: 'percent' },
  mortgageRateAsOf: { label: 'Mortgage Rate As Of', format: 'text' },
  treasuryYieldAsOf: { label: 'Treasury Yield As Of', format: 'text' },
  floodZone: { label: 'Flood Zone', format: 'text' },
  zoneSubtype: { label: 'Zone Subtype', format: 'text' },
  description: { label: 'Description', format: 'text' },
  asOf: { label: 'As Of', format: 'text' },
}

function formatFieldValue(key: string, value: unknown): string {
  const field = FIELD_LABELS[key]
  if (value === undefined || value === null) return '—'
  if (!field || field.format === 'text') return String(value)
  const num = Number(value)
  if (Number.isNaN(num)) return String(value)
  return field.format === 'percent' ? pct(num) : money(num)
}

function DataSectionCard({ title, section }: { title: string; section: DataSection }) {
  const unavailable = section.dataSource === 'unavailable'
  const entries = Object.entries(section).filter(
    ([k]) => k !== 'dataSource' && k !== 'note' && FIELD_LABELS[k],
  )

  return (
    <div className="rounded border border-slate-200 p-3">
      <div className="flex items-center justify-between">
        <div className="text-xs font-semibold text-slate-500">{title}</div>
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] ${
            unavailable ? 'bg-slate-100 text-slate-400' : 'bg-emerald-100 text-emerald-700'
          }`}
        >
          {unavailable ? 'not configured' : section.dataSource}
        </span>
      </div>
      {unavailable ? (
        <div className="mt-2 text-xs text-slate-400">{section.note}</div>
      ) : (
        <div className="mt-2 space-y-1 text-sm">
          {entries.map(([key, value]) => (
            <div key={key} className="flex justify-between">
              <span className="text-slate-500">{FIELD_LABELS[key].label}</span>
              <span className="text-slate-800">{formatFieldValue(key, value)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function MarketContextPanel({
  market,
  submarket,
  assetClass,
  benchmarks = null,
  benchmarksLoading = false,
}: MarketContextPanelProps) {
  const [context, setContext] = useState<MarketContext | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!market.trim()) {
      setContext(null)
      return
    }
    const handle = setTimeout(() => {
      setLoading(true)
      setError(null)
      fetchMarketContext(market, submarket, assetClass)
        .then(setContext)
        .catch((err) => setError(err instanceof Error ? err.message : 'Could not load market context'))
        .finally(() => setLoading(false))
    }, DEBOUNCE_MS)
    return () => clearTimeout(handle)
  }, [market, submarket, assetClass])

  if (!market.trim()) {
    return (
      <div className="mb-4 rounded-md border border-dashed border-slate-300 bg-white p-4 text-sm text-slate-400">
        Enter a market in Deal Basics to see comparable market context.
      </div>
    )
  }

  return (
    <div className="mb-4 rounded-md border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold tracking-wide text-slate-500">
          MARKET CONTEXT — {market}
          {submarket ? ` / ${submarket}` : ''}
          {assetClass ? ` (${assetClass})` : ''}
        </h2>
        {(loading || benchmarksLoading) && <span className="text-xs text-slate-400">Loading…</span>}
      </div>

      {error && <div className="mt-2 text-sm text-red-600">{error}</div>}

      {benchmarks && (
        <div className="mt-3">
          <BenchmarkChecklist result={benchmarks} />
        </div>
      )}

      {context && (
        <div className="mt-3 space-y-4">
          {context.location.resolved ? (
            <div className="text-xs text-slate-400">
              Resolved to {context.location.countyName ? `${context.location.countyName} County, ` : ''}
              {context.location.cbsaName ?? ''}
            </div>
          ) : (
            <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-600">
              Could not geocode this market — real data sections below will show as unavailable. Try a more
              specific market/submarket name.
            </div>
          )}

          <div>
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              <strong>Placeholder</strong> — comps and pricing trends below are illustrative, not real market
              data (no free public source exists for these).
            </div>
            <div className="mt-2 grid grid-cols-4 gap-4 text-sm">
              <div>
                <div className="text-xs font-medium text-slate-400">CAP RATE RANGE</div>
                <div className="mt-0.5 text-slate-800">
                  {pct(context.pricingTrends.capRateLow)} – {pct(context.pricingTrends.capRateHigh)}
                </div>
              </div>
              <div>
                <div className="text-xs font-medium text-slate-400">
                  PRICE RANGE ({context.pricingTrends.priceUnitLabel})
                </div>
                <div className="mt-0.5 text-slate-800">
                  {money(context.pricingTrends.priceLow)} – {money(context.pricingTrends.priceHigh)}
                </div>
              </div>
              <div>
                <div className="text-xs font-medium text-slate-400">RENT GROWTH YoY</div>
                <div className="mt-0.5 text-slate-800">{pct(context.rentTrends.rentGrowthYoY)}</div>
              </div>
              <div>
                <div className="text-xs font-medium text-slate-400">VACANCY</div>
                <div className="mt-0.5 text-slate-800">{pct(context.rentTrends.vacancyPct)}</div>
              </div>
            </div>
          </div>

          <div>
            <div className="text-xs font-medium text-slate-400">COMPARABLES (placeholder)</div>
            <table className="mt-1 w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-500">
                  <th className="py-1 font-medium">Name</th>
                  <th className="py-1 font-medium">Type</th>
                  <th className="py-1 font-medium">Date</th>
                  <th className="py-1 font-medium">Price</th>
                  <th className="py-1 font-medium">Cap Rate</th>
                </tr>
              </thead>
              <tbody>
                {context.comps.map((comp, i) => (
                  <tr key={i} className="border-b border-slate-50">
                    <td className="py-1">{comp.name}</td>
                    <td className="py-1 capitalize text-slate-500">{comp.type}</td>
                    <td className="py-1 text-slate-500">{comp.date}</td>
                    <td className="py-1">
                      {money(comp.pricePerUnit)} <span className="text-slate-400">{comp.priceUnitLabel}</span>
                    </td>
                    <td className="py-1">{pct(comp.capRate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div>
            <div className="mb-1 text-xs font-medium text-slate-400">
              REAL DATA — FROM FREE PUBLIC SOURCES (CENSUS, BLS, BEA, FRED, HUD, FHFA, FEMA)
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <DataSectionCard title="Demographics" section={context.demographics} />
              <DataSectionCard title="Labor Market" section={context.laborMarket} />
              <DataSectionCard title="Housing" section={context.housing} />
              <DataSectionCard title="Macro Rates" section={context.macro} />
              <DataSectionCard title="Site Risk" section={context.siteRisk} />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
