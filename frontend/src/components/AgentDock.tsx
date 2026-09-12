import { useEffect, useState } from 'react'
import AgentChat from './AgentChat'
import { safeStorage } from '../lib/safeStorage'
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
 * SUMMARY aside already has, just as an overlay instead of a fourth column.
 * z-40 sits above the sticky deal header (z-30) and below the command
 * palette / modals (z-50) and toasts (z-60). Escape closes it, like every
 * other popover. */
export default function AgentDock({
  dealId,
  controller,
  schema,
  currentValues,
  onApprove,
  onReject,
}: AgentDockProps) {
  const [open, setOpen] = useState(() => safeStorage.get(STORAGE_KEY) === '1')

  function setOpenPersisted(next: boolean) {
    setOpen(next)
    safeStorage.set(STORAGE_KEY, next ? '1' : '0')
  }

  useEffect(() => {
    if (!open) return
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpenPersisted(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const pendingCount = (controller.thread?.proposals ?? []).filter((p) => p.status === 'pending').length

  return (
    <div className="fixed bottom-4 right-4 z-40" data-no-print>
      {open && (
        <div
          role="dialog"
          aria-label="Underwriting agent chat"
          className="mb-2 w-96 overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl"
        >
          <div className="flex items-center justify-between border-b border-slate-200 bg-slate-100 px-3 py-2 text-sm font-medium text-slate-800">
            <span>Underwriting Agent</span>
            <button
              onClick={() => setOpenPersisted(false)}
              aria-label="Close agent chat"
              className="text-xs text-slate-500 hover:text-slate-700"
            >
              Close
            </button>
          </div>
          {dealId ? (
            <AgentChat
              key={dealId}
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
        onClick={() => setOpenPersisted(!open)}
        aria-label="Toggle underwriting agent chat"
        aria-expanded={open}
        className="relative flex items-center gap-1.5 rounded-full bg-slate-900 px-4 py-2.5 text-sm font-medium text-white shadow-lg hover:bg-slate-700"
      >
        Agent
        {pendingCount > 0 && (
          <span className="flex h-4 w-4 items-center justify-center rounded-full bg-indigo-500 text-[10px] font-semibold text-white">
            {pendingCount}
          </span>
        )}
      </button>
    </div>
  )
}
