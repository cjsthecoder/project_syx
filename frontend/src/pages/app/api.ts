/**
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Thin JSON fetch wrapper for backend API calls.
 *
 * Exports `api`, which sends JSON requests, throws a `RequestError` on non-OK
 * responses, and safely parses and returns the typed JSON body.
 */
import { RequestError, readJsonSafe, throwRequestError } from '@/pages/app/request'

/**
 * Send a JSON request to the backend and return the parsed body.
 *
 * Defaults the content-type to JSON and merges caller `options`.
 *
 * @param path - Backend path or URL to fetch.
 * @param options - Optional `fetch` init merged over the JSON defaults (method, body, headers).
 * @returns The parsed JSON response body, typed as `T`.
 * @throws {RequestError} When the response is not OK, or the body is missing/not valid JSON.
 */
export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) await throwRequestError(res)
  const data = await readJsonSafe<T>(res)
  if (data === null) {
    throw new RequestError('Invalid JSON response', res.status, null)
  }
  return data
}
