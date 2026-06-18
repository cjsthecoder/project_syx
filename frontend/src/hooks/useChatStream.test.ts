/**
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Tests for the useChatStream hook.
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useChatStream } from '@/hooks/useChatStream'
import { LLM_NOT_CONFIGURED_MESSAGE } from '@/pages/app/health'

afterEach(() => {
  vi.unstubAllGlobals()
})

function renderChatHook(overrides: Partial<Parameters<typeof useChatStream>[0]> = {}) {
  const onError = vi.fn()
  const checkSleeping = vi.fn(() => Promise.resolve(false))
  const result = renderHook(() =>
    useChatStream({
      projectId: 'p1',
      model: 'gpt-test',
      onError,
      checkSleeping,
      ...overrides,
    }),
  )
  return { ...result, onError, checkSleeping }
}

describe('useChatStream', () => {
  it('disables sends when app health marks chat unavailable', async () => {
    const fetchSpy = vi.fn()
    vi.stubGlobal('fetch', fetchSpy)
    const { result, checkSleeping } = renderChatHook({ chatEnabled: false })

    act(() => {
      result.current.setInput('hello')
    })

    expect(result.current.canSend).toBe(false)
    await act(async () => {
      await result.current.send()
    })

    expect(fetchSpy).not.toHaveBeenCalled()
    expect(checkSleeping).not.toHaveBeenCalled()
  })

  it('maps structured llm_not_configured stream failures to setup guidance', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              detail: {
                error: 'ANTHROPIC_API_KEY is not configured',
                error_code: 'llm_not_configured',
              },
            }),
            { status: 503, headers: { 'Content-Type': 'application/json' } },
          ),
        ),
      ),
    )
    const { result, onError } = renderChatHook()

    act(() => {
      result.current.setInput('hello')
    })
    await waitFor(() => expect(result.current.canSend).toBe(true))

    await act(async () => {
      await result.current.send()
    })

    expect(onError).toHaveBeenCalledWith(LLM_NOT_CONFIGURED_MESSAGE)
  })
})
