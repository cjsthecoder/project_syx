import { DreamItem } from '@/pages/app/types'

type DreamViewState = {
  projectSummary: string | null
  hasDreamItems: boolean
  dreamItems: DreamItem[]
}

function _normalizeDreamItems(items: any[]): DreamItem[] {
  return items
    .filter((it: any) => it && (it.origin_text || it.assistant_response))
    .map((it: any) => ({
      id: it.id,
      origin_text: it.origin_text,
      assistant_response: it.assistant_response,
      origin_type: it.origin_type,
      source_resolution: it.source_resolution,
      research: Array.isArray(it.research)
        ? it.research.map((r: any) => ({
            research_topic: r?.research_topic,
            research_summary: r?.research_summary,
          }))
        : [],
      keep: false,
      remember: false,
    }))
}

export function toDreamViewState(dream: any): DreamViewState {
  const summary = dream?.project_summary
  const items = Array.isArray(dream?.items) ? dream.items : []
  const hasSummary = typeof summary === 'string' && summary.trim().length > 0
  return {
    projectSummary: hasSummary ? summary.trim() : null,
    hasDreamItems: hasSummary && items.length > 0,
    dreamItems: _normalizeDreamItems(items),
  }
}
