// The Agent tab: the full-height Underwriting Agent conversation for the open
// deal. App mounts it (and the floating AgentDock, with the same props):
//
//   <AgentPage key={dealScope} dealId={…} schema={…} currentValues={…}
//              icLocked={…} onApproveProposal={…} />
//
// Props (AgentSurfaceProps, shared with components/AgentDock.tsx):
// - dealId:            the active deal (null only during boot).
// - schema:            input schema (labels for the proposal diff).
// - currentValues:     the Deal Inputs on screen (the "before" side).
// - icLocked:          the deal is locked for the investment committee —
//                      Approve shows disabled with the reason (App also
//                      refuses; the server 409s as the last line).
// - onApproveProposal: App's approve path (IC lock, pending-save flush,
//                      approveAgentProposal, adopt the deal + provenance
//                      'agent'); resolves true when applied. Rejecting has no
//                      app-level side effects (lib/useAgentThread calls
//                      rejectAgentProposal directly).
import AgentChat from '../components/AgentChat'
import { announceAgentThreadChange, useAgentThread } from '../lib/useAgentThread'
import type { InputSchema } from '../types/schema'
import type { AgentProposal } from '../types/agent'

export interface AgentSurfaceProps {
  dealId: string | null
  schema: InputSchema
  currentValues: Record<string, unknown>
  icLocked: boolean
  onApproveProposal: (
    proposal: Pick<AgentProposal, 'id' | 'changes'>,
    overrideChanges?: Record<string, unknown>,
  ) => Promise<boolean>
}

export type AgentPageProps = AgentSurfaceProps

export default function AgentPage({ dealId, schema, currentValues, icLocked, onApproveProposal }: AgentPageProps) {
  const controller = useAgentThread(dealId)

  if (!dealId) {
    return <div className="text-sm text-slate-500">Open a deal to chat with the Underwriting Agent.</div>
  }

  async function handleApprove(proposal: AgentProposal) {
    const ok = await onApproveProposal(proposal)
    if (dealId) announceAgentThreadChange(dealId)
    return ok
  }

  const thread = controller.thread

  return (
    <div className="rounded-md border border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
        <h2 className="text-sm font-semibold text-slate-700">Underwriting Agent</h2>
        {thread && (
          <div
            className="text-xs text-slate-500"
            title={`${thread.totalInputTokens.toLocaleString()} input + ${thread.totalOutputTokens.toLocaleString()} output tokens (${thread.provider})`}
          >
            {(thread.totalInputTokens + thread.totalOutputTokens).toLocaleString()} tokens used
          </div>
        )}
      </div>
      {icLocked && (
        <div className="border-b border-amber-200 bg-amber-50 px-4 py-1.5 text-xs text-amber-700">
          Locked for the investment committee — the agent can still analyse this deal, but its input changes can't be
          applied until the lock is lifted.
        </div>
      )}
      <AgentChat
        key={dealId}
        controller={controller}
        schema={schema}
        currentValues={currentValues}
        icLocked={icLocked}
        onApprove={handleApprove}
      />
    </div>
  )
}
