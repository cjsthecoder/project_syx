/**
 * Copyright (c) 2025-2026 Syx Project Contributors
 *
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * HTTP response and error handling utilities.
 *
 * Defines the `RequestError` class and helpers for safely reading response
 * text/JSON, extracting error messages from varied payload shapes, and throwing
 * a normalized error for failed responses.
 */
export class RequestError extends Error {
  status: number
  body: unknown

  constructor(message: string, status: number, body: unknown) {
    super(message)
    this.name = 'RequestError'
    this.status = status
    this.body = body
  }
}

export async function readTextSafe(res: Response): Promise<string> {
  try {
    return await res.text()
  } catch {
    return ''
  }
}

export function extractErrorMessage(payload: unknown, fallback = 'Request failed'): string {
  if (!payload) return fallback
  if (typeof payload === 'string') return payload || fallback
  if (typeof payload === 'object') {
    const obj = payload as Record<string, unknown>
    const detail = obj.detail
    if (typeof detail === 'string' && detail.trim()) return detail
    if (typeof obj.error === 'string' && obj.error.trim()) return obj.error
    if (typeof obj.message === 'string' && obj.message.trim()) return obj.message
  }
  return fallback
}

export async function parseResponseBody(res: Response): Promise<unknown> {
  const raw = await readTextSafe(res)
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return raw
  }
}

export async function throwRequestError(res: Response): Promise<never> {
  const body = await parseResponseBody(res)
  const message = extractErrorMessage(body, `HTTP ${res.status}`)
  throw new RequestError(message, res.status, body)
}

export async function readJsonSafe<T>(res: Response): Promise<T | null> {
  const body = await parseResponseBody(res)
  if (body && typeof body === 'object') {
    return body as T
  }
  return null
}
