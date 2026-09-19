// STUB (Phase 0, F1) — F3 replaces the body with the Run 6 Agent tab
// (AgentChat + PendingProposalCard + lib/useAgentThread). Keep the props
// interface; App.tsx already mounts it:
//
//   <PanelBoundary name="Agent">
//     <AgentPage key={dealScope} dealId={…} schema={…} currentValues={…}
//                icLocked={…} onApproveProposal={…} />
//   </PanelBoundary>
//
// Props (shared with components/AgentDock.tsx — see AgentSurfaceProps):
// - dealId:            the active deal (null only during boot).
// - schema:            input schema (labels for the proposal diff —
//                      prefer lib/inputChanges.describeInputChanges).
// - currentValues:     the Deal Inputs on screen (the "before" side).
// - icLocked:          the deal is locked for the investment committee —
//                      show Approve disabled with the reason (App also
//                      refuses; the server 409s as the last line).
// - onApproveProposal: App's approve path. It checks the IC lock, saves
//                      pending edits, calls approveAgentProposal (api.ts),
//                      adopts the returned deal (applyDealState + provenance
//                      source 'agent') and resolves true on success, false
//                      when refused/failed (App already toasted why). The
//                      component then refreshes its thread. Rejecting has no
//                      app-level side effects: call rejectAgentProposal
//                      (api.ts) directly.
//
// Thread sharing between the dock and the tab: if F3's useAgentThread needs
// to be one instance for both, add a `controller` prop to
// AgentSurfaceProps and G1 wires `useAgentThread(activeDealId)` in App at
// integration. Storage (dock open state etc.) goes through lib/safeStorage;
// errors through toastError('What failed', err).
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

export default function AgentPage({ dealId }: AgentPageProps) {
  return (
    <div className="max-w-3xl rounded-md border border-slate-200 bg-white p-4 text-sm text-slate-600">
      <h2 className="text-sm font-semibold text-slate-800">Underwriting Agent</h2>
      <p className="mt-1 text-xs text-slate-500">
        {dealId ? 'The agent chat for this deal is coming soon.' : 'Open a deal to talk to the agent.'}
      </p>
    </div>
  )
}
