import { useEffect, useState } from 'react'
import { fetchPortfolio, type PortfolioRollup } from '../lib/api'
import { STAGE_LABELS } from '../lib/dealStages'
import type { DealStatus } from '../types/deal'
import ServerFileLink from '../components/ServerFileLink'
import { formatMoney } from '../lib/money'

interface PortfolioPageProps {
  active: boolean
}

const fmtMoney = (v: number) => formatMoney(v)
const fmtPct = (v: number | null) => (v === null ? '—' : `${(v * 100).toFixed(1)}%`)
const fmtX = (v: number | null) => (v === null ? '—' : `${v.toFixed(2)}x`)

const STATUS_LABELS: Record<string, string> = STAGE_LABELS as Record<DealStatus, string>

function Bars({ rows }: { rows: { label: string; equity: number }[] }) {
  const max = Math.max(...rows.map((r) => r.equity), 1)
  return (
    <div className="space-y-1">
      {rows.map((r) => (
        <div key={r.label} className="flex items-center gap-2 text-xs">
          <span className="w-32 truncate text-slate-600">{r.label}</span>
          <div className="h-3 flex-1 rounded bg-slate-100">
            <div className="h-3 rounded bg-sky-500" style={{ width: `${(r.equity / max) * 100}%` }} />
          </div>
          <span className="w-20 text-right tabular-nums text-slate-500">{fmtMoney(r.equity)}</span>
        </div>
      ))}
    </div>
  )
}

/** J15: portfolio roll-up over non-dead deals. */
export default function PortfolioPage({ active }: PortfolioPageProps) {
  const [data, setData] = useState<PortfolioRollup | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!active) return
    fetchPortfolio()
      .then((next) => {
        // Run 6: a later success clears an earlier failure (the error used
        // to stick until a reload).
        setError(null)
        setData(next)
      })
      .catch((e) => setError(e instanceof Error ? e.message : 'Could not load portfolio.'))
  }, [active])

  if (error) return <div className="text-sm text-red-600">{error}</div>
  if (!data) return <div className="text-sm text-slate-400">Loading portfolio…</div>
  if (data.dealCount === 0 && data.excludedCount === 0) {
    return <div className="text-sm text-slate-400">No non-dead deals to roll up yet.</div>
  }

  return (
    <div className="max-w-4xl space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-700">
          Portfolio — {data.dealCount} deal(s)
        </h2>
        <ServerFileLink
          href="/api/portfolio/export.csv"
          filename="portfolio.csv"
          className="rounded border border-slate-300 px-3 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          Export CSV
        </ServerFileLink>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {(
          [
            ['Equity committed', fmtMoney(data.totals.equity)],
            ['Total cost', fmtMoney(data.totals.totalCost)],
            ['Units', Math.round(data.totals.units).toLocaleString()],
            ['SF', Math.round(data.totals.sf).toLocaleString()],
            ['Blended levered IRR', fmtPct(data.blendedLeveredIrr)],
            ['Blended multiple', fmtX(data.blendedEquityMultiple)],
          ] as const
        ).map(([label, value]) => (
          <div key={label} className="rounded border border-slate-200 bg-white p-2">
            <div className="text-[10px] uppercase tracking-wide text-slate-400">{label}</div>
            <div className="text-lg font-semibold text-slate-800">{value}</div>
          </div>
        ))}
      </div>

      <div>
        <div className="mb-1 text-xs font-semibold text-slate-500">TOTALS BY DEAL TYPE</div>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-slate-400">
              <th className="pr-3 font-medium">Type</th>
              <th className="pr-3 text-right font-medium">Deals</th>
              <th className="pr-3 text-right font-medium">Equity</th>
              <th className="pr-3 text-right font-medium">Total cost</th>
              <th className="pr-3 text-right font-medium">Units</th>
              <th className="pr-3 text-right font-medium">SF</th>
            </tr>
          </thead>
          <tbody className="text-slate-600">
            {data.byDealType.map((t) => (
              <tr key={t.dealType}>
                <td className="pr-3 capitalize">{t.dealType}</td>
                <td className="pr-3 text-right tabular-nums">{t.count}</td>
                <td className="pr-3 text-right tabular-nums">{fmtMoney(t.equity)}</td>
                <td className="pr-3 text-right tabular-nums">{fmtMoney(t.totalCost)}</td>
                <td className="pr-3 text-right tabular-nums">{Math.round(t.units).toLocaleString()}</td>
                <td className="pr-3 text-right tabular-nums">{Math.round(t.sf).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div>
        <div className="mb-1 text-xs font-semibold text-slate-500">TOTALS BY STATUS</div>
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-slate-400">
              <th className="pr-3 font-medium">Status</th>
              <th className="pr-3 text-right font-medium">Deals</th>
              <th className="pr-3 text-right font-medium">Equity</th>
              <th className="pr-3 text-right font-medium">Total cost</th>
              <th className="pr-3 text-right font-medium">Units</th>
              <th className="pr-3 text-right font-medium">SF</th>
            </tr>
          </thead>
          <tbody className="text-slate-600">
            {data.byStatus.map((s) => (
              <tr key={s.status}>
                <td className="pr-3">{STATUS_LABELS[s.status] ?? s.status}</td>
                <td className="pr-3 text-right tabular-nums">{s.count}</td>
                <td className="pr-3 text-right tabular-nums">{fmtMoney(s.equity)}</td>
                <td className="pr-3 text-right tabular-nums">{fmtMoney(s.totalCost)}</td>
                <td className="pr-3 text-right tabular-nums">{Math.round(s.units).toLocaleString()}</td>
                <td className="pr-3 text-right tabular-nums">{Math.round(s.sf).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-500">EXPOSURE BY MARKET</div>
          <Bars rows={data.exposureByMarket.map((r) => ({ label: r.market, equity: r.equity }))} />
        </div>
        <div>
          <div className="mb-1 text-xs font-semibold text-slate-500">EXPOSURE BY ASSET CLASS</div>
          <Bars rows={data.exposureByAssetClass.map((r) => ({ label: r.assetClass, equity: r.equity }))} />
        </div>
      </div>

      <div>
        <div className="mb-1 text-xs font-semibold text-slate-500">CONCENTRATION (TOP MARKETS BY EQUITY)</div>
        <table className="text-xs">
          <tbody className="text-slate-600">
            {data.concentration.slice(0, 5).map((c) => (
              <tr key={c.market}>
                <td className="pr-4">{c.market}</td>
                <td className="pr-4 text-right tabular-nums">{fmtMoney(c.equity)}</td>
                <td className="text-right tabular-nums">{(c.sharePct * 100).toFixed(1)}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {data.excluded.length > 0 && (
        <div className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-700">
          <div className="font-medium">
            Excluded from the blend ({data.excluded.length}) — not yet computable:
          </div>
          <ul className="mt-1 list-disc pl-4">
            {data.excluded.map((d) => (
              <li key={d.id}>
                {d.name} — {d.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
