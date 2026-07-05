import { useEffect, useMemo, useState } from 'react'
import {
  fetchDealHistory,
  restoreDealSnapshot,
  type DealSnapshotMeta,
} from '../lib/api'
import { relativeAge } from '../lib/staleness'
import { flattenFields } from '../lib/schemaFields'
import type { Deal } from '../types/deal'
import type { InputSchema } from '../types/schema'

interface HistoryDrawerProps {
  schema: InputSchema
  dealId: string | null
  onRestored: (deal: Deal) => void
}

const KIND_LABELS: Record<DealSnapshotMeta['kind'], string> = {
  baseline: 'Baseline (before first edit)',
  autosave: 'Edit',
  restore: 'Restore',
}

/** Input change history (H9): snapshot list with what changed, and a
 *  confirm-gated restore. */
export default function HistoryDrawer({ schema, dealId, onRestored }: HistoryDrawerProps) {
  const [open, setOpen] = useState(false)
  const [snapshots, setSnapshots] = useState<DealSnapshotMeta[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [confirmingId, setConfirmingId] = useState<string | null>(null)
  const [restoring, setRestoring] = useState(false)

  const labelById = useMemo(() => {
    const map = new Map<string, string>()
    for (const field of flattenFields(schema)) map.set(field.id, field.label)
    return map
  }, [schema])

  useEffect(() => {
    if (!open || !dealId) return
    setLoading(true)
    setError(null)
    fetchDealHistory(dealId)
      .then(setSnapshots)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load history'))
      .finally(() => setLoading(false))
  }, [open, dealId])

  function pathLabel(path: string): string {
    const [head, sub] = path.split('.', 2)
    const label = labelById.get(head) ?? head
    return sub ? `${label} · ${sub}` : label
  }

  async function handleRestore(snapshotId: string) {
    if (!dealId) return
    setRestoring(true)
    setError(null)
    try {
      const deal = await restoreDealSnapshot(dealId, snapshotId)
      setConfirmingId(null)
      onRestored(deal)
      // Refresh: the restore itself is now the newest snapshot.
      setSnapshots(await fetchDealHistory(dealId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Restore failed')
    } finally {
      setRestoring(false)
    }
  }

  return (
    <div className="mb-4">
      <button
        onClick={() => setOpen(!open)}
        className="rounded border border-slate-200 px-3 py-1 text-xs text-slate-500 hover:bg-slate-50"
      >
        {open ? 'Hide input history' : 'Input history'}
      </button>

      {open && (
        <div className="mt-2 max-h-80 overflow-y-auto rounded border border-slate-200 bg-white p-3">
          {loading && <div className="text-xs text-slate-400">Loading…</div>}
          {error && <div className="text-xs text-red-600">{error}</div>}
          {!loading && snapshots.length === 0 && !error && (
            <div className="text-xs text-slate-400">
              No history yet — snapshots are recorded as you edit (coalesced into 10-minute
              windows, last 200 kept).
            </div>
          )}
          <ul className="space-y-2">
            {snapshots.map((snapshot, index) => (
              <li key={snapshot.id} className="border-b border-slate-50 pb-2 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <span
                      className={`font-medium ${
                        snapshot.kind === 'baseline'
                          ? 'text-slate-400'
                          : snapshot.kind === 'restore'
                            ? 'text-violet-600'
                            : 'text-slate-600'
                      }`}
                    >
                      {KIND_LABELS[snapshot.kind]}
                    </span>
                    <span className="ml-2 text-slate-400">
                      {relativeAge(snapshot.updatedAt)}
                      {index === 0 ? ' · current' : ''}
                    </span>
                  </div>
                  {index > 0 &&
                    (confirmingId === snapshot.id ? (
                      <span className="flex items-center gap-1">
                        <button
                          onClick={() => void handleRestore(snapshot.id)}
                          disabled={restoring}
                          className="rounded bg-violet-600 px-2 py-0.5 text-white hover:bg-violet-700 disabled:opacity-40"
                        >
                          {restoring ? 'Restoring…' : 'Confirm restore'}
                        </button>
                        <button
                          onClick={() => setConfirmingId(null)}
                          className="rounded border border-slate-200 px-2 py-0.5 text-slate-500"
                        >
                          Cancel
                        </button>
                      </span>
                    ) : (
                      <button
                        onClick={() => setConfirmingId(snapshot.id)}
                        className="rounded border border-violet-300 px-2 py-0.5 text-violet-600 hover:bg-violet-50"
                      >
                        Restore
                      </button>
                    ))}
                </div>
                {snapshot.changedPaths.length > 0 && (
                  <div className="mt-1 text-slate-500">
                    {snapshot.changedPaths.slice(0, 8).map(pathLabel).join(', ')}
                    {snapshot.changedPaths.length > 8 &&
                      ` +${snapshot.changedPaths.length - 8} more`}
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
