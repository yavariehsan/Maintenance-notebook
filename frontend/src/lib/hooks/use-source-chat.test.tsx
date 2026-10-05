/* eslint-disable @typescript-eslint/no-explicit-any */
import React from 'react'
import { renderHook, act, waitFor } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useSourceChat } from './use-source-chat'
import { sourceChatApi } from '@/lib/api/source-chat'

vi.mock('@/lib/api/source-chat', () => ({
  sourceChatApi: {
    createSession: vi.fn(),
    listSessions: vi.fn(),
    getSession: vi.fn(),
    updateSession: vi.fn(),
    sendMessage: vi.fn(),
  },
}))

vi.mock('sonner', () => ({
  toast: { error: vi.fn(), success: vi.fn() },
}))

const PROVIDER_ERROR =
  'The AI provider is temporarily unavailable. Please try again in a few minutes.'

function sseStream(events: Array<Record<string, unknown>>) {
  const encoder = new TextEncoder()
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const event of events) {
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(event)}\n\n`))
      }
      controller.close()
    },
  })
}

function successStream(content = 'answer') {
  return sseStream([
    { type: 'ai_message', content },
    { type: 'context_indicators', data: { sources: [], insights: [], notes: [] } },
    { type: 'complete' },
  ]) as any
}

function errorStream(message = PROVIDER_ERROR) {
  return sseStream([{ type: 'error', message }]) as any
}

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const sessionA = {
  id: 's1',
  title: 'Session',
  source_id: 'source:x',
  model_override: 'model-a',
  created: '2026-01-01',
  updated: '2026-01-01',
}

type HookResult = ReturnType<typeof useSourceChat>

/** Mirrors the page-level prop: pending-first effective model selection. */
function effectiveModel(result: { current: HookResult }) {
  const pending = result.current.pendingModelOverride
  return pending !== undefined
    ? (pending ?? undefined)
    : result.current.currentSession?.model_override
}

async function renderWithSessionA() {
  vi.mocked(sourceChatApi.listSessions).mockResolvedValue([sessionA] as any)
  vi.mocked(sourceChatApi.getSession).mockResolvedValue({
    ...sessionA,
    messages: [],
  } as any)
  const hook = renderHook(() => useSourceChat('source:x'), {
    wrapper: makeWrapper(),
  })
  await waitFor(() => expect(hook.result.current.currentSessionId).toBe('s1'))
  return hook.result
}

describe('useSourceChat model failure/recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('uses the newly selected model on the next request (A -> B, no error)', async () => {
    const result = await renderWithSessionA()
    // The sessions list has not refetched with B yet (stale cache).
    vi.mocked(sourceChatApi.updateSession).mockResolvedValue({
      ...sessionA,
      model_override: 'model-b',
    } as any)
    vi.mocked(sourceChatApi.sendMessage).mockResolvedValue(successStream('b'))

    await act(async () => {
      result.current.setModelOverride('model-b')
    })

    // The selection applies synchronously, before any refetch.
    expect(result.current.pendingModelOverride).toBe('model-b')
    expect(effectiveModel(result)).toBe('model-b')
    // ... and the session persist call carries the new model.
    expect(vi.mocked(sourceChatApi.updateSession)).toHaveBeenCalledWith(
      'source:x',
      's1',
      { model_override: 'model-b' }
    )

    await act(async () => {
      await result.current.sendMessage('question', effectiveModel(result))
    })

    expect(vi.mocked(sourceChatApi.sendMessage).mock.calls[0][2]).toMatchObject({
      message: 'question',
      model_override: 'model-b',
    })
    expect(result.current.isStreaming).toBe(false)
  })

  it('recovers after an SSE provider failure: next request uses model B', async () => {
    const result = await renderWithSessionA()
    vi.mocked(sourceChatApi.updateSession).mockResolvedValue({
      ...sessionA,
      model_override: 'model-b',
    } as any)
    vi.mocked(sourceChatApi.sendMessage)
      .mockResolvedValueOnce(errorStream())
      .mockResolvedValueOnce(successStream('answer-b'))

    // 1-3. Model A fails with a provider error; the request finishes cleanly.
    await act(async () => {
      await result.current.sendMessage('q1', 'model-a')
    })
    expect(result.current.isStreaming).toBe(false)
    expect(result.current.messages.filter((m) => m.id.startsWith('temp-'))).toHaveLength(0)

    // 4-5. Switch to B. 6. Send again.
    await act(async () => {
      result.current.setModelOverride('model-b')
    })
    expect(effectiveModel(result)).toBe('model-b')
    await act(async () => {
      await result.current.sendMessage('q2', effectiveModel(result))
    })

    // 7-9. The second request carries B (A is not reused) and its answer lands.
    const calls = vi.mocked(sourceChatApi.sendMessage).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[0][2]).toMatchObject({ model_override: 'model-a' })
    expect(calls[1][2]).toMatchObject({ message: 'q2', model_override: 'model-b' })
    expect(result.current.isStreaming).toBe(false)
    expect(result.current.messages.some((m) => m.content === 'answer-b')).toBe(true)
  })

  it('recovers after a network failure: next request uses model B', async () => {
    const result = await renderWithSessionA()
    vi.mocked(sourceChatApi.updateSession).mockResolvedValue({
      ...sessionA,
      model_override: 'model-b',
    } as any)
    vi.mocked(sourceChatApi.sendMessage)
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce(successStream('answer-b'))

    await act(async () => {
      await result.current.sendMessage('q1', 'model-a')
    })
    expect(result.current.isStreaming).toBe(false)

    await act(async () => {
      result.current.setModelOverride('model-b')
    })
    await act(async () => {
      await result.current.sendMessage('q2', effectiveModel(result))
    })

    const calls = vi.mocked(sourceChatApi.sendMessage).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[1][2]).toMatchObject({ model_override: 'model-b' })
    expect(result.current.isStreaming).toBe(false)
  })

  it('repeated retry with the same model reuses it', async () => {
    const result = await renderWithSessionA()
    vi.mocked(sourceChatApi.sendMessage)
      .mockResolvedValueOnce(errorStream())
      .mockResolvedValueOnce(successStream('retry-ok'))

    await act(async () => {
      await result.current.sendMessage('q1', 'model-a')
    })
    await act(async () => {
      await result.current.sendMessage('q1 again', 'model-a')
    })

    const calls = vi.mocked(sourceChatApi.sendMessage).mock.calls
    expect(calls).toHaveLength(2)
    expect(calls[0][2]).toMatchObject({ model_override: 'model-a' })
    expect(calls[1][2]).toMatchObject({ model_override: 'model-a' })
    expect(result.current.isStreaming).toBe(false)
  })

  it('reset to default clears the override and omits it from the next request', async () => {
    const result = await renderWithSessionA()
    vi.mocked(sourceChatApi.updateSession).mockResolvedValue({
      ...sessionA,
      model_override: null,
    } as any)
    vi.mocked(sourceChatApi.sendMessage).mockResolvedValue(successStream('ok'))

    await act(async () => {
      result.current.setModelOverride(null)
    })

    expect(vi.mocked(sourceChatApi.updateSession)).toHaveBeenCalledWith(
      'source:x',
      's1',
      { model_override: null }
    )
    expect(effectiveModel(result)).toBeUndefined()

    await act(async () => {
      await result.current.sendMessage('q', effectiveModel(result))
    })
    expect(
      vi.mocked(sourceChatApi.sendMessage).mock.calls[0][2].model_override
    ).toBeUndefined()
  })

  it('leaves no stuck streaming state after malformed SSE data', async () => {
    const result = await renderWithSessionA()
    const encoder = new TextEncoder()
    const malformed = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {broken json\n\n'))
        controller.enqueue(
          encoder.encode(`data: ${JSON.stringify({ type: 'complete' })}\n\n`)
        )
        controller.close()
      },
    })
    vi.mocked(sourceChatApi.sendMessage).mockResolvedValue(malformed as any)

    await act(async () => {
      await result.current.sendMessage('q', 'model-a')
    })

    expect(result.current.isStreaming).toBe(false)
  })

  it('documents the stale-cache window the pending selection closes', async () => {
    // Characterization: the raw `currentSession?.model_override` prop only
    // changes after the sessions list refetches. The composer used to forward
    // exactly that prop, so a send issued before the refetch reused the old
    // model. setModelOverride/pendingModelOverride exist to close it.
    const result = await renderWithSessionA()
    vi.mocked(sourceChatApi.updateSession).mockResolvedValue({
      ...sessionA,
      model_override: 'model-b',
    } as any)
    vi.mocked(sourceChatApi.sendMessage).mockResolvedValue(successStream('ok'))

    await act(async () => {
      result.current.updateSession('s1', { model_override: 'model-b' })
    })

    // listSessions still returns A: the raw prop lags behind the PUT.
    expect(result.current.currentSession?.model_override).toBe('model-a')
    await act(async () => {
      await result.current.sendMessage(
        'follow-up',
        result.current.currentSession?.model_override
      )
    })
    expect(vi.mocked(sourceChatApi.sendMessage).mock.calls[0][2]).toMatchObject({
      model_override: 'model-a',
    })
  })
})

describe('useSourceChat streaming decoder and badges (P1.4)', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('restores context indicators from the loaded session', async () => {
    const indicators = { sources: ['source:x'], insights: ['i1'], notes: [] }
    vi.mocked(sourceChatApi.listSessions).mockResolvedValue([sessionA] as any)
    vi.mocked(sourceChatApi.getSession).mockResolvedValue({
      ...sessionA,
      messages: [],
      context_indicators: indicators,
    } as any)
    const hook = renderHook(() => useSourceChat('source:x'), {
      wrapper: makeWrapper(),
    })
    await waitFor(() => expect(hook.result.current.currentSessionId).toBe('s1'))
    await waitFor(() =>
      expect(hook.result.current.contextIndicators).toEqual(indicators)
    )
  })

  it('reassembles a UTF-8 event split mid-multibyte-character', async () => {
    const result = await renderWithSessionA()
    const content = 'پاسخ کامل مدل'
    const event = `data: ${JSON.stringify({ type: 'ai_message', content })}\n\n`
    // Prefix is pure ASCII, so the string index of the first Persian
    // character equals its UTF-8 byte offset; +1 lands mid-character.
    const splitAt = event.indexOf('پ') + 1
    const bytes = new TextEncoder().encode(event)
    const split = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(bytes.slice(0, splitAt))
        controller.enqueue(bytes.slice(splitAt))
        controller.close()
      },
    })
    const tail = `data: ${JSON.stringify({ type: 'complete' })}\n\n`
    const combined = new ReadableStream<Uint8Array>({
      async start(controller) {
        const reader = split.getReader()
        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          controller.enqueue(value)
        }
        controller.enqueue(new TextEncoder().encode(tail))
        controller.close()
      },
    })
    vi.mocked(sourceChatApi.sendMessage).mockResolvedValue(combined as any)

    await act(async () => {
      await result.current.sendMessage('q', 'model-a')
    })

    const aiMessages = result.current.messages.filter((m) => m.type === 'ai')
    expect(aiMessages).toHaveLength(1)
    expect(aiMessages[0].content).toBe(content)
  })

  it('decodes multiple events arriving in a single chunk', async () => {
    const result = await renderWithSessionA()
    const indicators = { sources: ['source:x'], insights: [], notes: [] }
    const encoder = new TextEncoder()
    const oneChunk = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            `data: ${JSON.stringify({ type: 'ai_message', content: 'hi' })}\n\n` +
              `data: ${JSON.stringify({ type: 'context_indicators', data: indicators })}\n\n` +
              `data: ${JSON.stringify({ type: 'complete' })}\n\n`
          )
        )
        controller.close()
      },
    })
    vi.mocked(sourceChatApi.sendMessage).mockResolvedValue(oneChunk as any)

    await act(async () => {
      await result.current.sendMessage('q', 'model-a')
    })

    expect(
      result.current.messages.some((m) => m.type === 'ai' && m.content === 'hi')
    ).toBe(true)
    expect(result.current.contextIndicators).toEqual(indicators)
  })
})
