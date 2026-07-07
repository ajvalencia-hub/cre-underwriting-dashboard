import AgentChat from '../components/AgentChat'
import type { AgentThreadController } from '../lib/useAgentThread'
import type { InputSchema } from '../types/schema'

interface AgentPageProps {
  dealId: string | null
  controller: AgentThreadController
  schema: InputSchema
  currentValues: Record<string, unknown>
  onApprove: (proposalId: string) => Promise<void>
  onReject: (proposalId: string, note: string) => Promise<void>
}

export default function AgentPage({
  dealId,
  controller,
  schema,
  currentValues,
  onApprove,
  onReject,
}: AgentPageProps) {
  if (!dealId) {
    return <div className="text-sm text-slate-400">Select a deal to chat with the Underwriting Agent.</div>
  }

  const thread = controller.thread

  return (
    <div className="rounded-md border border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2">
        <div className="text-sm font-semibold text-slate-700">Underwriting Agent</div>
        {thread && (
          <div className="text-xs text-slate-400">
            {thread.totalInputTokens + thread.totalOutputTokens} tokens used
          </div>
        )}
      </div>
      <AgentChat
        controller={controller}
        schema={schema}
        currentValues={currentValues}
        onApprove={onApprove}
        onReject={onReject}
      />
    </div>
  )
}
