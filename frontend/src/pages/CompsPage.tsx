import { useCallback, useEffect, useRef, useState } from 'react'
import {
  createComp,
  deleteComp,
  fetchComps,
  importCompsCsv,
  type Comp,
  type CompKind,
  type CompsImportResult,
} from '../lib/api'

interface CompsPageProps {
  /** Deal market from the input form — prefills the filter, nothing more. */
  dealMarket: string
}

const money = (v: number | null | undefined) =>
  typeof v === 'number' ? `$${Math.round(v).toLocaleString()}` : '—'
const pct = (v: number | null | undefined) =>
  typeof v === 'number' ? `${(v * 100).toFixed(2)}%` : '—'
const text = (v: string | null | undefined) => (v ? v : '—')

// Importable fields per kind (mirrors the backend's synonym tables).
const IMPORT_FIELDS: Record<CompKind, { id: string; label: string }[]> = {
  sale: [
    { id: 'name', label: 'Property name (required)' },
    { id: 'address', label: 'Address' },
    { id: 'market', label: 'Market' },
    { id: 'submarket', label: 'Submarket' },
    { id: 'propertyType', label: 'Property type' },
    { id: 'saleDate', label: 'Sale date' },
    { id: 'price', label: 'Sale price' },
    { id: 'units', label: 'Units' },
    { id: 'sf', label: 'SF / RBA' },
    { id: 'capRatePct', label: 'Cap rate' },
    { id: 'yearBuilt', label: 'Year built' },
    { id: 'notes', label: 'Notes' },
  ],
  rent: [
    { id: 'name', label: 'Property name (required)' },
    { id: 'address', label: 'Address' },
    { id: 'market', label: 'Market' },
    { id: 'submarket', label: 'Submarket' },
    { id: 'propertyType', label: 'Property type' },
    { id: 'asOf', label: 'As-of date' },
    { id: 'unitType', label: 'Unit type' },
    { id: 'avgRent', label: 'Avg rent (required)' },
    { id: 'avgSf', label: 'Avg unit SF' },
    { id: 'occupancyPct', label: 'Occupancy' },
    { id: 'yearBuilt', label: 'Year built' },
    { id: 'notes', label: 'Notes' },
  ],
}

const EMPTY_SALE = { name: '', market: '', price: '', units: '', capRatePct: '' }
const EMPTY_RENT = { name: '', market: '', avgRent: '', unitType: '', occupancyPct: '' }

