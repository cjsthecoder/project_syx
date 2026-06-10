/**
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Tests for frontend health and chat-error message helpers.
 */
import { describe, expect, it } from 'vitest'
import {
  LLM_NOT_CONFIGURED_MESSAGE,
  isLlmNotConfiguredError,
  messageForAppHealth,
  messageForChatError,
} from '@/pages/app/health'
import { RequestError } from '@/pages/app/request'

describe('messageForAppHealth', () => {
  it('returns the persistent LLM warning when OpenAI is missing', () => {
    expect(messageForAppHealth({ status: 'degraded', dependencies: { openai: 'missing' } })).toBe(
      LLM_NOT_CONFIGURED_MESSAGE,
    )
  })

  it('returns null when OpenAI is configured', () => {
    expect(messageForAppHealth({ status: 'healthy', dependencies: { openai: 'configured' } })).toBeNull()
  })
})

describe('messageForChatError', () => {
  it('maps structured llm_not_configured request errors', () => {
    const error = new RequestError(
      'HTTP 503',
      503,
      { detail: { error_code: 'llm_not_configured', error: 'missing key' } },
    )

    expect(isLlmNotConfiguredError(error)).toBe(true)
    expect(messageForChatError(error)).toBe(LLM_NOT_CONFIGURED_MESSAGE)
  })

  it('preserves generic error messages', () => {
    expect(messageForChatError(new Error('stream exploded'))).toBe('stream exploded')
  })
})
