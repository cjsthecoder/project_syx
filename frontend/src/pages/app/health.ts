/**
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Frontend helpers for backend health and LLM availability messaging.
 */
import { api } from '@/pages/app/api'
import { RequestError, extractErrorCode } from '@/pages/app/request'

export const LLM_NOT_CONFIGURED_CODE = 'llm_not_configured'
export const LLM_NOT_CONFIGURED_MESSAGE =
  'The active LLM provider API key is not configured. Set the provider API key in the backend environment and restart the server.'

export type AppHealthResponse = {
  status: string
  dependencies?: Record<string, string>
}

/**
 * Convert backend health status into a persistent app notice message.
 *
 * @param health - Parsed `/health` response from the backend.
 * @returns A user-facing warning when chat cannot use the configured LLM.
 */
export function messageForAppHealth(health: AppHealthResponse): string | null {
  const llmProviderMissing =
    health.dependencies?.openai === 'missing' || health.dependencies?.anthropic === 'missing'
  if (llmProviderMissing) {
    return LLM_NOT_CONFIGURED_MESSAGE
  }
  return null
}

/**
 * Load app health and return the current persistent LLM notice, if any.
 *
 * @returns A warning message when `/health` reports the active LLM key is missing.
 */
export async function loadAppHealth(): Promise<string | null> {
  const health = await api<AppHealthResponse>('/health')
  return messageForAppHealth(health)
}

/**
 * Test whether a caught request error represents an unconfigured LLM.
 *
 * @param error - Error raised by the chat request path.
 * @returns True when the backend returned the stable `llm_not_configured` code.
 */
export function isLlmNotConfiguredError(error: unknown): boolean {
  return error instanceof RequestError && extractErrorCode(error.body) === LLM_NOT_CONFIGURED_CODE
}

/**
 * Map chat-send failures to user-facing messages.
 *
 * @param error - Error raised while sending or streaming a chat message.
 * @returns A clear message for known configuration failures, otherwise the original error message.
 */
export function messageForChatError(error: unknown): string {
  if (isLlmNotConfiguredError(error)) {
    return LLM_NOT_CONFIGURED_MESSAGE
  }
  return error instanceof Error ? error.message : 'Stream failed'
}
