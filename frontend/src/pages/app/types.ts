/**
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Shared TypeScript type definitions for the chat app.
 *
 * Declares the data shapes used across the app pages and hooks, including
 * `Message`, `Project`, `ModelItem`, `DreamItem`/`DreamResearch`,
 * `ProjectStats`, and `ProjectInfo`.
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

export type ProjectFile = {
  id: number
  filename: string
  size_bytes: number
}

export type Tone = 'analytical' | 'friendly' | 'creative' | 'formal'
export type Verbosity = 'concise' | 'balanced' | 'detailed'
export type FormatPref = 'markdown' | 'plain' | 'html'

export type Personality = {
  tone?: string
  verbosity?: string
  format?: string
  creativity?: number | string
  domain_focus?: string[] | string
}

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
  file_count: number
  daily_index_size_bytes?: number
  daily_tokens_indexed?: number
  daily_vector_count?: number
  active_pairs?: number
  active_pair_tokens?: number
}

export type ProjectInfo = {
  name?: string
  description?: string
  created_at?: string
  system?: boolean
  daily_rag_enabled?: boolean
}
