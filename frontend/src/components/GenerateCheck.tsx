import { TONE_CLASS, statusInfo, willWrite, type GenerateCheckResult } from '../lib/mappingCoverage'
import type { MappingPreviewRow } from '../types/mappingPreview'

function IssueList({ rows, labelOf }: { rows: MappingPreviewRow[]; labelOf: (id: string) => string }) {
  return (
    <ul className="mt-1 max-h-48 space-y-1 overflow-auto">
      {rows.map((row) => {
        const info = statusInfo(row)
        return (
          <li key={row.fieldId} className="text-xs">
            <span className={`mr-1.5 inline-block rounded border px-1 py-px text-[10px] ${TONE_CLASS[info.tone]}`}>
              {info.label}
            </span>
            <strong className="font-medium text-slate-700">{labelOf(row.fieldId)}</strong>
            {row.resolvedRef && <span className="ml-1 font-mono text-[10px] text-slate-400">{row.resolvedRef}</span>}
            {row.message && <span className="ml-1 text-slate-500">— {row.message}</span>}
          </li>
        )
      })}
    </ul>
  )
}

/** Shown before generating when the mapping would not reproduce this deal. */
export function GeneratePreflight({
  check,
  labelOf,
  onGenerateAnyway,
  onReview,
  onCancel,
}: {
  check: GenerateCheckResult
  labelOf: (id: string) => string
  onGenerateAnyway: () => void
  onReview: () => void
  onCancel: () => void
}) {
  return (
    <div className="mt-2 max-w-3xl rounded-md border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700">
      <div className="font-medium">
        Before generating: {check.issues.length > 0 && `${check.issues.length} mapped field(s) won't come through as shown`}
        {check.issues.length > 0 && check.unmappedWithValue.length > 0 && ' · '}
        {check.unmappedWithValue.length > 0 &&
          `${check.unmappedWithValue.length} field(s) with values aren't mapped (the template uses its own numbers)`}
      </div>
      {check.issues.length > 0 && <IssueList rows={check.issues} labelOf={labelOf} />}
      <div className="mt-2 flex gap-2">
        <button onClick={onReview} className="rounded bg-slate-900 px-3 py-1 text-xs text-white hover:bg-slate-700">
          Review mapping
        </button>
        <button
          onClick={onGenerateAnyway}
          className="rounded border border-amber-400 px-3 py-1 text-xs hover:bg-amber-100"
        >
          Generate anyway
        </button>
        <button onClick={onCancel} className="px-2 py-1 text-xs underline">
          Cancel
        </button>
      </div>
    </div>
  )
}

/** After generating: exactly which inputs were written, which weren't, and
 *  whether the template's results came back. */
export function GenerateReport({
  check,
  labelOf,
  serverWarnings,
  recalcRequested,
  outputsReturned,
  savedTo,
  recalcUnavailable,
}: {
  check: GenerateCheckResult | null
  labelOf: (id: string) => string
  serverWarnings: string[]
  recalcRequested: boolean
  outputsReturned: number
  savedTo: string | null
  /** LibreOffice isn't installed, so no read-back was possible. */
  recalcUnavailable: boolean
}) {
  const written = check ? check.rows.filter(willWrite) : []
  const needsLook = check ? check.issues : []
  const recalcWarning = serverWarnings.find((w) => w.startsWith('Server-side recalc skipped'))
  const otherWarnings = serverWarnings.filter((w) => w !== recalcWarning)

  return (
    <div className="mt-2 max-w-3xl space-y-1.5 text-xs text-slate-600">
      <div>
        <strong className="text-emerald-700">Workbook generated</strong>
        {savedTo && <span className="ml-1 text-slate-500">— {savedTo}</span>}. Wrote {written.length} input(s)
        {check && ` of ${check.rows.filter((r) => !r.isOutput && r.status !== 'unmapped').length} mapped`}.
      </div>
      {recalcRequested && outputsReturned > 0 && (
        <div className="text-emerald-700">
          Read back {outputsReturned} result(s) from the recalculated template — shown in the summary panel.
        </div>
      )}
      {!recalcRequested && recalcUnavailable && (
        <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-amber-700">
          Your template's own results aren't shown in the app: LibreOffice isn't installed (Settings → External
          tools). Open the saved workbook in Excel to see them — it recalculates on open.
        </div>
      )}
      {recalcRequested && outputsReturned === 0 && (
        <div className="rounded border border-amber-200 bg-amber-50 px-2 py-1 text-amber-700">
          No results were read back from your template
          {recalcWarning ? ` (${recalcWarning.replace('Server-side recalc skipped: ', '')})` : ' (no output cells are mapped)'}.
          The saved workbook is still correct — Excel recalculates it when opened.
        </div>
      )}
      {needsLook.length > 0 && (
        <details open>
          <summary className="cursor-pointer text-amber-700">
            {needsLook.length} mapped field(s) need a second look
          </summary>
          <IssueList rows={needsLook} labelOf={labelOf} />
        </details>
      )}
      {otherWarnings.length > 0 && (
        <ul className="list-disc pl-4 text-amber-600">
          {otherWarnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
