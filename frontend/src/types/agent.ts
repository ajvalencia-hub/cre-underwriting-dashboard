export type ToolPrivilege = 'read' | 'write' | 'unknown'

export interface AgentToolCallLog {
  name: string
  arguments: Record<string, unknown>
  result: Record<string, unknown>
  privilege: ToolPrivilege
}

export interface UnverifiedClaim {
  raw: string
  value: number
  kind: 'dollar' | 'percent' | 'multiple' | 'bare'
}

export interface AgentMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  toolCalls: AgentToolCallLog[]
  proposalIds: string[]
  unverifiedClaims: UnverifiedClaim[]
  stoppedReason: string | null
  createdAt: string
}

export type ProposalStatus = 'pending' | 'approved' | 'rejected' | 'stale'
export type ProposalKind = 'input_changes' | 'scenario'

export interface AgentProposalPreview {
  outputs: Record<string, unknown>
  warnings: string[]
}

export interface AgentProposal {
  id: string
  kind: ProposalKind
  changes: Record<string, unknown>
  rationale: string
  scenarioName: string | null
  preview: AgentProposalPreview | null
  warnings: string[]
  status: ProposalStatus
  createdAt: string
}

export interface AgentThreadState {
  id: string
  dealId: string
  provider: string
  totalInputTokens: number
  totalOutputTokens: number
  messages: AgentMessage[]
  proposals: AgentProposal[]
}

export interface AgentTurnResult {
  threadId: string
  text: string
  toolCalls: AgentToolCallLog[]
  proposals: AgentProposal[]
  unverifiedClaims: UnverifiedClaim[]
  stoppedReason: string | null
}

export const PROPOSAL_STATUS_LABELS: Record<ProposalStatus, string> = {
  pending: 'Pending review',
  approved: 'Approved',
  rejected: 'Rejected',
  stale: 'Stale — inputs changed since',
}
