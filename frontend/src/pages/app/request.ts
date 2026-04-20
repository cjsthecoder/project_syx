/**
 * Copyright (c) 2025 Syx Project Contributors. All rights reserved.
 *
 * This source code is part of the Syx project and is proprietary.
 *
 * Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.
 *
 * Use of this software requires explicit written permission from the copyright holder.
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
