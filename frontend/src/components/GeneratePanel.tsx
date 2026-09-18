import { useState } from 'react'
import {
  computeNative,
  exportNativeModel,
  generateWorkbook,
  type DebtBlock,
  type GpEconomics,
} from '../lib/api'
import type { Statement } from '../lib/cashflowStatement'
import { openSavedFile, revealInFinder, saveFile } from '../lib/platform'
import { toastSaved } from '../lib/toast'
import type { TemplateSummary } from '../types/template'

interface GeneratePanelProps {
  template: TemplateSummary | null
  mappingProfileId: string | null
  /** The Template tab has edits not yet saved to the profile Generate uses. */
  mappingUnsaved: boolean
  values: Record<string, unknown>
  onGenerated?: (outputs: Record<string, unknown>) => void
  onComputedNative?: (
    outputs: Record<string, number | string>,
    debt: DebtBlock | null,
    irrConvention?: 'periodic_monthly' | 'xirr',
    statement?: Statement | null,
  ) => void
}

const fmtMoney = (v: number) => `$${Math.round(v).toLocaleString()}`

/** J5: tiny inline sparkline of the floating loan's all-in monthly rate. */
function RateSparkline({ rates }: { rates: number[] }) {
  if (rates.length < 2) return null
  const min = Math.min(...rates)
  const max = Math.max(...rates)
  const span = max - min || 1
  const w = 140
  const h = 22
  const points = rates
    .map((r, i) => `${((i / (rates.length - 1)) * w).toFixed(1)},${(h - 3 - ((r - min) / span) * (h - 6)).toFixed(1)}`)
    .join(' ')
  return (
    <svg
      width={w}
      height={h}
      className="shrink-0"
      aria-label={`All-in rate ${(min * 100).toFixed(2)}%–${(max * 100).toFixed(2)}% over the hold`}
    >
      <title>
        All-in rate {(min * 100).toFixed(2)}%–{(max * 100).toFixed(2)}% over the hold
      </title>
      <polyline points={points} fill="none" stroke="#0284c7" strokeWidth="1.5" />
    </svg>
  )
}

