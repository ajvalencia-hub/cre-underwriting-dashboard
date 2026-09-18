import { useEffect, useMemo, useState } from 'react'
import {
  computeNative,
  exportNativeModel,
  fetchExternalTools,
  fetchMappingProfile,
  generateWorkbook,
  previewMapping,
  type DebtBlock,
  type GpEconomics,
} from '../lib/api'
import { checkForGenerate, withSharedTargets, type GenerateCheckResult } from '../lib/mappingCoverage'
import { flattenFields, visibleFields } from '../lib/schemaFields'
import type { InputSchema } from '../types/schema'
import { GeneratePreflight, GenerateReport } from './GenerateCheck'
import type { Statement } from '../lib/cashflowStatement'
import { saveOutput } from '../lib/saveOutput'
import type { TemplateSummary } from '../types/template'

interface GeneratePanelProps {
  schema: InputSchema
  template: TemplateSummary | null
  mappingProfileId: string | null
  /** The Template tab has edits not yet saved to the profile Generate uses. */
  mappingUnsaved: boolean
  values: Record<string, unknown>
  onGenerated?: (outputs: Record<string, unknown>) => void
  onReviewMapping: () => void
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
  schema,
  template,
  mappingProfileId,
  mappingUnsaved,
  values,
  onGenerated,
  onReviewMapping,
  onComputedNative,
}: GeneratePanelProps) {
  const [generating, setGenerating] = useState(false)
  const [checking, setChecking] = useState(false)
  const [preflight, setPreflight] = useState<GenerateCheckResult | null>(null)
  const [result, setResult] = useState<{
    check: GenerateCheckResult | null
    warnings: string[]
    outputsReturned: number
    recalcRequested: boolean
    savedTo: string | null
  } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [recalc, setRecalc] = useState(true)
  // null until known; false = LibreOffice isn't installed, so a template's
  // results can't be read back (the workbook itself is still correct).
  const [recalcAvailable, setRecalcAvailable] = useState<boolean | null>(null)
  useEffect(() => {
    fetchExternalTools()
      .then((t) => setRecalcAvailable(t.libreoffice.available))
      .catch(() => setRecalcAvailable(null))
  }, [])
  const labels = useMemo(() => new Map([...flattenFields(schema), ...schema.outputs].map((f) => [f.id, f.label])), [schema])
  const labelOf = (id: string) => labels.get(id) ?? id
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
      await saveOutput(blob, 'native-model.xlsx')
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

  /** What Generate will do with this deal under the SAVED profile (the
   *  one the server uses). Null if the check itself couldn't run. */
  async function runCheck(): Promise<GenerateCheckResult | null> {
    if (!template || !mappingProfileId) return null
    try {
      const profile = await fetchMappingProfile(mappingProfileId)
      const rows = withSharedTargets(await previewMapping(template.id, profile.mappings, values))
      return checkForGenerate(rows, new Set(visibleFields(schema, values).map((f) => f.id)))
    } catch {
      return null
    }
  }

  async function handleGenerate(skipCheck = false) {
    if (!template || !mappingProfileId) return
    setError(null)
    setResult(null)
    let check: GenerateCheckResult | null = preflight
    if (!skipCheck) {
      setChecking(true)
      check = await runCheck()
      setChecking(false)
      if (check && (check.issues.length > 0 || check.unmappedWithValue.length > 0)) {
        setPreflight(check)
        return
      }
    }
    setPreflight(null)
    setGenerating(true)
    const recalcRequested = recalc && recalcAvailable !== false
    try {
      const { blob, filename, warnings, outputs } = await generateWorkbook({
        templateId: template.id,
        mappingProfileId,
        values,
        recalc: recalcRequested,
      })
      const saved = await saveOutput(blob, filename)
      setResult({
        check,
        warnings,
        outputsReturned: Object.keys(outputs).length,
        recalcRequested,
        savedTo: saved.status === 'saved' ? saved.path : saved.status === 'downloaded' ? `downloaded ${saved.filename}` : null,
      })
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
          <label
            className="flex items-center gap-1 text-xs text-slate-500"
            title={
              recalcAvailable === false
                ? "LibreOffice isn't installed, so your template's results can't be read back into the app. The saved workbook still recalculates when opened in Excel. See Settings → External tools."
                : "Recalculate the filled-in workbook with LibreOffice and show your template's own results in the summary."
            }
          >
            <input
              type="checkbox"
              checked={recalc && recalcAvailable !== false}
              disabled={recalcAvailable === false}
              onChange={(e) => setRecalc(e.target.checked)}
            />
            {recalcAvailable === false ? 'Recalculate & read back (needs LibreOffice)' : 'Recalculate & read back results'}
          </label>
          <button
            onClick={() => void handleGenerate()}
            disabled={!ready || generating || checking}
            className="rounded bg-emerald-600 px-4 py-1.5 text-sm text-white hover:bg-emerald-700 disabled:opacity-40"
          >
            {checking ? 'Checking mapping…' : generating ? 'Generating…' : 'Generate workbook…'}
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
      {preflight && (
        <GeneratePreflight
          check={preflight}
          labelOf={labelOf}
          onGenerateAnyway={() => void handleGenerate(true)}
          onReview={() => {
            setPreflight(null)
            onReviewMapping()
          }}
          onCancel={() => setPreflight(null)}
        />
      )}
      {result && (
        <GenerateReport
          check={result.check}
          labelOf={labelOf}
          serverWarnings={result.warnings}
          recalcRequested={result.recalcRequested}
          outputsReturned={result.outputsReturned}
          savedTo={result.savedTo}
          recalcUnavailable={recalcAvailable === false}
        />
      )}
    </div>
  )
}
