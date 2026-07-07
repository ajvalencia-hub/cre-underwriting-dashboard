import { useCallback, useEffect, useState } from 'react'
import { approveAgentProposal, fetchAgentThread, postAgentMessage, rejectAgentProposal } from './api'
import type { AgentThreadState } from '../types/agent'
import type { Deal } from '../types/deal'

export interface AgentThreadController {
  thread: AgentThreadState | null
  loading: boolean
  sending: boolean
  error: string | null
  sendMessage: (content: string, playId?: string) => Promise<void>
  approveProposal: (proposalId: string, overrideChanges?: Record<string, unknown>) => Promise<Deal | null>
  rejectProposal: (proposalId: string, note?: string) => Promise<void>
}

/** K6: one thread per deal, shared by the chat dock and the Agent tab — both
 * instantiate this same hook from App.tsx and receive the identical
 * controller object, so an in-progress conversation survives switching
 * between them exactly like form state survives switching tabs. */
export function useAgentThread(dealId: string | null): AgentThreadController {
  const [thread, setThread] = useState<AgentThreadState | null>(null)
  const [loading, setLoading] = useState(false)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!dealId) {
      setThread(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      setThread(await fetchAgentThread(dealId))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load agent thread')
    } finally {
      setLoading(false)
    }
  }, [dealId])

  useEffect(() => {
    void refresh()
  }, [refresh])

  async function sendMessage(content: string, playId?: string) {
    if (!dealId || sending || (!content.trim() && !playId)) return
    setSending(true)
    setError(null)
    try {
      await postAgentMessage(dealId, content.trim(), playId)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to send message')
    } finally {
      setSending(false)
    }
  }

  async function approveProposal(proposalId: string, overrideChanges?: Record<string, unknown>) {
    setError(null)
    try {
      const result = await approveAgentProposal(proposalId, overrideChanges)
      await refresh()
      return result.deal
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve proposal')
      return null
    }
  }

  async function rejectProposal(proposalId: string, note = '') {
    setError(null)
    try {
      await rejectAgentProposal(proposalId, note)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to reject proposal')
    }
  }

  return { thread, loading, sending, error, sendMessage, approveProposal, rejectProposal }
}
