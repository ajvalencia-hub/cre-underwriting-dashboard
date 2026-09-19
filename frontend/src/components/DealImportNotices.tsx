import type { DealExportBundle } from '../lib/api'

interface Props {
  notice: string | null
  preview: DealExportBundle | null
  onConfirm: () => void
  onCancel: () => void
}

/** The outcome of the last deal import, and the confirm step for a bundle
 *  that's been read but not imported yet. */
export default function DealImportNotices({ notice, preview, onConfirm, onCancel }: Props) {
  return (
    <>
      {notice && (
        <div className="mb-3 rounded border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs text-slate-600">
          {notice}
        </div>
      )}
      {preview && (
        <div className="mb-3 flex items-center gap-3 rounded border border-sky-200 bg-sky-50 px-3 py-2 text-sm text-slate-700">
          <span>
            Import <span className="font-semibold">{preview.deal.name}</span> — {preview.scenarios.length}{' '}
            scenario(s), exported {new Date(preview.exportedAt).toLocaleString()}
            {preview.activeTemplate && ` · used template "${preview.activeTemplate.filename}" (not bundled)`}?
          </span>
          <button onClick={onConfirm} className="rounded bg-slate-900 px-2 py-1 text-xs text-white hover:bg-slate-700">
            Create new deal
          </button>
          <button
            onClick={onCancel}
            className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-white"
          >
            Cancel
          </button>
        </div>
      )}
    </>
  )
}
