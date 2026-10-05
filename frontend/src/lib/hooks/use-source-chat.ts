'use client'

import { useState, useCallback, useRef, useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { getApiErrorMessage } from '@/lib/utils/error-handler'
import { useTranslation } from '@/lib/hooks/use-translation'
import { sourceChatApi } from '@/lib/api/source-chat'
import {
  SourceChatSession,
  SourceChatMessage,
  SourceChatContextIndicator,
  CreateSourceChatSessionRequest,
  UpdateSourceChatSessionRequest
} from '@/lib/types/api'

export function useSourceChat(sourceId: string) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [messages, setMessages] = useState<SourceChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState(false)
  const [contextIndicators, setContextIndicators] = useState<SourceChatContextIndicator | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)
  // Synchronously-applied model selection. `undefined` means "no pending
  // change" (follow the server session); `null` means "reset to default".
  // This closes the race where the sessions-list query still holds the old
  // model after a save: the selector UI and the next request must agree
  // immediately, without waiting for the background refetch.
  const [pendingModelOverride, setPendingModelOverride] = useState<string | null | undefined>(undefined)

  // Fetch sessions
  const { data: sessions = [], isLoading: loadingSessions, refetch: refetchSessions } = useQuery<SourceChatSession[]>({
    queryKey: ['sourceChatSessions', sourceId],
    queryFn: () => sourceChatApi.listSessions(sourceId),
    enabled: !!sourceId
  })

  // Fetch current session with messages
  const { data: currentSession, refetch: refetchCurrentSession } = useQuery({
    queryKey: ['sourceChatSession', sourceId, currentSessionId],
    queryFn: () => sourceChatApi.getSession(sourceId, currentSessionId!),
    enabled: !!sourceId && !!currentSessionId
  })

  // Update messages when session changes
  useEffect(() => {
    if (currentSession?.messages) {
      setMessages(currentSession.messages)
    }
    // Restore the context badge from the persisted session so it survives
    // refresh and session switches (it is otherwise only set live mid-stream).
    if (currentSession?.context_indicators) {
      setContextIndicators(currentSession.context_indicators)
    }
  }, [currentSession])
  // Auto-select most recent session when sessions are loaded
  useEffect(() => {
    if (sessions.length > 0 && !currentSessionId) {
      // Find most recent session (sessions are sorted by created date desc from API)
      const mostRecentSession = sessions[0]
      setCurrentSessionId(mostRecentSession.id)
    }
  }, [sessions, currentSessionId])

  // Session object for the active conversation (source of the persisted model).
  const listedCurrentSession = sessions.find(s => s.id === currentSessionId)
  const serverModelOverride = listedCurrentSession?.model_override ?? undefined
  // Synchronous view of the selected model: a just-saved pending change wins
  // over the sessions-list cache until the server refetch catches up.
  const effectiveModelOverride = pendingModelOverride !== undefined
    ? (pendingModelOverride ?? undefined)
    : serverModelOverride

  // Drop the pending change once the server state reflects it, so the
  // persisted session becomes the single source of truth again.
  useEffect(() => {
    if (
      pendingModelOverride !== undefined &&
      serverModelOverride === (pendingModelOverride ?? undefined)
    ) {
      setPendingModelOverride(undefined)
    }
  }, [pendingModelOverride, serverModelOverride])

  // Create session mutation
  const createSessionMutation = useMutation({
    mutationFn: (data: Omit<CreateSourceChatSessionRequest, 'source_id'>) => 
      sourceChatApi.createSession(sourceId, data),
    onSuccess: (newSession) => {
      queryClient.invalidateQueries({ queryKey: ['sourceChatSessions', sourceId] })
      setCurrentSessionId(newSession.id)
      // A freshly created session starts from the server state.
      setPendingModelOverride(undefined)
      toast.success(t('chat.sessionCreated'))
    },
    onError: (err: unknown) => {
      const error = err as { response?: { data?: { detail?: string } }, message?: string };
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToCreateSession'))
    }
  })

  // Update session mutation
  const updateSessionMutation = useMutation({
    mutationFn: ({ sessionId, data }: { sessionId: string, data: UpdateSourceChatSessionRequest }) =>
      sourceChatApi.updateSession(sourceId, sessionId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['sourceChatSessions', sourceId] })
      queryClient.invalidateQueries({ queryKey: ['sourceChatSession', sourceId, currentSessionId] })
      toast.success(t('chat.sessionUpdated'))
    },
    onError: (err: unknown, variables) => {
      const error = err as { response?: { data?: { detail?: string } }, message?: string };
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToUpdateSession'))
      // The model save failed: revert to the server truth, but only if no
      // newer model change superseded the failed one. Title-only updates
      // never touch the pending model selection.
      if (variables?.data && 'model_override' in variables.data) {
        const failedModel = variables.data.model_override ?? null
        setPendingModelOverride(prev => (prev === failedModel ? undefined : prev))
      }
    }
  })

  // Delete session mutation
  const deleteSessionMutation = useMutation({
    mutationFn: (sessionId: string) => 
      sourceChatApi.deleteSession(sourceId, sessionId),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ['sourceChatSessions', sourceId] })
      if (currentSessionId === deletedId) {
        setCurrentSessionId(null)
        setMessages([])
        // The pending selection belonged to the deleted session.
        setPendingModelOverride(undefined)
      }
      toast.success(t('chat.sessionDeleted'))
    },
    onError: (err: unknown) => {
      const error = err as { response?: { data?: { detail?: string } }, message?: string };
      toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToDeleteSession'))
    }
  })

  // Send message with streaming.
  // The model for this request resolves as: explicit per-message override,
  // then the synchronously-applied selection (pending or persisted session
  // value). The explicit parameter and the pending state agree in the normal
  // UI flow (the composer forwards the effective selection), while the
  // pending fallback covers sends issued before the sessions-list refetch.
  const sendMessage = useCallback(async (message: string, modelOverride?: string) => {
    const resolvedModelOverride = modelOverride ?? effectiveModelOverride
    let sessionId = currentSessionId

    // Auto-create session if none exists
    if (!sessionId) {
      try {
        const defaultTitle = message.length > 30 ? `${message.substring(0, 30)}...` : message
        const newSession = await sourceChatApi.createSession(sourceId, {
          title: defaultTitle,
          ...(resolvedModelOverride ? { model_override: resolvedModelOverride } : {}),
        })
        sessionId = newSession.id
        setCurrentSessionId(sessionId)
        // The pending selection (if any) is now persisted on the new session.
        setPendingModelOverride(undefined)
        queryClient.invalidateQueries({ queryKey: ['sourceChatSessions', sourceId] })
      } catch (err: unknown) {
        const error = err as { response?: { data?: { detail?: string } }, message?: string };
        console.error('Failed to create chat session:', error)
        toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToCreateSession'))
        return
      }
    }

    // Add user message optimistically
    const userMessage: SourceChatMessage = {
      id: `temp-${Date.now()}`,
      type: 'human',
      content: message,
      timestamp: new Date().toISOString()
    }
    setMessages(prev => [...prev, userMessage])
    setIsStreaming(true)

    const controller = new AbortController()
    abortControllerRef.current = controller
    let reader: ReadableStreamDefaultReader<Uint8Array> | null = null

    try {
      const response = await sourceChatApi.sendMessage(sourceId, sessionId, {
        message,
        model_override: resolvedModelOverride
      }, { signal: controller.signal })

      if (!response) {
        throw new Error('No response body')
      }

      reader = response.getReader()
      const decoder = new TextDecoder()
      let aiMessage: SourceChatMessage | null = null
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')

        // Keep the last incomplete line in buffer
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const jsonStr = line.slice(6).trim()
              if (!jsonStr) continue

              const data = JSON.parse(jsonStr)
              
              if (data.type === 'ai_message') {
                // Create AI message on first content chunk to avoid empty bubble
                if (!aiMessage) {
                  aiMessage = {
                    id: `ai-${Date.now()}`,
                    type: 'ai',
                    content: data.content || '',
                    timestamp: new Date().toISOString()
                  }
                  setMessages(prev => [...prev, aiMessage!])
                } else {
                  aiMessage.content += data.content || ''
                  setMessages(prev =>
                    prev.map(msg => msg.id === aiMessage!.id
                      ? { ...msg, content: aiMessage!.content }
                      : msg
                    )
                  )
                }
              } else if (data.type === 'context_indicators') {
                setContextIndicators(data.data)
              } else if (data.type === 'error') {
                throw new Error(data.message || 'Stream error')
              }
            } catch (e) {
              if (e instanceof SyntaxError) {
                console.error('Error parsing SSE data:', e)
              } else {
                throw e
              }
            }
          }
        }
      }
    } catch (err: unknown) {
      const error = err as { response?: { data?: { detail?: string } }, message?: string };
      // User cancellation is cleanup-only: the request is gone, but that is
      // not an error worth surfacing.
      if ((error as { name?: string })?.name === 'AbortError') {
        console.debug('Source chat request aborted')
      } else {
        console.error('Error sending message:', error)
        toast.error(getApiErrorMessage(error.response?.data?.detail || error.message, (key) => t(key), 'apiErrors.failedToSendMessage'))
      }
      // Remove optimistic messages on error
      setMessages(prev => prev.filter(msg => !msg.id.startsWith('temp-')))
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null
      }
      // Release the stream reader so a failed/aborted request never leaves
      // the stream locked; a no-op once the stream was fully consumed.
      try {
        await reader?.cancel()
      } catch {
        // Ignore cleanup errors (already-closed or errored streams).
      }
      setIsStreaming(false)
      // Refetch session to get persisted messages
      refetchCurrentSession()
    }
  }, [sourceId, currentSessionId, effectiveModelOverride, refetchCurrentSession, queryClient, t])

  // Cancel streaming
  const cancelStreaming = useCallback(() => {
    abortControllerRef.current?.abort()
    setIsStreaming(false)
  }, [])

  // Switch session
  const switchSession = useCallback((sessionId: string) => {
    // A pending selection belongs to the previous session; the newly
    // selected session brings its own persisted model.
    setPendingModelOverride(undefined)
    abortControllerRef.current?.abort()
    setCurrentSessionId(sessionId)
    setContextIndicators(null)
  }, [])

  // Create session
  const createSession = useCallback((data: Omit<CreateSourceChatSessionRequest, 'source_id'>) => {
    return createSessionMutation.mutate(data)
  }, [createSessionMutation])

  // Update session
  const updateSession = useCallback((sessionId: string, data: UpdateSourceChatSessionRequest) => {
    return updateSessionMutation.mutate({ sessionId, data })
  }, [updateSessionMutation])

  // Delete session
  const deleteSession = useCallback((sessionId: string) => {
    return deleteSessionMutation.mutate(sessionId)
  }, [deleteSessionMutation])

  // Set the model override. Applies synchronously (selector UI and the next
  // request agree immediately) and persists to the session in the background.
  // `null` resets to the default model. Without a session yet, the value is
  // held pending and applied when sendMessage auto-creates the session.
  const setModelOverride = useCallback((model: string | null) => {
    setPendingModelOverride(model)
    if (currentSessionId) {
      updateSessionMutation.mutate({
        sessionId: currentSessionId,
        data: { model_override: model }
      })
    }
  }, [currentSessionId, updateSessionMutation])

  return {
    // State
    sessions,
    currentSession: listedCurrentSession,
    currentSessionId,
    messages,
    isStreaming,
    contextIndicators,
    loadingSessions,
    // Synchronously-applied model selection (`string`: override id,
    // `null`: pending reset to default, `undefined`: follow the session).
    pendingModelOverride,

    // Actions
    createSession,
    updateSession,
    deleteSession,
    switchSession,
    sendMessage,
    setModelOverride,
    cancelStreaming,
    refetchSessions
  }
}
