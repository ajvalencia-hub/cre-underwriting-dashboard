import { useState } from 'react'
import { diffSnapshots } from '../lib/snapshotDiff'
import SnapshotDiffView from './SnapshotDiffView'
import { PROPOSAL_STATUS_LABELS, proposalPreview, type AgentProposal } from '../types/agent'
import type { InputSchema } from '../types/schema'

interface PendingProposalCardProps {
  proposal: AgentProposal
  schema: InputSchema
  currentValues: Record<string, unknown>
  /** The deal is locked for the investment committee: input changes can't
   *  be applied (App and the server refuse too). */
  icLocked: boolean
  /** Resolves true when the change was applied. */
  onApprove: (proposal: AgentProposal) => Promise<boolean>
  onReject: (proposalId: string, note: string) => Promise<void>
}

const STATUS_BADGE: Record<AgentProposal['status'], string> = {
  pending: 'bg-indigo-100 text-indigo-700',
  approved: 'bg-emerald-100 text-emerald-700',
  rejected: 'bg-red-100 text-red-700',
  stale: 'bg-amber-100 text-amber-700',
}

/** One agent proposal: rationale, the before/after diff (the shared snapshot
 *  diff renderer, so it reads like History), the engine preview and
 *  Approve/Reject. Approving goes up to App, which applies it server-side
 *  (history kind "agent") and marks the fields as agent-filled. */
export default function PendingProposalCard({
  proposal,
  schema,
  currentValues,
  icLocked,
  onApprove,
  onReject,
}: PendingProposalCardProps) {
  const [rejecting, setRejecting] = useState(false)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)

  const diff = diffSnapshots(currentValues, { ...currentValues, ...proposal.changes }, schema)
  const preview = proposalPreview(proposal)
  const isPending = proposal.status === 'pending'
  const lockBlocks = icLocked && proposal.kind === 'input_changes'

  async function handleApprove() {
    setBusy(true)
    try {
      await onApprove(proposal)
    } finally {
      setBusy(false)
    }
  }

  async function handleConfirmReject() {
    setBusy(true)
    try {
      await onReject(proposal.id, note)
    } finally {
      setBusy(false)
      setRejecting(false)
      setNote('')
    }
  }

  const previewEntries = preview ? Object.entries(preview.outputs).slice(0, 4) : []

  return (
    <div className="rounded-md border border-indigo-200 bg-indigo-50/50 p-3 text-xs" data-testid="agent-proposal">
      <div className="mb-1 flex items-center justify-between gap-2">
        <span className="font-semibold text-indigo-700">
          {proposal.kind === 'scenario'
            ? `Proposed scenario: ${proposal.scenarioName ?? 'Untitled'}`
            : 'Proposed input changes'}
        </span>
        <span className={`shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${STATUS_BADGE[proposal.status]}`}>
          {PROPOSAL_STATUS_LABELS[proposal.status]}
        </span>
      </div>
      {proposal.rationale && <p className="mb-2 text-slate-600">{proposal.rationale}</p>}
      <SnapshotDiffView diff={diff} />
      {previewEntries.length > 0 && (
        <div className="mt-2 text-slate-500">
          Preview: {previewEntries.map(([id, value]) => `${id}: ${String(value)}`).join(' · ')}
        </div>
      )}
      {(proposal.warnings.length > 0 || (preview?.warnings.length ?? 0) > 0) && (
        <ul className="mt-1 list-disc space-y-0.5 pl-4 text-amber-600">
          {[...proposal.warnings, ...(preview?.warnings ?? [])].map((w, i) => (
            <li key={`${i}-${w}`}>{w}</li>
          ))}
        </ul>
      )}
      {isPending && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button
            type="button"
            disabled={busy || lockBlocks}
            onClick={() => void handleApprove()}
            title={lockBlocks ? 'Locked for the investment committee' : undefined}
            className="rounded bg-slate-900 px-2 py-1 text-white hover:bg-slate-700 disabled:opacity-40"
          >
            Approve &amp; apply
          </button>
          {!rejecting ? (
            <button
              type="button"
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
                onKeyDown={(e) => {
                  // Don't let Escape here close the dock around it.
                  if (e.key === 'Escape') {
                    e.stopPropagation()
                    setRejecting(false)
                  }
                }}
                placeholder="Why? (optional)"
                aria-label="Reason for rejecting (optional)"
                className="rounded border border-slate-300 px-2 py-1"
              />
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleConfirmReject()}
                className="rounded bg-red-600 px-2 py-1 text-white hover:bg-red-700 disabled:opacity-40"
              >
                Confirm reject
              </button>
              <button
                type="button"
                onClick={() => setRejecting(false)}
                className="text-slate-500 hover:text-slate-700"
              >
                Cancel
              </button>
            </>
          )}
        </div>
      )}
      {isPending && lockBlocks && (
        <div className="mt-2 text-amber-700" role="note">
          This deal is locked for the investment committee — its inputs can't change, so this proposal can't be
          applied. Reopen the IC review to apply it, or reject it.
        </div>
      )}
      {proposal.status === 'stale' && (
        <div className="mt-2 text-amber-600">
          The deal's inputs changed since this was proposed — the preview above no longer reflects them.
        </div>
      )}
    </div>
  )
}
