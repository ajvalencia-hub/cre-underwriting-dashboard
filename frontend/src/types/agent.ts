// Underwriting Agent types (Run 6 K*). TARGET style: aliases of the
// generated API schemas (api.gen.ts, from the backend's response_models),
// so there is no hand copy to drift. The one loosely-typed field is a
// proposal's `preview` (the backend declares it as an open dict) — read it
// through `proposalPreview()`.
import type { components } from './api.gen'

type Schemas = components['schemas']

export type AgentThreadState = Schemas['AgentThreadOut']
export type AgentMessage = Schemas['AgentMessageOut']
/** A proposal as stored on the thread (has createdAt). */
export type AgentProposal = Schemas['AgentProposalOut']
/** A proposal as returned inside a turn (no createdAt yet). */
export type AgentTurnProposal = Schemas['AgentTurnProposalOut']
export type AgentTurnResult = Schemas['AgentTurnOut']
export type AgentToolCallLog = Schemas['AgentToolCallLogOut']
export type UnverifiedClaim = Schemas['AgentUnverifiedClaimOut']
export type AgentPlay = Schemas['AgentPlayOut']
export type AgentProviderInfo = Schemas['AgentProviderOut']
export type AgentThreadRef = Schemas['AgentThreadRefOut']
export type AgentApproveResult = Schemas['AgentApproveOut']
export type AgentRejectResult = Schemas['AgentRejectOut']

export type ToolPrivilege = AgentToolCallLog['privilege']
export type ProposalStatus = AgentProposal['status']
export type ProposalKind = AgentProposal['kind']

export interface AgentProposalPreview {
  outputs: Record<string, unknown>
  warnings: string[]
}

/** The engine preview the agent attached to a proposal, or null when there
 *  is none / it isn't the expected shape. */
export function proposalPreview(p: Pick<AgentProposal, 'preview'>): AgentProposalPreview | null {
  const raw = p.preview
  if (!raw || typeof raw !== 'object') return null
  const outputs = (raw as Record<string, unknown>).outputs
  const warnings = (raw as Record<string, unknown>).warnings
  return {
    outputs: outputs && typeof outputs === 'object' && !Array.isArray(outputs) ? (outputs as Record<string, unknown>) : {},
    warnings: Array.isArray(warnings) ? warnings.filter((w): w is string => typeof w === 'string') : [],
  }
}

export const PROPOSAL_STATUS_LABELS: Record<ProposalStatus, string> = {
  pending: 'Pending review',
  approved: 'Approved',
  rejected: 'Rejected',
  stale: 'Stale — inputs changed since',
}
