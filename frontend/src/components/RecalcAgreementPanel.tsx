import { useEffect, useState } from 'react'
import { checkRecalcAgreement, type RecalcAgreement } from '../lib/api'
import type { MappingsById } from '../types/mapping'

function show(value: unknown): string {
  if (typeof value === 'number') return value.toLocaleString(undefined, { maximumFractionDigits: 6 })
  if (value === null || value === undefined) return '—'
  return String(value)
}

/**
 * Generate reads results back after a LibreOffice recalculation, and
 * LibreOffice's IRR and some functions can differ from Excel's. This
 * recalculates the UNMODIFIED template and compares each mapped output
 * with the value Excel saved in the file, so the user knows whether the
 * app's "template" results can stand in for Excel's for this model.
 */
export default function RecalcAgreementPanel({
  templateId,
  mappings,
  labelOf,
}: {
  templateId: string
  mappings: MappingsById
  labelOf: (fieldId: string) => string
}) {
  const [result, setResult] = useState<RecalcAgreement | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  // A different template or saved mapping makes an earlier answer meaningless.
  useEffect(() => {
    setResult(null)
    setError(null)
  }, [templateId, mappings])

  async function run() {
    setRunning(true)
    setError(null)
    try {
      setResult(await checkRecalcAgreement(templateId, mappings))
    } catch (err) {
      setResult(null)
      setError(err instanceof Error ? err.message : 'The check failed.')
    } finally {
      setRunning(false)
    }
  }

  const differing = result?.rows.filter((r) => !r.agrees) ?? []
  return (
    <div className="mt-4 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-slate-700">Does LibreOffice compute this template like Excel?</span>
        <button
          type="button"
          onClick={() => void run()}
          disabled={running}
          className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50 disabled:opacity-50"
        >
          {running ? 'Checking… (recalculating in LibreOffice)' : result ? 'Check again' : 'Check'}
        </button>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        Results read back from your template come from a LibreOffice recalculation. This recalculates the unmodified
        template and compares each mapped output with the value Excel last saved in the file.
      </p>
      {error && <div className="mt-2 text-xs text-red-600">{error}</div>}
      {result?.status === 'agrees' && (
        <div className="mt-2 text-xs text-emerald-700">
          LibreOffice matches Excel's saved values on all {result.rows.length} mapped output(s).
        </div>
      )}
      {result?.status === 'noOutputsMapped' && (
        <div className="mt-2 text-xs text-slate-600">Map at least one computed output to compare.</div>
      )}
      {result?.status === 'noSavedValues' && (
        <div className="mt-2 text-xs text-amber-700">
          This file has no values saved by Excel for the mapped outputs, so there's nothing to compare. Open it in
          Excel, save, and upload it again.
        </div>
      )}
      {result?.status === 'differs' && (
        <div className="mt-2 rounded border border-amber-200 bg-amber-50 px-2 py-1.5 text-xs text-amber-800">
          LibreOffice computes {differing.length} of {result.rows.length} mapped output(s) differently from Excel —
          treat those template results as LibreOffice's, not Excel's:
          <ul className="mt-1 list-disc pl-4">
            {differing.map((row) => (
              <li key={row.fieldId}>
                {labelOf(row.fieldId)}: Excel saved {show(row.excelValue)}, LibreOffice gets {show(row.libreOfficeValue)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
