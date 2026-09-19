// The floating Underwriting Agent chat. App mounts it OUTSIDE <Layout> (so it
// survives every tab switch) and only after boot/auth:
//
//   <AgentDock {...agentSurface} hidden={tab === 'agent'} />
//
// Props: AgentSurfaceProps (documented in pages/AgentPage.tsx) plus
// - hidden: true while the Agent tab itself is showing (no duplicate chat).
//
// Layering: z-40 (above the sticky deal header z-30, below the palette /
// modals z-50 and toasts z-[60]). Escape closes it. The open/closed flag
// goes through lib/safeStorage. The dock and the tab each hold their own
// thread controller; lib/useAgentThread keeps them in step (a change in one
// re-reads the thread in the other).
import { useEffect, useRef, useState } from 'react'
import AgentChat from './AgentChat'
import { safeStorage } from '../lib/safeStorage'
import { announceAgentThreadChange, useAgentThread } from '../lib/useAgentThread'
import type { AgentSurfaceProps } from '../pages/AgentPage'
import type { AgentProposal } from '../types/agent'

export interface AgentDockProps extends AgentSurfaceProps {
  hidden: boolean
}

const STORAGE_KEY = 'cre.agentDockOpen'

export default function AgentDock({ dealId, schema, currentValues, icLocked, onApproveProposal, hidden }: AgentDockProps) {
  const controller = useAgentThread(dealId)
  const [open, setOpen] = useState(() => safeStorage.get(STORAGE_KEY) === '1')
  const dockRef = useRef<HTMLDivElement>(null)

  function setOpenPersisted(next: boolean) {
    setOpen(next)
    safeStorage.set(STORAGE_KEY, next ? '1' : '0')
  }

  useEffect(() => {
    if (!open || hidden) return
    function onKey(e: KeyboardEvent) {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      // Only when the dock (or nothing in particular) has focus — Escape
      // inside a modal or the palette belongs to that surface.
      const active = document.activeElement
      if (active && active !== document.body && !dockRef.current?.contains(active)) return
      setOpen(false)
      safeStorage.set(STORAGE_KEY, '0')
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, hidden])

  if (hidden) return null

  async function handleApprove(proposal: AgentProposal) {
    const ok = await onApproveProposal(proposal)
    // Applied or refused, the proposal's status may have moved server-side.
    if (dealId) announceAgentThreadChange(dealId)
    return ok
  }

  const pendingCount = (controller.thread?.proposals ?? []).filter((p) => p.status === 'pending').length

  return (
    <div ref={dockRef} className="fixed bottom-4 right-4 z-40" data-no-print>
      {open && (
        <div
          role="dialog"
          aria-label="Underwriting agent chat"
          className="mb-2 w-96 max-w-[calc(100vw-2rem)] overflow-hidden rounded-lg border border-slate-200 bg-white shadow-xl"
        >
          <div className="flex items-center justify-between border-b border-slate-200 bg-slate-100 px-3 py-2 text-sm font-medium text-slate-800">
            <span>Underwriting Agent</span>
            <button
              type="button"
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
              icLocked={icLocked}
              onApprove={handleApprove}
              compact
            />
          ) : (
            <div className="p-3 text-xs text-slate-500">Open a deal to chat with the agent.</div>
          )}
        </div>
      )}
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => setOpenPersisted(!open)}
          aria-label="Toggle underwriting agent chat"
          aria-expanded={open}
          className="relative flex items-center gap-1.5 rounded-full bg-slate-900 px-4 py-2.5 text-sm font-medium text-white shadow-lg hover:bg-slate-700"
        >
          Agent
          {pendingCount > 0 && (
            <span
              className="flex h-4 min-w-4 items-center justify-center rounded-full bg-indigo-500 px-1 text-[10px] font-semibold text-white"
              aria-label={`${pendingCount} pending proposal(s)`}
            >
              {pendingCount}
            </span>
          )}
        </button>
      </div>
    </div>
  )
}
