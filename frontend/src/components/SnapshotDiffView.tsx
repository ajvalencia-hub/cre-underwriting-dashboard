import { formatDiffValue, type SnapshotDiff } from '../lib/snapshotDiff'

const KIND_STYLES = {
  added: 'bg-emerald-100 text-emerald-700',
  removed: 'bg-red-100 text-red-700',
  changed: 'bg-sky-100 text-sky-700',
} as const

/** I12: shared renderer for snapshot comparisons and the restore preview. */
export default function SnapshotDiffView({ diff }: { diff: SnapshotDiff }) {
  if (diff.scalars.length === 0 && diff.tables.length === 0) {
    return <div className="text-xs text-slate-400">No differences.</div>
  }

  const sections = [...new Set([
    ...diff.scalars.map((s) => s.section),
    ...diff.tables.map((t) => t.section),
  ])]

  return (
    <div className="space-y-2 text-xs">
      {sections.map((section) => (
        <div key={section}>
          <div className="font-semibold text-slate-500">{section}</div>
          {diff.scalars
            .filter((s) => s.section === section)
            .map((change) => (
              <div key={change.fieldId} className="ml-2 mt-0.5 flex items-center gap-2">
                <span className={`rounded px-1 py-0.5 text-[10px] ${KIND_STYLES[change.kind]}`}>
                  {change.kind}
                </span>
                <span className="text-slate-600">{change.label}:</span>
                <span className="text-slate-400 line-through">
                  {formatDiffValue(change.before, change.type)}
                </span>
                <span>→</span>
                <span className="font-medium text-slate-700">
                  {formatDiffValue(change.after, change.type)}
                </span>
              </div>
            ))}
          {diff.tables
            .filter((t) => t.section === section)
            .map((table) => (
              <div key={table.fieldId} className="ml-2 mt-0.5">
                <div className="text-slate-600">{table.label}</div>
                {table.rows.map((row) => (
                  <div key={row.key} className="ml-2 mt-0.5 flex flex-wrap items-center gap-2">
                    <span className={`rounded px-1 py-0.5 text-[10px] ${KIND_STYLES[row.kind]}`}>
                      {row.kind}
                    </span>
                    <span className="font-medium text-slate-600">{row.key}</span>
                    {row.cells.map((cell) => (
                      <span key={cell.column} className="text-slate-500">
                        {cell.column}: {formatDiffValue(cell.before, 'text')} →{' '}
                        <span className="text-slate-700">{formatDiffValue(cell.after, 'text')}</span>
                      </span>
                    ))}
                  </div>
                ))}
              </div>
            ))}
        </div>
      ))}
    </div>
  )
}
