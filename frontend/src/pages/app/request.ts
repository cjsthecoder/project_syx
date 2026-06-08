/**
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
/** Error thrown for failed HTTP responses, carrying the status code and parsed body. */
export class RequestError extends Error {
  status: number
  body: unknown

  /**
   * @param message - Human-readable error message.
   * @param status - HTTP status code of the failed response.
   * @param body - Parsed response body (object, string, or null) for diagnostics.
   */
  constructor(message: string, status: number, body: unknown) {
    super(message)
    this.name = 'RequestError'
    this.status = status
    this.body = body
  }
}

/**
 * Read a response body as text, returning an empty string if reading throws.
 *
 * @param res - The response whose body to read.
 * @returns The body text, or an empty string on failure.
 */
export async function readTextSafe(res: Response): Promise<string> {
  try {
    return await res.text()
  } catch {
    return ''
  }
}

/**
 * Derive a human-readable message from an error payload of unknown shape.
 *
 * Accepts a plain string or an object, checking `detail`, then `error`, then
 * `message`, and returns `fallback` when none are usable.
 *
 * @param payload - The raw error payload (string, object, or nullish).
 * @param fallback - Message to use when no usable field is found.
 * @returns The extracted message, or `fallback`.
 */
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

/**
 * Read a response body and JSON-parse it, falling back to raw text, or null when empty.
 *
 * @param res - The response whose body to read.
 * @returns The parsed JSON value, the raw text if not JSON, or null when the body is empty.
 */
export async function parseResponseBody(res: Response): Promise<unknown> {
  const raw = await readTextSafe(res)
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return raw
  }
}

/**
 * Throw a normalized {@link RequestError} for a failed response, deriving the
 * message from the parsed body.
 *
 * @param res - The failed response to convert into an error.
 * @returns Never returns; always throws.
 * @throws {RequestError} Always, carrying the status and parsed body.
 */
export async function throwRequestError(res: Response): Promise<never> {
  const body = await parseResponseBody(res)
  const message = extractErrorMessage(body, `HTTP ${res.status}`)
  throw new RequestError(message, res.status, body)
}

/**
 * Parse a response body as a JSON object, returning null when it is empty or not an object.
 *
 * @param res - The response whose body to parse.
 * @returns The parsed object typed as `T`, or null when the body is empty or not an object.
 */
export async function readJsonSafe<T>(res: Response): Promise<T | null> {
  const body = await parseResponseBody(res)
  if (body && typeof body === 'object') {
    return body as T
  }
  return null
}
