/**
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Tests for toDreamViewState payload normalization.
 */
import { describe, expect, it } from 'vitest'
import { toDreamViewState } from '@/pages/app/dream'

describe('toDreamViewState', () => {
  it('returns empty state for non-object input', () => {
    expect(toDreamViewState(null)).toEqual({
      projectSummary: null,
      hasDreamItems: false,
      dreamItems: [],
    })
    expect(toDreamViewState('nope').projectSummary).toBeNull()
  })

  it('trims the summary and reports no items when items are empty', () => {
    const state = toDreamViewState({ project_summary: '  hello  ', items: [] })
    expect(state.projectSummary).toBe('hello')
    expect(state.hasDreamItems).toBe(false)
  })

  it('treats a blank summary as null', () => {
    expect(toDreamViewState({ project_summary: '   ', items: [{ origin_text: 'x' }] }).projectSummary).toBeNull()
  })

  it('normalizes items and drops empty ones', () => {
    const state = toDreamViewState({
      project_summary: 'summary',
      items: [
        { id: 'k1', origin_text: 'why?', research: [{ research_topic: 't', research_summary: 's' }] },
        { id: 'k2', assistant_response: 'answer' },
        { id: 'empty' }, // no origin_text/assistant_response -> dropped
      ],
    })
    expect(state.hasDreamItems).toBe(true)
    expect(state.dreamItems).toHaveLength(2)
    expect(state.dreamItems[0]).toMatchObject({
      id: 'k1',
      origin_text: 'why?',
      keep: false,
      remember: false,
    })
    expect(state.dreamItems[0].research).toEqual([{ research_topic: 't', research_summary: 's' }])
  })

  it('coerces non-string fields to undefined and non-array research to []', () => {
    const state = toDreamViewState({
      project_summary: 'summary',
      items: [{ origin_text: 'x', id: 123, research: 'bad' }],
    })
    expect(state.dreamItems[0].id).toBeUndefined()
    expect(state.dreamItems[0].research).toEqual([])
  })
})
