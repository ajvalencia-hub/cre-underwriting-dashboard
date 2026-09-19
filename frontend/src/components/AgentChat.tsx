import { useEffect, useRef, useState } from 'react'
import PendingProposalCard from './PendingProposalCard'
import { fetchAgentPlays, fetchAgentProviders } from '../lib/api'
import type { AgentThreadController } from '../lib/useAgentThread'
import type { AgentPlay, AgentProposal, AgentProviderInfo } from '../types/agent'
import type { InputSchema } from '../types/schema'

interface AgentChatProps {
  controller: AgentThreadController
  schema: InputSchema
  currentValues: Record<string, unknown>
  icLocked: boolean
  onApprove: (proposal: AgentProposal) => Promise<boolean>
  compact?: boolean
}

/** The agent conversation + composer, shared by the floating dock
 *  (AgentDock) and the Agent tab (AgentPage). The agent only ever PROPOSES
 *  input changes; each lands as a card to approve or reject here. */
export default function AgentChat({
  controller,
  schema,
  currentValues,
  icLocked,
  onApprove,
  compact = false,
}: AgentChatProps) {
  const { thread, loading, sending, error, sendMessage, setProvider, rejectProposal } = controller
  const [input, setInput] = useState('')
  const [plays, setPlays] = useState<AgentPlay[]>([])
  const [providers, setProviders] = useState<AgentProviderInfo[]>([])
  const [switchingProvider, setSwitchingProvider] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let current = true
    fetchAgentPlays()
      .then((p) => current && setPlays(p))
      .catch(() => current && setPlays([]))
    fetchAgentProviders()
      .then((p) => current && setProviders(p))
      .catch(() => current && setProviders([]))
    return () => {
      current = false
    }
  }, [])

  const messageCount = thread?.messages.length ?? 0
  useEffect(() => {
    bottomRef.current?.scrollIntoView?.({ block: 'nearest' })
  }, [messageCount])

  async function handleProviderChange(providerId: string) {
    setSwitchingProvider(true)
    try {
      await setProvider(providerId)
    } finally {
      setSwitchingProvider(false)
    }
  }

  async function handleSend(text: string) {
    if (!text.trim() || sending) return
    setInput('')
    await sendMessage(text)
  }

  const proposalById = new Map((thread?.proposals ?? []).map((p) => [p.id, p]))
  const activeProvider = providers.find((p) => p.id === thread?.provider)
  // A provider set only by the server's env (e.g. the e2e "scripted" stub)
  // isn't user-selectable; still show it as the current choice.
  const providerOptions =
    thread && !activeProvider ? [{ id: thread.provider, label: thread.provider, hasKey: true }, ...providers] : providers
  const missingKey = activeProvider ? !activeProvider.hasKey : false

  return (
    <div className={`flex flex-col ${compact ? 'h-96' : 'h-[70vh]'}`}>
      {thread && providers.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-200 px-3 py-1.5 text-xs">
          <label htmlFor={compact ? 'agent-provider-dock' : 'agent-provider-page'} className="text-slate-500">
            Provider
          </label>
          <select
            id={compact ? 'agent-provider-dock' : 'agent-provider-page'}
            value={thread.provider}
            disabled={switchingProvider}
            onChange={(e) => void handleProviderChange(e.target.value)}
            className="rounded border border-slate-300 bg-white px-1.5 py-0.5 text-xs text-slate-700 disabled:opacity-50"
          >
            {providerOptions.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
                {!p.hasKey ? ' (no API key set)' : ''}
              </option>
            ))}
          </select>
          {missingKey && (
            <span className="text-amber-700">No API key is configured for this provider — set it in backend/.env.</span>
          )}
        </div>
      )}
      <div className="flex-1 space-y-3 overflow-y-auto p-3" aria-live="polite">
        {loading && !thread && <div className="text-xs text-slate-500">Loading…</div>}
        {!loading && messageCount === 0 && (
          <div className="space-y-2">
            <div className="text-xs text-slate-500">
              Ask about this deal — the agent can compute metrics, run sensitivities and propose input changes for you
              to review. It never applies a change itself.
            </div>
            {plays.length > 0 && (
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Suggested questions">
                {plays.map((play) => (
                  <button
                    key={play.id}
                    type="button"
                    disabled={!thread || sending}
                    onClick={() => void sendMessage('', play.id)}
                    className="rounded-full border border-slate-200 px-2.5 py-1 text-[11px] text-slate-600 hover:bg-slate-50 disabled:opacity-50"
                  >
                    {play.label}
                  </button>
                ))}
              </div>
            )}
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
                <div
                  role="note"
                  className="mt-1.5 rounded border border-amber-200 bg-amber-50 px-2 py-1 text-[11px] text-amber-700"
                >
                  Unverified: {m.unverifiedClaims.map((c) => c.raw).join(', ')} — not confirmed by a tool call this
                  turn.
                </div>
              )}
              {m.toolCalls.length > 0 && (
                <details className="mt-1.5 text-[11px] opacity-80">
                  <summary className="cursor-pointer">{m.toolCalls.length} tool call(s)</summary>
                  <ul className="mt-1 space-y-1">
                    {m.toolCalls.map((tc, i) => (
                      <li key={i} className={tc.privilege === 'write' ? 'text-indigo-700' : ''}>
                        {tc.name}
                        {tc.privilege === 'write' ? ' (proposal)' : ''}
                        {typeof tc.result?.error === 'string' && (
                          <span className="text-red-600"> — {tc.result.error}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
              {m.stoppedReason && !['unavailable', 'error'].includes(m.stoppedReason) && (
                <div className="mt-1 text-[11px] text-amber-600">Stopped early: {m.stoppedReason}</div>
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
                    icLocked={icLocked}
                    onApprove={onApprove}
                    onReject={rejectProposal}
                  />
                </div>
              )
            })}
          </div>
        ))}
        {sending && <div className="text-xs text-slate-500">The agent is working…</div>}
        {error && (
          <div role="alert" className="text-xs text-red-600">
            {error}
          </div>
        )}
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
          aria-label="Message the agent"
          disabled={!thread || sending}
          className="flex-1 rounded border border-slate-300 px-2 py-1.5 text-sm disabled:opacity-60"
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
