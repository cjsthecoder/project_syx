/**
 * Copyright (c) 2025-2026 Syx Project Contributors. All rights reserved.
 *
 * This source code is part of the Syx project and is proprietary.
 *
 * Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.
 *
 * Use of this software requires explicit written permission from the copyright holder.
 */
import { RequestError, readJsonSafe, throwRequestError } from '@/pages/app/request'

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
