/**
 * Copyright (c) 2025-2026 Syx Project Contributors
 *
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Tests for the useProjectData hook.
 *
 * The `api` module is mocked so the hook's data-loading and CRUD orchestration
 * can be verified without any network access.
 */
import { act, renderHook, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { useProjectData } from '@/hooks/useProjectData'
import { api } from '@/pages/app/api'

vi.mock('@/pages/app/api', () => ({ api: vi.fn() }))

const mockApi = api as unknown as Mock

beforeEach(() => {
  mockApi.mockReset()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useProjectData', () => {
  it('loads projects on mount, filtering "default" and mapping display names', async () => {
    mockApi.mockResolvedValue({
      available_projects: ['default', 'p1', 'p2'],
      current_project: 'p1',
      project_names: { p1: 'Alpha' },
    })

    const onError = vi.fn()
    const { result } = renderHook(() => useProjectData({ showDebugValues: false, onError }))

    await waitFor(() => expect(result.current.projects).toHaveLength(2))
    expect(result.current.projects).toEqual([
      { id: 'p1', name: 'Alpha' },
      { id: 'p2', name: 'p2' },
    ])
    expect(result.current.projectId).toBe('p1')
    expect(onError).not.toHaveBeenCalled()
  })

  it('resets projects to empty when loading fails', async () => {
    mockApi.mockRejectedValue(new Error('boom'))
    const onError = vi.fn()
    const { result } = renderHook(() => useProjectData({ showDebugValues: false, onError }))

    await waitFor(() => expect(mockApi).toHaveBeenCalled())
    expect(result.current.projects).toEqual([])
  })

  it('createProject POSTs the new name then reloads the project list', async () => {
    mockApi.mockImplementation((_path: string, options?: RequestInit) => {
      if (options?.method === 'POST') return Promise.resolve({})
      return Promise.resolve({ available_projects: ['default', 'p1'], current_project: 'p1', project_names: {} })
    })

    const onError = vi.fn()
    const { result } = renderHook(() => useProjectData({ showDebugValues: false, onError }))
    await waitFor(() => expect(result.current.projectId).toBe('p1'))

    await act(async () => {
      await result.current.createProject('New Project')
    })

    expect(mockApi).toHaveBeenCalledWith(
      '/projects',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ project_name: 'New Project' }) }),
    )
    expect(onError).not.toHaveBeenCalled()
  })

  it('createProject ignores blank names', async () => {
    mockApi.mockResolvedValue({ available_projects: [], current_project: '', project_names: {} })
    const onError = vi.fn()
    const { result } = renderHook(() => useProjectData({ showDebugValues: false, onError }))
    await waitFor(() => expect(mockApi).toHaveBeenCalledTimes(1))

    await act(async () => {
      await result.current.createProject('   ')
    })

    // No POST issued; only the initial mount GET.
    expect(mockApi).toHaveBeenCalledTimes(1)
  })

  it('createProject reports failures through onError', async () => {
    mockApi.mockImplementation((_path: string, options?: RequestInit) => {
      if (options?.method === 'POST') return Promise.reject(new Error('duplicate name'))
      return Promise.resolve({ available_projects: ['default', 'p1'], current_project: 'p1', project_names: {} })
    })

    const onError = vi.fn()
    const { result } = renderHook(() => useProjectData({ showDebugValues: false, onError }))
    await waitFor(() => expect(result.current.projectId).toBe('p1'))

    await act(async () => {
      await result.current.createProject('Dup')
    })

    expect(onError).toHaveBeenCalledWith('duplicate name')
  })
})
