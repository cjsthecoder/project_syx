/**
 * Copyright (c) 2025-2026 Syx Project Contributors
 *
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Helpers for transforming raw dream API payloads into view state.
 *
 * Exports `toDreamViewState`, which validates and normalizes the project
 * summary and dream items from an untyped payload into a typed structure for
 * rendering.
 */
import { DreamItem } from '@/pages/app/types'

type DreamViewState = {
  projectSummary: string | null
  hasDreamItems: boolean
  dreamItems: DreamItem[]
}

type DreamResearchPayload = {
  research_topic?: unknown
  research_summary?: unknown
}

type DreamItemPayload = {
  id?: unknown
  origin_text?: unknown
  assistant_response?: unknown
  origin_type?: unknown
  source_resolution?: unknown
  research?: unknown
}

type DreamPayload = {
  project_summary?: unknown
  items?: unknown
}

function _normalizeDreamItems(items: DreamItemPayload[]): DreamItem[] {
  return items
    .filter((it) => it && (it.origin_text || it.assistant_response))
    .map((it) => ({
      id: typeof it.id === 'string' ? it.id : undefined,
      origin_text: typeof it.origin_text === 'string' ? it.origin_text : undefined,
      assistant_response: typeof it.assistant_response === 'string' ? it.assistant_response : undefined,
      origin_type: typeof it.origin_type === 'string' ? it.origin_type : undefined,
      source_resolution: typeof it.source_resolution === 'string' ? it.source_resolution : undefined,
      research: Array.isArray(it.research)
        ? (it.research as DreamResearchPayload[]).map((r) => ({
            research_topic: typeof r?.research_topic === 'string' ? r.research_topic : undefined,
            research_summary: typeof r?.research_summary === 'string' ? r.research_summary : undefined,
          }))
        : [],
      keep: false,
      remember: false,
    }))
}

export function toDreamViewState(dream: unknown): DreamViewState {
  const payload = (dream && typeof dream === 'object' ? dream : {}) as DreamPayload
  const summary = payload.project_summary
  const items = Array.isArray(payload.items) ? (payload.items as DreamItemPayload[]) : []
  const hasSummary = typeof summary === 'string' && summary.trim().length > 0
  return {
    projectSummary: hasSummary ? summary.trim() : null,
    hasDreamItems: hasSummary && items.length > 0,
    dreamItems: _normalizeDreamItems(items),
  }
}