export default function GeneratePanel({
  template,
  mappingProfileId,
  mappingUnsaved,
  values,
  onGenerated,
  onComputedNative,
}: GeneratePanelProps) {
  const [generating, setGenerating] = useState(false)
  const [result, setResult] = useState<{ warnings: string[]; writtenCount: number } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [recalc, setRecalc] = useState(true)
  const [computing, setComputing] = useState(false)
  const [computeWarnings, setComputeWarnings] = useState<string[]>([])
  const [computeError, setComputeError] = useState<string | null>(null)
  const [debtBlock, setDebtBlock] = useState<DebtBlock | null>(null)
  const [gpEconomics, setGpEconomics] = useState<GpEconomics | null>(null)
  const [exportingModel, setExportingModel] = useState(false)

  const ready = Boolean(template && mappingProfileId) && !mappingUnsaved

  async function handleExportModel() {
    setExportingModel(true)
    setComputeError(null)
    try {
      const { blob, warnings } = await exportNativeModel(values)
      toastSaved(await saveFile(blob, 'native-model.xlsx'), { reveal: revealInFinder, open: openSavedFile })
      if (warnings.length > 0) setComputeWarnings(warnings)
    } catch (err) {
      setComputeError(err instanceof Error ? err.message : 'Excel model export failed')
    } finally {
      setExportingModel(false)
    }
  }

  async function handleComputeNative() {
    setComputing(true)
    setComputeError(null)
    setComputeWarnings([])
    try {
      const response = await computeNative(values, { detail: true })
      const { outputs, warnings, debt, irrConvention, statement } = response
      setComputeWarnings(warnings)
      setDebtBlock(debt)
      setGpEconomics(response.gpEconomics ?? null)
      onComputedNative?.(outputs, debt, irrConvention, statement ?? null)
    } catch (err) {
      setComputeError(err instanceof Error ? err.message : 'Native compute failed')
      setDebtBlock(null)
      setGpEconomics(null)
    } finally {
      setComputing(false)
    }
  }

  async function handleGenerate() {
    if (!template || !mappingProfileId) return
    setGenerating(true)
    setError(null)
    setResult(null)
    try {
      const { blob, filename, warnings, writtenCount, outputs } = await generateWorkbook({
        templateId: template.id,
        mappingProfileId,
        values,
        recalc,
      })
      toastSaved(await saveFile(blob, filename), { reveal: revealInFinder, open: openSavedFile })
      setResult({ warnings, writtenCount })
      if (Object.keys(outputs).length > 0) onGenerated?.(outputs)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Generate failed')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="sticky bottom-0 -mx-8 border-t border-slate-200 bg-white px-8 py-3">
      <div className="flex max-w-3xl items-center justify-between gap-4">
        <div className="text-xs text-slate-500">
          {!template && (
            <>Upload a template and save a mapping profile under "2. Template &amp; Mapping".</>
          )}
          {template && !mappingProfileId && (
            <>
              Template <strong>{template.filename}</strong> uploaded — save a mapping profile
              first.
            </>
          )}
          {template && mappingProfileId && mappingUnsaved && (
            <span className="text-amber-700">
              Unsaved mapping changes in <strong>2. Template &amp; Mapping</strong> — save them
              before generating (Generate uses the saved profile).
            </span>
          )}
          {template && mappingProfileId && !mappingUnsaved && (
            <>
              Template <strong>{template.filename}</strong> &middot; mapping profile ready.
            </>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <button
            onClick={handleComputeNative}
            disabled={computing}
            title="Compute all return metrics with the built-in pro-forma engine — no template or mapping required."
            className="rounded border border-sky-600 px-4 py-1.5 text-sm text-sky-700 hover:bg-sky-50 disabled:opacity-40"
          >
            {computing ? 'Computing…' : 'Compute (native)'}
          </button>
          <button
            onClick={handleExportModel}
            disabled={exportingModel}
            title="Download a formula-live Excel model of this deal — no template needed. Supports acquisitions and developments (incl. opex line detail); lease-level rolls and waterfall tiers are refused with the reason."
            className="rounded border border-slate-400 px-4 py-1.5 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-40"
          >
            {exportingModel ? 'Exporting…' : 'Export Excel model'}
          </button>
          <label className="flex items-center gap-1 text-xs text-slate-500">
            <input
              type="checkbox"
              checked={recalc}
              onChange={(e) => setRecalc(e.target.checked)}
            />
            Recalculate on server
          </label>
          <button
            onClick={handleGenerate}
            disabled={!ready || generating}
            className="rounded bg-emerald-600 px-4 py-1.5 text-sm text-white hover:bg-emerald-700 disabled:opacity-40"
          >
            {generating ? 'Generating…' : 'Generate & Download'}
          </button>
        </div>
      </div>
      {error && <div className="mt-2 text-xs text-red-600">{error}</div>}
      {computeError && <div className="mt-2 text-xs text-red-600">{computeError}</div>}
      {computeWarnings.length > 0 && (
        <ul className="mt-2 list-disc pl-4 text-xs text-amber-600">
          {computeWarnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
      {debtBlock && (
        <div className="mt-3 max-w-3xl">
          <div className="text-xs font-semibold tracking-wide text-slate-500">
            DEBT SIZING — {fmtMoney(debtBlock.loanAmount)} · governed by{' '}
            {debtBlock.governingConstraint}
          </div>
          {debtBlock.rate && (
            <div className="mt-1 flex items-center gap-3 text-xs text-slate-500">
              <span>
                Floating: {debtBlock.rate.index} + {Math.round(debtBlock.rate.spreadBps)}bps ·
                initial {(debtBlock.rate.initialRatePct * 100).toFixed(2)}%
                {debtBlock.rate.floorPct !== undefined &&
                  ` · floor ${(debtBlock.rate.floorPct * 100).toFixed(2)}%`}
                {debtBlock.rate.cap &&
                  ` · cap ${(debtBlock.rate.cap.strikePct * 100).toFixed(2)}% strike, ${debtBlock.rate.cap.termMonths}mo`}
              </span>
              <RateSparkline rates={debtBlock.rate.monthlyRatePct} />
            </div>
          )}
          <table className="mt-1 text-xs">
            <thead>
              <tr className="text-left text-slate-400">
                <th className="pr-3 font-medium">Stress</th>
                <th className="pr-3 font-medium">DSCR</th>
                <th className="pr-3 font-medium">Refi proceeds</th>
                <th className="pr-3 font-medium">Shortfall</th>
              </tr>
            </thead>
            <tbody>
              {debtBlock.rate?.cap?.dscrAtStrike != null && (
                // J5: for a capped floater the generic rate-bump rows are a
                // fiction the borrower paid to escape — show the strike row.
                <tr className="text-slate-600">
                  <td className="pr-3">
                    At cap strike ({(debtBlock.rate.cap.strikeAllInPct * 100).toFixed(2)}% all-in)
                  </td>
                  <td
                    className={`pr-3 ${debtBlock.rate.cap.dscrAtStrike < 1 ? 'text-red-600' : ''}`}
                  >
                    {debtBlock.rate.cap.dscrAtStrike.toFixed(2)}x
                  </td>
                  <td className="pr-3">—</td>
                  <td className="pr-3">—</td>
                </tr>
              )}
              {debtBlock.stress
                .filter(
                  (c) =>
                    (c.rateBumpBps === 0 && c.noiHaircutPct === 0) ||
                    (!debtBlock.rate?.cap &&
                      ((c.rateBumpBps > 0 && c.noiHaircutPct === 0) ||
                        (c.rateBumpBps === 200 && c.noiHaircutPct === 0.1))) ||
                    (c.rateBumpBps === 0 && c.noiHaircutPct > 0),
                )
                .map((c) => (
                  <tr key={`${c.rateBumpBps}-${c.noiHaircutPct}`} className="text-slate-600">
                    <td className="pr-3">
                      {c.rateBumpBps === 0 && c.noiHaircutPct === 0
                        ? 'Base'
                        : [
                            c.rateBumpBps > 0 ? `+${c.rateBumpBps}bps` : null,
                            c.noiHaircutPct > 0 ? `NOI −${Math.round(c.noiHaircutPct * 100)}%` : null,
                          ]
                            .filter(Boolean)
                            .join(' · ')}
                    </td>
                    <td className={`pr-3 ${c.dscr !== null && c.dscr < 1 ? 'text-red-600' : ''}`}>
                      {c.dscr === null ? '—' : `${c.dscr.toFixed(2)}x`}
                    </td>
                    <td className="pr-3">{fmtMoney(c.refiProceeds)}</td>
                    <td className={`pr-3 ${c.refiShortfall > 0 ? 'text-amber-600' : ''}`}>
                      {c.refiShortfall > 0 ? fmtMoney(c.refiShortfall) : '—'}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          {debtBlock.insuranceStress && debtBlock.insuranceStress.length > 0 && (
            <table className="mt-2 text-xs">
              <thead>
                <tr className="text-left text-slate-400">
                  <th className="pr-3 font-medium">Insurance stress</th>
                  <th className="pr-3 font-medium">Min DSCR</th>
                  <th className="pr-3 font-medium">Levered CF Δ / yr</th>
                </tr>
              </thead>
              <tbody>
                {debtBlock.insuranceStress.map((row) => (
                  <tr key={row.bumpPct} className="text-slate-600">
                    <td className="pr-3">+{Math.round(row.bumpPct * 100)}%</td>
                    <td className={`pr-3 ${row.minDscr !== null && row.minDscr < 1 ? 'text-red-600' : ''}`}>
                      {row.minDscr === null ? '—' : `${row.minDscr.toFixed(2)}x`}
                    </td>
                    <td className="pr-3 text-red-600">{fmtMoney(row.leveredCfDeltaAnnual)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
      {gpEconomics && (
        <div className="mt-3 max-w-3xl text-xs">
          <div className="font-semibold tracking-wide text-slate-500">
            GP COMPENSATION — {fmtMoney(gpEconomics.totalCompensation)} total
          </div>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-slate-600">
            {gpEconomics.acquisitionFee > 0 && (
              <span>Acquisition fee {fmtMoney(gpEconomics.acquisitionFee)}</span>
            )}
            {gpEconomics.developerFee > 0 && (
              <span>Developer fee {fmtMoney(gpEconomics.developerFee)}</span>
            )}
            {gpEconomics.assetMgmtFees > 0 && (
              <span>AM fees {fmtMoney(gpEconomics.assetMgmtFees)}</span>
            )}
            <span>Promote {fmtMoney(gpEconomics.promote)}</span>
            <span>Pro-rata (net) {fmtMoney(gpEconomics.proRataNet)}</span>
          </div>
        </div>
      )}
      {result && (
        <div className="mt-2 text-xs text-slate-500">
          Wrote {result.writtenCount} field(s).
          {result.warnings.length > 0 && (
            <ul className="mt-1 list-disc pl-4 text-amber-600">
              {result.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
