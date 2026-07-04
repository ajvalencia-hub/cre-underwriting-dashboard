import { useState } from 'react'
import { computeNative, generateWorkbook, type DebtBlock } from '../lib/api'
import type { Statement } from '../lib/cashflowStatement'
import type { TemplateSummary } from '../types/template'

interface GeneratePanelProps {
  template: TemplateSummary | null
  mappingProfileId: string | null
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

export default function GeneratePanel({
  template,
  mappingProfileId,
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

  const ready = Boolean(template && mappingProfileId)

  async function handleComputeNative() {
    setComputing(true)
    setComputeError(null)
    setComputeWarnings([])
    try {
      const { outputs, warnings, debt, irrConvention, statement } = await computeNative(values, {
        detail: true,
      })
      setComputeWarnings(warnings)
      setDebtBlock(debt)
      onComputedNative?.(outputs, debt, irrConvention, statement ?? null)
    } catch (err) {
      setComputeError(err instanceof Error ? err.message : 'Native compute failed')
      setDebtBlock(null)
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
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
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
            <>Upload a template and save a mapping profile under "1. Template &amp; Mapping".</>
          )}
          {template && !mappingProfileId && (
            <>
              Template <strong>{template.filename}</strong> uploaded — save a mapping profile
              first.
            </>
          )}
          {template && mappingProfileId && (
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
              {debtBlock.stress
                .filter(
                  (c) =>
                    (c.rateBumpBps === 0 && c.noiHaircutPct === 0) ||
                    (c.rateBumpBps > 0 && c.noiHaircutPct === 0) ||
                    (c.rateBumpBps === 0 && c.noiHaircutPct > 0) ||
                    (c.rateBumpBps === 200 && c.noiHaircutPct === 0.1),
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