export default function CompsPage({ dealMarket }: CompsPageProps) {
  const [kind, setKind] = useState<CompKind>('sale')
  const [marketFilter, setMarketFilter] = useState(dealMarket)
  const [comps, setComps] = useState<Comp[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // add-comp inline form (string state; parsed on save)
  const [draft, setDraft] = useState<Record<string, string>>(EMPTY_SALE)

  // CSV import state
  const [preview, setPreview] = useState<CompsImportResult | null>(null)
  const [csvText, setCsvText] = useState('')
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [importResult, setImportResult] = useState<CompsImportResult | null>(null)
  const [importing, setImporting] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    fetchComps(kind, marketFilter)
      .then(setComps)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load comps'))
      .finally(() => setLoading(false))
  }, [kind, marketFilter])

  useEffect(() => {
    const handle = setTimeout(load, 300)
    return () => clearTimeout(handle)
  }, [load])

  function switchKind(next: CompKind) {
    setKind(next)
    setDraft(next === 'sale' ? EMPTY_SALE : EMPTY_RENT)
    setPreview(null)
    setImportResult(null)
  }

  async function handleAdd() {
    const num = (s: string) => {
      const v = parseFloat(s.replace(/[^0-9.-]/g, ''))
      return Number.isFinite(v) ? v : undefined
    }
    const payload: Record<string, unknown> =
      kind === 'sale'
        ? {
            name: draft.name,
            market: draft.market,
            price: num(draft.price),
            units: num(draft.units),
            capRatePct: (() => {
              const v = num(draft.capRatePct)
              return v !== undefined && v > 1 ? v / 100 : v
            })(),
          }
        : {
            name: draft.name,
            market: draft.market,
            avgRent: num(draft.avgRent),
            unitType: draft.unitType,
            occupancyPct: (() => {
              const v = num(draft.occupancyPct)
              return v !== undefined && v > 1 ? v / 100 : v
            })(),
          }
    try {
      await createComp(kind, payload)
      setDraft(kind === 'sale' ? EMPTY_SALE : EMPTY_RENT)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to add comp')
    }
  }

  async function handleDelete(compId: string) {
    try {
      await deleteComp(kind, compId)
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete comp')
    }
  }

  async function handleFile(file: File) {
    const content = await file.text()
    setCsvText(content)
    setImportResult(null)
    setImporting(true)
    try {
      const result = await importCompsCsv({ kind, csvText: content })
      setPreview(result)
      setMapping(result.suggestedMapping ?? {})
    } catch (err) {
      setError(err instanceof Error ? err.message : 'CSV preview failed')
      setPreview(null)
    } finally {
      setImporting(false)
    }
  }

  async function handleImport() {
    setImporting(true)
    try {
      const result = await importCompsCsv({
        kind,
        csvText,
        mapping,
        defaultMarket: marketFilter || dealMarket,
      })
      setImportResult(result)
      setPreview(null)
      if (fileRef.current) fileRef.current.value = ''
      load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Import failed')
    } finally {
      setImporting(false)
    }
  }

  return (
    <div className="max-w-5xl space-y-4">
      <div className="flex items-center gap-3">
        <div className="flex rounded border border-slate-200">
          {(['sale', 'rent'] as const).map((k) => (
            <button
              key={k}
              onClick={() => switchKind(k)}
              className={`px-3 py-1.5 text-sm ${
                kind === k ? 'bg-slate-900 text-white' : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {k === 'sale' ? 'Sale comps' : 'Rent comps'}
            </button>
          ))}
        </div>
        <input
          value={marketFilter}
          onChange={(e) => setMarketFilter(e.target.value)}
          placeholder="Filter by market"
          className="rounded border border-slate-200 px-2 py-1.5 text-sm"
        />
        {loading && <span className="text-xs text-slate-400">Loading…</span>}
      </div>

      {error && <div className="text-sm text-red-600">{error}</div>}

      <div className="rounded border border-slate-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-left text-xs text-slate-400">
              <th className="px-3 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">Market</th>
              {kind === 'sale' ? (
                <>
                  <th className="px-3 py-2 font-medium">Sale date</th>
                  <th className="px-3 py-2 font-medium">Price</th>
                  <th className="px-3 py-2 font-medium">$/unit</th>
                  <th className="px-3 py-2 font-medium">Cap rate</th>
                </>
              ) : (
                <>
                  <th className="px-3 py-2 font-medium">Unit type</th>
                  <th className="px-3 py-2 font-medium">Avg rent</th>
                  <th className="px-3 py-2 font-medium">Occupancy</th>
                  <th className="px-3 py-2 font-medium">As of</th>
                </>
              )}
              <th className="px-3 py-2 font-medium">Source</th>
              <th className="px-3 py-2" />
            </tr>
          </thead>
          <tbody>
            {comps.map((comp) => (
              <tr key={comp.id} className="border-b border-slate-50 text-slate-700">
                <td className="px-3 py-1.5">{comp.name}</td>
                <td className="px-3 py-1.5">{text(comp.market)}</td>
                {kind === 'sale' ? (
                  <>
                    <td className="px-3 py-1.5">{text(comp.saleDate)}</td>
                    <td className="px-3 py-1.5">{money(comp.price)}</td>
                    <td className="px-3 py-1.5">{money(comp.pricePerUnit)}</td>
                    <td className="px-3 py-1.5">{pct(comp.capRatePct)}</td>
                  </>
                ) : (
                  <>
                    <td className="px-3 py-1.5">{text(comp.unitType)}</td>
                    <td className="px-3 py-1.5">{money(comp.avgRent)}</td>
                    <td className="px-3 py-1.5">{pct(comp.occupancyPct)}</td>
                    <td className="px-3 py-1.5">{text(comp.asOf)}</td>
                  </>
                )}
                <td className="px-3 py-1.5 text-xs text-slate-400">{comp.source}</td>
                <td className="px-3 py-1.5 text-right">
                  <button
                    onClick={() => handleDelete(comp.id)}
                    className="text-xs text-slate-400 hover:text-red-600"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {comps.length === 0 && !loading && (
              <tr>
                <td colSpan={8} className="px-3 py-6 text-center text-sm text-slate-400">
                  No {kind} comps{marketFilter ? ` matching '${marketFilter}'` : ''} — add one below
                  or import a Yardi Matrix CSV.
                </td>
              </tr>
            )}
            {/* inline add row */}
            <tr className="text-slate-600">
              <td className="px-3 py-1.5">
                <input
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  placeholder="New comp name"
                  className="w-full rounded border border-slate-200 px-2 py-1 text-sm"
                />
              </td>
              <td className="px-3 py-1.5">
                <input
                  value={draft.market}
                  onChange={(e) => setDraft({ ...draft, market: e.target.value })}
                  placeholder="Market"
                  className="w-full rounded border border-slate-200 px-2 py-1 text-sm"
                />
              </td>
              {kind === 'sale' ? (
                <>
                  <td className="px-3 py-1.5 text-xs text-slate-300">—</td>
                  <td className="px-3 py-1.5">
                    <input
                      value={draft.price}
                      onChange={(e) => setDraft({ ...draft, price: e.target.value })}
                      placeholder="Price"
                      className="w-full rounded border border-slate-200 px-2 py-1 text-sm"
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <input
                      value={draft.units}
                      onChange={(e) => setDraft({ ...draft, units: e.target.value })}
                      placeholder="Units"
                      className="w-full rounded border border-slate-200 px-2 py-1 text-sm"
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <input
                      value={draft.capRatePct}
                      onChange={(e) => setDraft({ ...draft, capRatePct: e.target.value })}
                      placeholder="Cap % e.g. 5.25"
                      className="w-full rounded border border-slate-200 px-2 py-1 text-sm"
                    />
                  </td>
                </>
              ) : (
                <>
                  <td className="px-3 py-1.5">
                    <input
                      value={draft.unitType}
                      onChange={(e) => setDraft({ ...draft, unitType: e.target.value })}
                      placeholder="e.g. 1BR"
                      className="w-full rounded border border-slate-200 px-2 py-1 text-sm"
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <input
                      value={draft.avgRent}
                      onChange={(e) => setDraft({ ...draft, avgRent: e.target.value })}
                      placeholder="Avg rent"
                      className="w-full rounded border border-slate-200 px-2 py-1 text-sm"
                    />
                  </td>
                  <td className="px-3 py-1.5">
                    <input
                      value={draft.occupancyPct}
                      onChange={(e) => setDraft({ ...draft, occupancyPct: e.target.value })}
                      placeholder="Occ % e.g. 95"
                      className="w-full rounded border border-slate-200 px-2 py-1 text-sm"
                    />
                  </td>
                  <td className="px-3 py-1.5 text-xs text-slate-300">—</td>
                </>
              )}
              <td className="px-3 py-1.5" />
              <td className="px-3 py-1.5 text-right">
                <button
                  onClick={handleAdd}
                  disabled={!draft.name.trim()}
                  className="rounded border border-emerald-600 px-2 py-0.5 text-xs text-emerald-700 hover:bg-emerald-50 disabled:opacity-40"
                >
                  Add
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="rounded border border-slate-200 bg-white p-4">
        <div className="text-sm font-semibold text-slate-600">Import CSV (Yardi Matrix export)</div>
        <div className="mt-1 text-xs text-slate-400">
          Two-step: pick a file to preview the detected columns, adjust the mapping, then import.
          Rows without the required fields are skipped with a warning.
        </div>
        <input
          ref={fileRef}
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) void handleFile(file)
          }}
          className="mt-2 block text-xs text-slate-500"
        />
        {importing && <div className="mt-2 text-xs text-slate-400">Working…</div>}

        {preview && (
          <div className="mt-3 space-y-3">
            <div className="text-xs text-slate-500">
              {preview.rowCount} row(s) detected. Map the fields, then import:
            </div>
            <div className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3">
              {IMPORT_FIELDS[kind].map((field) => (
                <label key={field.id} className="flex items-center justify-between gap-2 text-xs">
                  <span className="text-slate-500">{field.label}</span>
                  <select
                    value={mapping[field.id] ?? ''}
                    onChange={(e) => {
                      const next = { ...mapping }
                      if (e.target.value) next[field.id] = e.target.value
                      else delete next[field.id]
                      setMapping(next)
                    }}
                    className="rounded border border-slate-200 px-1 py-0.5"
                  >
                    <option value="">— skip —</option>
                    {(preview.columns ?? []).map((col) => (
                      <option key={col} value={col}>
                        {col}
                      </option>
                    ))}
                  </select>
                </label>
              ))}
            </div>
            {preview.sampleRows && preview.sampleRows.length > 0 && (
              <div className="max-h-40 overflow-auto rounded border border-slate-100">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr className="text-left text-slate-400">
                      {(preview.columns ?? []).map((col) => (
                        <th key={col} className="px-2 py-1 font-medium">
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.sampleRows.map((row, i) => (
                      <tr key={i} className="border-t border-slate-50 text-slate-600">
                        {(preview.columns ?? []).map((col) => (
                          <td key={col} className="px-2 py-1">
                            {row[col]}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <button
              onClick={handleImport}
              disabled={importing || !mapping.name}
              className="rounded bg-emerald-600 px-3 py-1.5 text-sm text-white hover:bg-emerald-700 disabled:opacity-40"
            >
              Import {preview.rowCount} row(s)
            </button>
            {!mapping.name && (
              <span className="ml-2 text-xs text-amber-600">
                Map the property-name column to enable import.
              </span>
            )}
          </div>
        )}

        {importResult && (
          <div className="mt-3 text-xs text-slate-600">
            Imported {importResult.imported} comp(s).
            {importResult.warnings.length > 0 && (
              <ul className="mt-1 list-disc pl-4 text-amber-600">
                {importResult.warnings.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>

      <div className="text-xs text-slate-400">
        Comps feed the benchmark flags on the Deal Inputs page (subject rent vs rent-comps median,
        exit cap vs sale-comps median) once at least 3 comps exist in the deal's market.
      </div>
    </div>
  )
}
