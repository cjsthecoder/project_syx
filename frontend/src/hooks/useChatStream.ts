/**
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * React hook managing chat message state and streaming responses.
 *
 * Tracks the message list and input, loads persisted chats, and posts to
 * `/chat/stream` while incrementally appending streamed assistant text and
 * handling sleep-state and error conditions.
 */
import { useCallback, useMemo, useState } from 'react'
import { api } from '@/pages/app/api'
import { messageForChatError } from '@/pages/app/health'
import { RequestError, throwRequestError } from '@/pages/app/request'
import { Message } from '@/pages/app/types'

type UseChatStreamArgs = {
  projectId: string
  model: string
  onBeforeSend?: () => void
  onError: (message: string) => void
  checkSleeping: () => Promise<boolean>
  onAfterStream?: (projectId: string) => Promise<void>
  chatEnabled?: boolean
}

/**
 * Manage chat message state and streamed assistant responses for a project.
 *
 * Errors are surfaced via `onError`; sleep-state aborts route through
 * `checkSleeping`.
 *
 * @param args - Hook configuration.
 * @param args.projectId - Active project id used when posting messages.
 * @param args.model - Model identifier sent with each request.
 * @param args.onBeforeSend - Optional callback invoked before a send begins.
 * @param args.onError - Callback invoked with a message when sending/streaming fails.
 * @param args.checkSleeping - Resolves true when the system is sleeping (send is aborted).
 * @param args.onAfterStream - Optional callback invoked with the project id after a stream completes.
 * @param args.chatEnabled - Whether chat sends are currently allowed by app health.
 * @returns Message list and setter, input state, `loading`/`canSend` flags, and the `send` and `loadChats` actions.
 */
export function useChatStream({
  projectId,
  model,
  onBeforeSend,
  onError,
  checkSleeping,
  onAfterStream,
  chatEnabled = true,
}: UseChatStreamArgs) {
  const makeClientId = () =>
    typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
      ? crypto.randomUUID()
      : `msg-${Date.now()}-${Math.random().toString(36).slice(2)}`

  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)

  const canSend = useMemo(
    () => chatEnabled && input.trim().length > 0 && !loading,
    [chatEnabled, input, loading],
  )

  /**
   * Load persisted chat history for a project, resetting to empty on failure.
   *
   * @param pid - Project id whose chat history to load.
   */
  const loadChats = useCallback(async (pid: string) => {
    try {
      const data = await api<{
        project_id: string
        messages: { id: number; role: 'user' | 'assistant'; content: string; created_at: string; forget?: boolean | null; keep?: boolean | null }[]
      }>(`/projects/${pid}/chats`)
      const msgs: Message[] = (data.messages || []).map((m) => ({
        id: m.id,
        role: m.role,
        content: m.content,
        forget: !!m.forget,
        keep: !!m.keep,
      }))
      setMessages(msgs)
    } catch {
      setMessages([])
    }
  }, [])

  /**
   * Send the current input and stream the assistant reply into the message list.
   *
   * Optimistically appends the user message, aborts early when the system is
   * sleeping (HTTP 423 or a sleep error), incrementally appends decoded chunks,
   * and flags completion on the `::event: done` sentinel.
   */
  const send = useCallback(async () => {
    if (!canSend) return
    onBeforeSend?.()
    setLoading(true)
    if (await checkSleeping()) {
      setLoading(false)
      return
    }
    const userMsg: Message = { clientId: makeClientId(), role: 'user', content: input }
    const assistantClientId = makeClientId()
    setMessages((m) => [...m, userMsg])
    const toSend = input
    setInput('')
    try {
      const res = await fetch('/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, message: toSend, model }),
      })
      if (!res.ok || !res.body) {
        let detail = ''
        let requestError: unknown = null
        try {
          await throwRequestError(res)
        } catch (err) {
          requestError = err
          if (err instanceof RequestError) {
            detail = err.message || ''
          } else if (err instanceof Error) {
            detail = err.message || ''
          }
        }
        if (res.status === 423 || /sleep/i.test(detail)) {
          await checkSleeping()
          throw new Error('System is sleeping')
        }
        if (requestError) {
          throw requestError
        }
        throw new Error(detail || `HTTP ${res.status}`)
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let done = false
      let assistantCreated = false
      while (!done) {
        const { value, done: d } = await reader.read()
        done = d
        if (value) {
          const chunk = decoder.decode(value, { stream: true })
          const streamComplete = /\n::event:\s*done\s*\n?/.test(chunk)
          const text = chunk.replace(/\n::event:\s*done\s*\n?/g, '')
          if (text && text.trim().length > 0) {
            setMessages((m) => {
              if (m.length === 0) return m
              if (!assistantCreated) {
                assistantCreated = true
                setLoading(false)
                return [...m, { clientId: assistantClientId, role: 'assistant', content: text }]
              }
              const copy = [...m]
              const idx = copy.length - 1
              if (copy[idx]?.role !== 'assistant') {
                return [...copy, { role: 'assistant', content: text }]
              }
              copy[idx] = { ...copy[idx], content: (copy[idx].content || '') + text }
              return copy
            })
          }
          if (streamComplete) {
            setMessages((m) => {
              const copy = [...m]
              const idx = copy.length - 1
              if (copy[idx]?.role === 'assistant') {
                copy[idx] = { ...copy[idx], streamComplete: true }
              }
              return copy
            })
          }
        }
      }
      if (projectId && onAfterStream) {
        await onAfterStream(projectId)
      }
    } catch (e: unknown) {
      onError(messageForChatError(e))
    } finally {
      setLoading(false)
    }
  }, [canSend, checkSleeping, input, model, onAfterStream, onBeforeSend, onError, projectId])

  return {
    messages,
    setMessages,
    input,
    setInput,
    loading,
    canSend,
    send,
    loadChats,
  }
}
