/**
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Tests for the `api` JSON fetch wrapper.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/pages/app/api'
import { RequestError } from '@/pages/app/request'

afterEach(() => {
  vi.unstubAllGlobals()
})

function stubFetch(impl: (path: string, options?: RequestInit) => Response) {
  vi.stubGlobal(
    'fetch',
    vi.fn((path: string, options?: RequestInit) => Promise.resolve(impl(path, options))),
  )
}

describe('api', () => {
  it('sends JSON content-type and returns the parsed body', async () => {
    const fetchSpy = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ ok: true }), { status: 200 })))
    vi.stubGlobal('fetch', fetchSpy)

    const data = await api<{ ok: boolean }>('/projects')

    expect(data).toEqual({ ok: true })
    expect(fetchSpy).toHaveBeenCalledWith(
      '/projects',
      expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
    )
  })

  it('merges caller options over defaults', async () => {
    const fetchSpy = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ id: 'p1' }), { status: 200 })))
    vi.stubGlobal('fetch', fetchSpy)

    await api('/projects', { method: 'POST', body: '{"x":1}' })

    expect(fetchSpy).toHaveBeenCalledWith(
      '/projects',
      expect.objectContaining({ method: 'POST', body: '{"x":1}' }),
    )
  })

  it('throws a RequestError on non-OK responses', async () => {
    stubFetch(() => new Response(JSON.stringify({ detail: 'denied' }), { status: 403 }))
    await expect(api('/projects')).rejects.toMatchObject({
      name: 'RequestError',
      status: 403,
      message: 'denied',
    })
  })

  it('throws when the body is not valid JSON object', async () => {
    stubFetch(() => new Response('not-json', { status: 200 }))
    await expect(api('/projects')).rejects.toBeInstanceOf(RequestError)
  })
})
