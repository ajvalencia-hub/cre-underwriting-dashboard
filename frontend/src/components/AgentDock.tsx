import { useState } from 'react'
import AgentChat from './AgentChat'
import type { AgentThreadController } from '../lib/useAgentThread'
import type { InputSchema } from '../types/schema'

interface AgentDockProps {
  dealId: string | null
  controller: AgentThreadController
  schema: InputSchema
  currentValues: Record<string, unknown>
  onApprove: (proposalId: string) => Promise<void>
  onReject: (proposalId: string, note: string) => Promise<void>
}

const STORAGE_KEY = 'agentDockOpen'

/** K6: a persistent floating chat dock, positioned outside Layout's column
 * flow so it survives every tab switch without needing to touch Layout's
 * width calculations — the same "stays mounted across tabs" property the
 * SUMMARY aside already has, just as an overlay instead of a fourth column. */
export default function AgentDock({
  dealId,
  controller,
  schema,
  currentValues,
  onApprove,
  onReject,
}: AgentDockProps) {
  const [open, setOpen] = useState(() => localStorage.getItem(STORAGE_KEY) === '1')

  function toggle() {
    const next = !open
    setOpen(next)
    localStorage.setItem(STORAGE_KEY, next ? '1' : '0')
  }

  const pendingCount = (controller.thread?.proposals ?? []).filter((p) => p.status === 'pending').length

  return (
    <div className="fixed bottom-4 right-4 z-30">
      {open && (
        <div className="mb-2 w-96 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-slate-200 bg-slate-900 px-3 py-2 text-sm font-medium text-white">
            <span>Underwriting Agent</span>
            <button onClick={toggle} aria-label="Close agent chat" className="text-slate-300 hover:text-white">
              Close
            </button>
          </div>
          {dealId ? (
            <AgentChat
              controller={controller}
              schema={schema}
              currentValues={currentValues}
              onApprove={onApprove}
              onReject={onReject}
              compact
            />
          ) : (
            <div className="p-3 text-xs text-slate-400">Select a deal to chat with the agent.</div>
          )}
        </div>
      )}
      <button
        onClick={toggle}
        aria-label="Toggle underwriting agent chat"
        className="relative flex items-center gap-1.5 rounded-full bg-slate-900 px-4 py-2.5 text-sm font-medium text-white shadow-lg hover:bg-slate-700"
      >
        Agent
        {pendingCount > 0 && (
          <span className="flex h-4 w-4 items-center justify-center rounded-full bg-indigo-500 text-[10px] font-semibold">
            {pendingCount}
          </span>
        )}
      </button>
    </div>
  )
}
