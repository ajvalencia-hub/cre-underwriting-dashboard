import { useEffect, useRef, useState } from 'react'
import PendingProposalCard from './PendingProposalCard'
import type { AgentThreadController } from '../lib/useAgentThread'
import type { InputSchema } from '../types/schema'

interface AgentChatProps {
  controller: AgentThreadController
  schema: InputSchema
  currentValues: Record<string, unknown>
  onApprove: (proposalId: string) => Promise<void>
  onReject: (proposalId: string, note: string) => Promise<void>
  compact?: boolean
}

const SUGGESTIONS = [
  'Screen this deal — is it worth pursuing?',
  "What's driving the levered IRR the most?",
  'What exit cap rate gets me to a 15% IRR?',
  'Propose a more conservative rent growth assumption.',
]

/** K6: the message list + composer, shared verbatim by the floating dock
 * (AgentDock) and the full Agent tab (AgentPage) — both are handed the
 * SAME controller instance from App.tsx, so a conversation started in one
 * continues seamlessly in the other. */
export default function AgentChat({
  controller,
  schema,
  currentValues,
  onApprove,
  onReject,
  compact = false,
}: AgentChatProps) {
  const { thread, loading, sending, error, sendMessage } = controller
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [thread?.messages.length])

  async function handleSend(text: string) {
    if (!text.trim() || sending) return
    setInput('')
    await sendMessage(text)
  }

  const proposalById = new Map((thread?.proposals ?? []).map((p) => [p.id, p]))

  return (
    <div className={`flex flex-col ${compact ? 'h-96' : 'h-[70vh]'}`}>
      <div className="flex-1 space-y-3 overflow-y-auto p-3">
        {loading && <div className="text-xs text-slate-400">Loading…</div>}
        {!loading && (thread?.messages.length ?? 0) === 0 && (
          <div className="space-y-2">
            <div className="text-xs text-slate-400">
              Ask about this deal — I can compute metrics, run sensitivity, and propose input
              changes for you to review and approve. I never apply a change myself.
            </div>
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => void handleSend(s)}
                  className="rounded-full border border-slate-200 px-2.5 py-1 text-[11px] text-slate-600 hover:bg-slate-50"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {thread?.messages.map((m) => (
          <div key={m.id} className={m.role === 'user' ? 'text-right' : ''}>
            <div
              className={`inline-block max-w-[92%] rounded-md px-3 py-2 text-left text-sm ${
                m.role === 'user' ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-800'
              }`}
            >
              <div className="whitespace-pre-wrap">{m.content}</div>
              {m.unverifiedClaims.length > 0 && (
                <div className="mt-1.5 rounded border border-amber-300 bg-amber-50 px-2 py-1 text-[10px] text-amber-700">
                  Unverified: {m.unverifiedClaims.map((c) => c.raw).join(', ')} — not confirmed by
                  a tool call this turn.
                </div>
              )}
              {m.toolCalls.length > 0 && (
                <details className="mt-1.5 text-[10px] opacity-80">
                  <summary className="cursor-pointer">{m.toolCalls.length} tool call(s)</summary>
                  <ul className="mt-1 space-y-1">
                    {m.toolCalls.map((tc, i) => (
                      <li key={i} className={tc.privilege === 'write' ? 'text-indigo-600' : ''}>
                        {tc.name}
                        {tc.privilege === 'write' ? ' (proposal)' : ''}
                        {typeof tc.result?.error === 'string' && (
                          <span className="text-red-500"> — {tc.result.error}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {m.stoppedReason && !['unavailable', 'error'].includes(m.stoppedReason) && (
                <div className="mt-1 text-[10px] text-amber-600">Stopped early: {m.stoppedReason}</div>
              )}
            </div>
            {m.proposalIds.map((pid) => {
              const proposal = proposalById.get(pid)
              if (!proposal) return null
              return (
                <div key={pid} className="mt-2 text-left">
                  <PendingProposalCard
                    proposal={proposal}
                    schema={schema}
                    currentValues={currentValues}
                    onApprove={onApprove}
                    onReject={onReject}
                  />
                </div>
              )
            })}
          </div>
        ))}
        {error && <div className="text-xs text-red-600">{error}</div>}
        <div ref={bottomRef} />
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void handleSend(input)
        }}
        className="flex items-center gap-2 border-t border-slate-200 p-2"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={thread ? 'Ask about this deal…' : 'Select a deal first'}
          disabled={!thread || sending}
          className="flex-1 rounded border border-slate-300 px-2 py-1.5 text-sm disabled:bg-slate-50"
        />
        <button
          type="submit"
          disabled={!thread || sending || !input.trim()}
          className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700 disabled:opacity-40"
        >
          {sending ? '…' : 'Send'}
        </button>
      </form>
    </div>
  )
}
