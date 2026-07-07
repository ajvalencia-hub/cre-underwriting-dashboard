import { useState } from 'react'
import { diffSnapshots } from '../lib/snapshotDiff'
import SnapshotDiffView from './SnapshotDiffView'
import type { AgentProposal } from '../types/agent'
import type { InputSchema } from '../types/schema'

interface PendingProposalCardProps {
  proposal: AgentProposal
  schema: InputSchema
  currentValues: Record<string, unknown>
  onApprove: (proposalId: string) => Promise<void>
  onReject: (proposalId: string, note: string) => Promise<void>
}

const STATUS_BADGE: Record<AgentProposal['status'], string> = {
  pending: 'bg-indigo-100 text-indigo-700',
  approved: 'bg-emerald-100 text-emerald-700',
  rejected: 'bg-red-100 text-red-700',
  stale: 'bg-amber-100 text-amber-700',
}

/** K7: reuses the existing snapshot-diff renderer (I12) for the before/after
 * preview — no parallel diff implementation. Approve calls back up to
 * App.tsx, which applies the change through the same PUT /api/deals/{id}
 * path every other edit uses. */
export default function PendingProposalCard({
  proposal,
  schema,
  currentValues,
  onApprove,
  onReject,
}: PendingProposalCardProps) {
  const [rejecting, setRejecting] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  const diff = diffSnapshots(currentValues, { ...currentValues, ...proposal.changes }, schema)
  const isPending = proposal.status === 'pending'

  async function handleApprove() {
    setBusy(true)
    await onApprove(proposal.id)
    setBusy(false)
  }

  async function handleConfirmReject() {
    setBusy(true)
    await onReject(proposal.id, note)
    setBusy(false)
    setRejecting(false)
    setNote('')
  }

  return (
    <div className="rounded-md border border-indigo-200 bg-indigo-50/40 p-3 text-xs">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="font-semibold text-indigo-700">
          {proposal.kind === 'scenario'
            ? `Proposed scenario: ${proposal.scenarioName ?? 'Untitled'}`
            : 'Proposed input changes'}
        </span>
        <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${STATUS_BADGE[proposal.status]}`}>
          {proposal.status}
        </span>
      </div>
      {proposal.rationale && <p className="mb-2 text-slate-600">{proposal.rationale}</p>}
      <SnapshotDiffView diff={diff} />
      {proposal.preview && (
        <div className="mt-2 text-slate-500">
          Preview:{' '}
          {Object.entries(proposal.preview.outputs)
            .slice(0, 4)
            .map(([id, value]) => `${id}: ${String(value)}`)
            .join(' · ')}
        </div>
      )}
      {proposal.warnings.length > 0 && (
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-amber-600">
          {proposal.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
      {isPending && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button
            disabled={busy}
            onClick={() => void handleApprove()}
            className="rounded bg-slate-900 px-2 py-1 text-white hover:bg-slate-700 disabled:opacity-40"
          >
            Approve &amp; apply
          </button>
          {!rejecting ? (
            <button
              disabled={busy}
              onClick={() => setRejecting(true)}
              className="rounded border border-slate-300 px-2 py-1 text-slate-600 hover:bg-white disabled:opacity-40"
            >
              Reject
            </button>
          ) : (
            <>
              <input
                autoFocus
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="Why? (optional)"
                className="rounded border border-slate-300 px-2 py-1"
              />
              <button
                disabled={busy}
                onClick={() => void handleConfirmReject()}
                className="rounded bg-red-600 px-2 py-1 text-white hover:bg-red-700 disabled:opacity-40"
              >
                Confirm reject
              </button>
              <button onClick={() => setRejecting(false)} className="text-slate-400 hover:text-slate-600">
                Cancel
              </button>
            </>
          )}
        </div>
      )}
      {proposal.status === 'stale' && (
        <div className="mt-2 text-amber-600">
          A different proposal was applied since this one was made — the preview above no longer
          reflects the deal's current inputs.
        </div>
      )}
    </div>
  )
}
