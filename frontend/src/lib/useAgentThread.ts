import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchAgentThread, postAgentMessage, rejectAgentProposal, setAgentThreadProvider } from './api'
import { createLatestGuard } from './latest'
import { toastError } from './toast'
import type { AgentThreadState } from '../types/agent'

export interface AgentThreadController {
  thread: AgentThreadState | null
  loading: boolean
  sending: boolean
  /** The last load/send failure, shown inline in the conversation. */
  error: string | null
  sendMessage: (content: string, playId?: string) => Promise<void>
  rejectProposal: (proposalId: string, note?: string) => Promise<void>
  setProvider: (provider: string) => Promise<void>
  /** Re-read the thread (after an approve, which goes through App). */
  refresh: () => Promise<void>
}

// The dock and the Agent tab each hold their own controller (they're never
// on screen together: the dock hides while the tab shows). Any mutation
// announces itself here so the other surface re-reads the thread instead
// of showing a stale conversation when the user switches between them.
const THREAD_CHANGED_EVENT = 'cre:agent-thread-changed'

export function announceAgentThreadChange(dealId: string): void {
  if (typeof window === 'undefined') return
  window.dispatchEvent(new CustomEvent<string>(THREAD_CHANGED_EVENT, { detail: dealId }))
}

/** One agent thread per deal. Loads on mount / deal change (latest-wins, so a
 *  fast deal switch can't show the previous deal's conversation). Approving
 *  a proposal is NOT here: it writes deal inputs, so it goes through App's
 *  onApproveProposal (IC lock, pending-save flush, provenance). */
export function useAgentThread(dealId: string | null): AgentThreadController {
  const [thread, setThread] = useState<AgentThreadState | null>(null)
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const guardRef = useRef(createLatestGuard())

  const refresh = useCallback(async () => {
    const token = guardRef.current.next()
    if (!dealId) {
      setThread(null)
      setLoading(false)
      return
    }
    setLoading(true)
    try {
      const next = await fetchAgentThread(dealId)
      if (!guardRef.current.isCurrent(token)) return
      setThread(next)
      setError(null)
    } catch (err) {
      if (!guardRef.current.isCurrent(token)) return
      setError(err instanceof Error ? err.message : "Couldn't load the agent conversation")
    } finally {
      if (guardRef.current.isCurrent(token)) setLoading(false)
    }
  }, [dealId])

  useEffect(() => {
    // A different deal: drop the old conversation right away.
    setThread(null)
    setError(null)
    void refresh()
  }, [refresh])

  useEffect(() => {
    if (!dealId) return
    function onChanged(e: Event) {
      if ((e as CustomEvent<string>).detail === dealId) void refresh()
    }
    window.addEventListener(THREAD_CHANGED_EVENT, onChanged)
    return () => window.removeEventListener(THREAD_CHANGED_EVENT, onChanged)
  }, [dealId, refresh])

  async function sendMessage(content: string, playId?: string) {
    if (!dealId || sending || (!content.trim() && !playId)) return
    setSending(true)
    setError(null)
    try {
      await postAgentMessage(dealId, content.trim(), playId)
      announceAgentThreadChange(dealId)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't send the message")
    } finally {
      setSending(false)
    }
  }

  async function rejectProposal(proposalId: string, note = '') {
    if (!dealId) return
    try {
      await rejectAgentProposal(proposalId, note)
      announceAgentThreadChange(dealId)
    } catch (err) {
      toastError("Couldn't reject the proposal", err)
    }
  }

  async function setProvider(provider: string) {
    if (!dealId) return
    try {
      await setAgentThreadProvider(dealId, provider)
      announceAgentThreadChange(dealId)
    } catch (err) {
      toastError("Couldn't switch the agent's provider", err)
    }
  }

  return { thread, loading, sending, error, sendMessage, rejectProposal, setProvider, refresh }
}
