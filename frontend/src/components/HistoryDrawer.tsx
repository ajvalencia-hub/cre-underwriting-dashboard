import { useEffect, useMemo, useState } from 'react'
import {
  fetchDeal,
  fetchDealHistory,
  fetchDealSnapshot,
  restoreDealSnapshot,
  type DealSnapshotMeta,
} from '../lib/api'
import { relativeAge } from '../lib/staleness'
import { flattenFields } from '../lib/schemaFields'
import { diffSnapshots, type SnapshotDiff } from '../lib/snapshotDiff'
import SnapshotDiffView from './SnapshotDiffView'
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
  agent: 'Agent-applied',
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
  // I12: restore preview (current saved state -> target snapshot) + compare.
  const [restorePreview, setRestorePreview] = useState<SnapshotDiff | null>(null)
  const [compareIds, setCompareIds] = useState<string[]>([])
  const [compareDiff, setCompareDiff] = useState<SnapshotDiff | null>(null)

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

  async function handlePreviewRestore(snapshotId: string) {
    if (!dealId) return
    setError(null)
    try {
      // Preview against the LAST SAVED deal state — that's what restore
      // actually replaces (unsaved keystrokes autosave within seconds).
      const [deal, snapshot] = await Promise.all([
        fetchDeal(dealId),
        fetchDealSnapshot(dealId, snapshotId),
      ])
      setRestorePreview(diffSnapshots(deal.inputs, snapshot.inputs, schema))
      setConfirmingId(snapshotId)
      setCompareDiff(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Preview failed')
    }
  }

  async function handleRestore(snapshotId: string) {
    if (!dealId) return
    setRestoring(true)
    setError(null)
    try {
      const deal = await restoreDealSnapshot(dealId, snapshotId)
      setConfirmingId(null)
      setRestorePreview(null)
      onRestored(deal)
      // Refresh: the restore itself is now the newest snapshot.
      setSnapshots(await fetchDealHistory(dealId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Restore failed')
    } finally {
      setRestoring(false)
    }
  }

  async function handleCompareToggle(snapshotId: string, checked: boolean) {
    const next = checked
      ? [...compareIds, snapshotId].slice(-2) // keep the last two picked
      : compareIds.filter((id) => id !== snapshotId)
    setCompareIds(next)
    setCompareDiff(null)
    if (next.length === 2 && dealId) {
      try {
        const [first, second] = await Promise.all(
          next.map((id) => fetchDealSnapshot(dealId, id)),
        )
        // Older snapshot is the "before" side regardless of pick order.
        const [older, newer] =
          Date.parse(first.updatedAt) <= Date.parse(second.updatedAt)
            ? [first, second]
            : [second, first]
        setCompareDiff(diffSnapshots(older.inputs, newer.inputs, schema))
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Compare failed')
      }
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
                            : snapshot.kind === 'agent'
                              ? 'text-indigo-600'
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
                  <span className="flex items-center gap-2">
                    <label className="flex items-center gap-1 text-[10px] text-slate-400">
                      <input
                        type="checkbox"
                        aria-label={`Compare snapshot from ${relativeAge(snapshot.updatedAt)}`}
                        checked={compareIds.includes(snapshot.id)}
                        onChange={(e) => void handleCompareToggle(snapshot.id, e.target.checked)}
                      />
                      compare
                    </label>
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
                            onClick={() => {
                              setConfirmingId(null)
                              setRestorePreview(null)
                            }}
                            className="rounded border border-slate-200 px-2 py-0.5 text-slate-500"
                          >
                            Cancel
                          </button>
                        </span>
                      ) : (
                        <button
                          onClick={() => void handlePreviewRestore(snapshot.id)}
                          className="rounded border border-violet-300 px-2 py-0.5 text-violet-600 hover:bg-violet-50"
                        >
                          Restore…
                        </button>
                      ))}
                  </span>
                </div>
                {confirmingId === snapshot.id && restorePreview && (
                  <div className="mt-2 rounded border border-violet-100 bg-violet-50/40 p-2">
                    <div className="mb-1 text-[10px] font-semibold text-violet-600">
                      RESTORE PREVIEW — last saved state → this snapshot
                    </div>
                    <SnapshotDiffView diff={restorePreview} />
                  </div>
                )}
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
          {compareIds.length === 2 && compareDiff && (
            <div className="mt-3 rounded border border-sky-100 bg-sky-50/40 p-2">
              <div className="mb-1 text-[10px] font-semibold text-sky-600">
                COMPARISON — older snapshot → newer snapshot
              </div>
              <SnapshotDiffView diff={compareDiff} />
            </div>
          )}
          {compareIds.length === 1 && (
            <div className="mt-2 text-[11px] text-slate-400">
              Pick a second snapshot to compare.
            </div>
          )}
        </div>
      )}
    </div>
  )
}
