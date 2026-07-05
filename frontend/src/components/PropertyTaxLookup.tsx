import { useState } from 'react'
import { lookupPropertyTax, type PropertyTaxLookupResult } from '../lib/api'

interface PropertyTaxLookupProps {
  address: string
  purchasePrice: number | null
  assessmentRatio: number | null
  /** Annual real estate taxes as currently modeled (flat field or the sum of
   *  detail tax lines) — used only for the caution comparison. */
  modeledTaxes: number | null
  onApplyMillage: (millageRate: number) => void
}

const money = (v: number) => `$${Math.round(v).toLocaleString()}`
const pct = (v: number) => `${(v * 100).toFixed(3)}%`

/** County assessor lookup (Miami-Dade). Display + one explicit apply action —
 *  nothing is written to inputs without a click. */
export default function PropertyTaxLookup({
  address,
  purchasePrice,
  assessmentRatio,
  modeledTaxes,
  onApplyMillage,
}: PropertyTaxLookupProps) {
  const [query, setQuery] = useState(address)
  const [result, setResult] = useState<PropertyTaxLookupResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleLookup() {
    setLoading(true)
    setError(null)
    try {
      setResult(
        await lookupPropertyTax({
          query: query.trim() || address,
          purchasePrice,
          assessmentRatio,
        }),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Lookup failed')
      setResult(null)
    } finally {
      setLoading(false)
    }
  }

  const projected = result?.projection?.projectedAnnualTaxes ?? null
  const underModeled =
    projected !== null && modeledTaxes !== null && modeledTaxes < projected * 0.95

  return (
    <div className="my-2 rounded border border-slate-100 bg-slate-50 p-2 text-xs">
      <div className="flex items-center gap-2">
        <span className="shrink-0 font-medium text-slate-500">Assessor lookup</span>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Address or folio (Miami-Dade)"
          className="w-full rounded border border-slate-200 px-2 py-1"
        />
        <button
          onClick={handleLookup}
          disabled={loading || !(query.trim() || address.trim())}
          className="shrink-0 rounded border border-sky-600 px-2 py-1 text-sky-700 hover:bg-sky-50 disabled:opacity-40"
        >
          {loading ? 'Looking up…' : 'Look up'}
        </button>
      </div>
      {error && <div className="mt-1 text-red-600">{error}</div>}
      {result && result.dataSource === 'unavailable' && (
        <div className="mt-1 text-slate-500">{result.note}</div>
      )}
      {result && result.dataSource !== 'unavailable' && (
        <div className="mt-2 space-y-1 text-slate-600">
          <div>
            {result.jurisdiction}
            {result.folio ? ` · folio ${result.folio}` : ''}
            {result.asOf ? ` · ${result.asOf} roll` : ''}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-0.5">
            {result.assessedValue !== null && (
              <span>Assessed: {money(result.assessedValue)}</span>
            )}
            {result.taxableValue !== null && <span>Taxable: {money(result.taxableValue)}</span>}
            {result.currentTaxes !== null && (
              <span>Current taxes: {money(result.currentTaxes)}/yr</span>
            )}
            {typeof result.adValoremTaxes === 'number' && (
              <span>Ad valorem: {money(result.adValoremTaxes)}</span>
            )}
            {typeof result.nonAdValorem === 'number' && (
              <span>Non-ad-valorem: {money(result.nonAdValorem)}</span>
            )}
            {result.millageRate !== null && <span>Millage: {pct(result.millageRate)}</span>}
          </div>
          {result.note && <div className="text-amber-600">△ {result.note}</div>}
          {result.projection && (
            <div>
              Reassessed at sale: {money(result.projection.projectedAssessedValue)} assessed (
              {Math.round(result.projection.assessmentRatio * 100)}% of price) →{' '}
              {typeof result.projection.projectedAdValorem === 'number' &&
              (result.projection.carriedNonAdValorem ?? 0) > 0 ? (
                <>
                  {money(result.projection.projectedAdValorem)} ad valorem +{' '}
                  {money(result.projection.carriedNonAdValorem ?? 0)} non-ad-valorem ={' '}
                </>
              ) : null}
              <strong>{money(result.projection.projectedAnnualTaxes)}/yr</strong> projected taxes
            </div>
          )}
          {underModeled && projected !== null && modeledTaxes !== null && (
            <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-amber-700">
              △ Modeled taxes ({money(modeledTaxes)}/yr) are below the reassessed projection (
              {money(projected)}/yr) — consider enabling reassessed taxes.
            </div>
          )}
          {result.millageRate !== null && (
            <button
              onClick={() => onApplyMillage(result.millageRate as number)}
              className="mt-1 rounded border border-emerald-600 px-2 py-0.5 text-emerald-700 hover:bg-emerald-50"
            >
              Apply millage rate to inputs
            </button>
          )}
        </div>
      )}
    </div>
  )
}
