/**
 * Copyright (c) 2025-2026 Syx Project Contributors
 *
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Tests for HTTP response/error helpers in request.ts.
 */
import { describe, expect, it } from 'vitest'
import {
  RequestError,
  extractErrorMessage,
  parseResponseBody,
  readJsonSafe,
  throwRequestError,
} from '@/pages/app/request'

describe('extractErrorMessage', () => {
  it('returns the fallback for empty payloads', () => {
    expect(extractErrorMessage(null)).toBe('Request failed')
    expect(extractErrorMessage(undefined, 'oops')).toBe('oops')
  })

  it('returns a string payload directly', () => {
    expect(extractErrorMessage('boom')).toBe('boom')
  })

  it('prefers detail, then error, then message', () => {
    expect(extractErrorMessage({ detail: 'd', error: 'e', message: 'm' })).toBe('d')
    expect(extractErrorMessage({ error: 'e', message: 'm' })).toBe('e')
    expect(extractErrorMessage({ message: 'm' })).toBe('m')
  })

  it('falls back when fields are blank or missing', () => {
    expect(extractErrorMessage({ detail: '   ' }, 'fb')).toBe('fb')
    expect(extractErrorMessage({ other: 'x' }, 'fb')).toBe('fb')
  })
})

describe('parseResponseBody / readJsonSafe', () => {
  it('parses JSON bodies', async () => {
    const res = new Response(JSON.stringify({ a: 1 }), { status: 200 })
    expect(await parseResponseBody(res)).toEqual({ a: 1 })
  })

  it('returns raw text for non-JSON bodies', async () => {
    const res = new Response('plain text', { status: 200 })
    expect(await parseResponseBody(res)).toBe('plain text')
  })

  it('returns null for empty bodies', async () => {
    const res = new Response('', { status: 200 })
    expect(await parseResponseBody(res)).toBeNull()
  })

  it('readJsonSafe returns objects and null for non-objects', async () => {
    expect(await readJsonSafe(new Response(JSON.stringify({ ok: true })))).toEqual({ ok: true })
    expect(await readJsonSafe(new Response('not json'))).toBeNull()
  })
})

describe('throwRequestError', () => {
  it('throws a RequestError carrying status, message, and body', async () => {
    const res = new Response(JSON.stringify({ detail: 'bad input' }), { status: 422 })
    await expect(throwRequestError(res)).rejects.toBeInstanceOf(RequestError)
    try {
      await throwRequestError(new Response(JSON.stringify({ detail: 'bad input' }), { status: 422 }))
    } catch (e) {
      const err = e as RequestError
      expect(err.status).toBe(422)
      expect(err.message).toBe('bad input')
      expect(err.body).toEqual({ detail: 'bad input' })
    }
  })

  it('uses an HTTP status fallback message when no body message is present', async () => {
    try {
      await throwRequestError(new Response('', { status: 500 }))
    } catch (e) {
      expect((e as RequestError).message).toBe('HTTP 500')
    }
  })
})
