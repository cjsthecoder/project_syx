/**
 * Copyright (c) 2025 Christopher Shuler. All rights reserved.
 *
 * This source code is part of the Syx project and is proprietary.
 *
 * Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.
 *
 * Use of this software requires explicit written permission from the copyright holder.
 */
export type Message = {
  id?: number
  clientId?: string
  role: 'user' | 'assistant'
  content: string
  forget?: boolean
  keep?: boolean
  streamComplete?: boolean
}

export type Project = { id: string; name?: string }

export type ModelItem = string

export type DreamResearch = {
  research_topic?: string
  research_summary?: string
}

export type DreamItem = {
  id?: string
  origin_text?: string
  assistant_response?: string
  origin_type?: string
  source_resolution?: string
  research?: DreamResearch[]
  keep?: boolean
  remember?: boolean
}

export type ProjectStats = {
  storage_bytes: number
  index_size_bytes: number
  tokens_indexed: number
  context_tokens: number
  file_count: number
  daily_index_size_bytes?: number
  daily_tokens_indexed?: number
  daily_vector_count?: number
  active_pairs?: number
}

export type ProjectInfo = {
  name?: string
  description?: string
  created_at?: string
  system?: boolean
  daily_rag_enabled?: boolean
}
