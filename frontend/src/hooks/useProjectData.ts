/**
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * React hook centralizing all project-scoped data and actions.
 *
 * Loads and manages projects, files, stats, project info, dream summaries,
 * personality settings, and the user profile, and exposes CRUD operations for
 * projects, file uploads, personality/profile saves, dream-item persistence,
 * and sleep-status checks.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '@/pages/app/api'
import { toDreamViewState } from '@/pages/app/dream'
import { extractErrorMessage, readJsonSafe, throwRequestError } from '@/pages/app/request'
import { DreamItem, Project, ProjectInfo, ProjectStats } from '@/pages/app/types'

type UseProjectDataArgs = {
  showDebugValues: boolean
  onError: (message: string) => void
}

/**
 * Centralize project-scoped data and actions for the chat app.
 *
 * Loads projects, files, stats, info, dream summaries, personality, and the user
 * profile, and returns loaders plus CRUD/mutation actions. Mutations surface
 * failures via `onError`; loaders fail soft to empty state.
 *
 * @param args - Hook configuration.
 * @param args.showDebugValues - When false, stats are not fetched and remain null.
 * @param args.onError - Callback invoked with a message when a mutation fails.
 * @returns Project state plus loader and CRUD/mutation actions (see the returned object).
 */
export function useProjectData({ showDebugValues, onError }: UseProjectDataArgs) {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState<string>('')
  const [files, setFiles] = useState<any[]>([])
  const [stats, setStats] = useState<ProjectStats | null>(null)
  const [projectInfo, setProjectInfo] = useState<ProjectInfo | null>(null)
  const [showSleepModal, setShowSleepModal] = useState(false)
  const [sleepSince, setSleepSince] = useState<string | null>(null)

  const [projectSummary, setProjectSummary] = useState<string | null>(null)
  const [hasDreamItems, setHasDreamItems] = useState(false)
  const [dreamItems, setDreamItems] = useState<DreamItem[]>([])
  const [savingDream, setSavingDream] = useState(false)

  const [systemPrompt, setSystemPrompt] = useState('')
  const [tone, setTone] = useState<'analytical' | 'friendly' | 'creative' | 'formal'>('analytical')
  const [verbosity, setVerbosity] = useState<'concise' | 'balanced' | 'detailed'>('concise')
  const [formatPref, setFormatPref] = useState<'markdown' | 'plain' | 'html'>('markdown')
  const [creativity, setCreativity] = useState(0.4)
  const [domainFocus, setDomainFocus] = useState('')

  const [userProfile, setUserProfile] = useState('')
  const [savingUserProfile, setSavingUserProfile] = useState(false)

  const [dragOver, setDragOver] = useState(false)
  const refreshInFlightRef = useRef<Set<string>>(new Set())
  const personalityInFlightRef = useRef<Set<string>>(new Set())

  /** Load the project list and select the current project; clears the list on failure. */
  const loadProjects = useCallback(async () => {
    try {
      const data = await api<{ available_projects?: string[]; current_project?: string; project_names?: Record<string, string> }>('/projects')
      const ids = (data.available_projects ?? []).filter((id) => id !== 'default')
      const namesMap = data.project_names || {}
      const list = ids.map((id) => ({ id, name: namesMap[id] || id }))
      setProjects(list)
      const current = data.current_project ?? list[0]?.id
      if (current) setProjectId(current)
    } catch {
      setProjects([])
    }
  }, [])

  /**
   * Load the file list for a project; clears it on failure.
   *
   * @param pid - Project id whose files to load.
   */
  const loadFiles = useCallback(async (pid: string) => {
    try {
      const data = await api<{ project_id: string; files: any[] }>(`/projects/${pid}/files`)
      setFiles(data.files || [])
    } catch {
      setFiles([])
    }
  }, [])

  /**
   * Load project stats when debug values are enabled; otherwise clears stats.
   *
   * @param pid - Project id whose stats to load.
   */
  const loadStats = useCallback(
    async (pid: string) => {
      if (!showDebugValues) {
        setStats(null)
        return
      }
      try {
        const data = await api<ProjectStats>(`/projects/${pid}/stats`)
        setStats(data)
      } catch {
        setStats(null)
      }
    },
    [showDebugValues],
  )

  /**
   * Load project metadata; clears it on failure.
   *
   * @param pid - Project id whose info to load.
   */
  const loadProjectInfo = useCallback(async (pid: string) => {
    try {
      const data = await api<{ project: ProjectInfo }>(`/projects/${pid}`)
      setProjectInfo(data.project || {})
    } catch {
      setProjectInfo(null)
    }
  }, [])

  /**
   * Load and normalize the project's dream summary and items; clears them on failure.
   *
   * @param pid - Project id whose dream data to load.
   */
  const loadDreamSummary = useCallback(async (pid: string) => {
    try {
      const data = await api<{ dream?: unknown }>(`/projects/${pid}/dream`)
      const state = toDreamViewState(data?.dream)
      setProjectSummary(state.projectSummary)
      setHasDreamItems(state.hasDreamItems)
      setDreamItems(state.dreamItems)
    } catch (e) {
      setProjectSummary(null)
      setHasDreamItems(false)
      setDreamItems([])
      console.warn('loadDreamSummary failed', e)
    }
  }, [])

  /**
   * Load chats, files, stats, info, and dream summary for a project in parallel.
   *
   * Deduplicates concurrent refreshes for the same project via an in-flight set.
   *
   * @param pid - Project id to refresh.
   * @param loadChats - Chat-history loader (injected from the chat-stream hook).
   */
  const refreshProjectData = useCallback(
    async (pid: string, loadChats: (projectId: string) => Promise<void>) => {
      if (!pid) return
      if (refreshInFlightRef.current.has(pid)) {
        return
      }
      refreshInFlightRef.current.add(pid)
      try {
        await Promise.all([loadChats(pid), loadFiles(pid), loadStats(pid), loadProjectInfo(pid), loadDreamSummary(pid)])
      } catch (e) {
        console.error('Failed to refresh project data:', e)
      } finally {
        refreshInFlightRef.current.delete(pid)
      }
    },
    [loadDreamSummary, loadFiles, loadProjectInfo, loadStats],
  )

  /**
   * Query sleep status; if sleeping, record the start time and open the sleep dialog.
   *
   * @returns True when the system is currently sleeping, false otherwise (including on error).
   */
  const checkSleeping = useCallback(async (): Promise<boolean> => {
    try {
      const r = await fetch('/sleep/status')
      if (!r.ok) return false
      const j = await r.json()
      if (j && j.sleeping) {
        setSleepSince(j.since || null)
        setShowSleepModal(true)
        return true
      }
    } catch (e) {
      console.info('checkSleeping status request failed', e)
    }
    return false
  }, [])

  /**
   * Create a project from a non-empty name, then reload the project list.
   *
   * @param name - Desired project name; no-op when blank.
   */
  const createProject = useCallback(
    async (name: string) => {
      if (!name.trim()) return
      try {
        await api('/projects', { method: 'POST', body: JSON.stringify({ project_name: name.trim() }) })
        await loadProjects()
      } catch (e: unknown) {
        onError(e instanceof Error ? e.message : 'Create project failed')
      }
    },
    [loadProjects, onError],
  )

  /**
   * Rename the current project, then refresh the project list and info.
   *
   * @param name - New project name; no-op when blank or when no project is active.
   */
  const renameProject = useCallback(
    async (name: string) => {
      if (!name.trim() || !projectId) return
      try {
        await api(`/projects/${projectId}`, { method: 'PATCH', body: JSON.stringify({ project_name: name.trim() }) })
        await loadProjects()
        await loadProjectInfo(projectId)
      } catch (e: unknown) {
        onError(e instanceof Error ? e.message : 'Rename failed')
      }
    },
    [loadProjectInfo, loadProjects, onError, projectId],
  )

  /** Delete the current project, then reload the project list. */
  const deleteProject = useCallback(async () => {
    if (!projectId) return
    try {
      await api(`/projects/${projectId}`, { method: 'DELETE' })
      await loadProjects()
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : 'Delete failed')
    }
  }, [loadProjects, onError, projectId])

  /**
   * Upload selected files to the current project as multipart form data, then
   * refresh the file list and stats. The backend rebuilds the RAG index.
   *
   * @param selected - Files chosen via picker or drag-and-drop; no-op when empty or no active project.
   */
  const uploadFiles = useCallback(
    async (selected: FileList) => {
      if (!projectId || !selected || selected.length === 0) return
      const form = new FormData()
      Array.from(selected).forEach((f) => form.append('files', f))
      try {
        const res = await fetch(`/projects/${projectId}/files`, { method: 'POST', body: form })
        if (!res.ok) await throwRequestError(res)
        await loadFiles(projectId)
        await loadStats(projectId)
      } catch (e: unknown) {
        onError(e instanceof Error ? e.message : 'Upload failed')
      }
    },
    [loadFiles, loadStats, onError, projectId],
  )

  /**
   * Delete a file from the current project, then refresh the file list and stats.
   *
   * @param fileId - Database id of the file to delete.
   */
  const deleteFile = useCallback(
    async (fileId: number) => {
      if (!projectId) return
      try {
        await api(`/projects/${projectId}/files/${fileId}`, { method: 'DELETE' })
        await loadFiles(projectId)
        await loadStats(projectId)
      } catch (e: unknown) {
        onError(e instanceof Error ? e.message : 'Delete failed')
      }
    },
    [loadFiles, loadStats, onError, projectId],
  )

  /**
   * Load a project's system prompt and personality settings into hook state.
   *
   * Deduplicates concurrent loads for the same project via an in-flight set.
   *
   * @param pid - Project id whose personality to load.
   */
  const loadPersonality = useCallback(
    async (pid: string) => {
      if (!pid) return
      if (personalityInFlightRef.current.has(pid)) {
        return
      }
      personalityInFlightRef.current.add(pid)
      try {
        const data = await api<{ project_id: string; personality: any; system_prompt: string }>(`/projects/${pid}/personality`)
        const p = data.personality || {}
        setSystemPrompt(data.system_prompt || '')
        setTone((p.tone || 'analytical').toLowerCase())
        setVerbosity((p.verbosity || 'concise').toLowerCase())
        setFormatPref((p.format || 'markdown').toLowerCase())
        setCreativity(parseFloat(p.creativity ?? 0.4) || 0.4)
        setDomainFocus(Array.isArray(p.domain_focus) ? p.domain_focus.join(', ') : '')
      } catch (e: unknown) {
        onError(e instanceof Error ? e.message : 'Failed to load personality')
      } finally {
        personalityInFlightRef.current.delete(pid)
      }
    },
    [onError],
  )

  /** Persist the system prompt and personality settings, then refresh project info. */
  const savePersonality = useCallback(async () => {
    if (!projectId) return
    try {
      await api(`/projects/${projectId}/system_prompt`, { method: 'PUT', body: JSON.stringify({ content: systemPrompt }) })
      const payload = {
        tone,
        verbosity,
        format: formatPref,
        creativity,
        domain_focus: domainFocus.split(',').map((s) => s.trim()).filter(Boolean),
      }
      await api(`/projects/${projectId}/personality`, { method: 'PATCH', body: JSON.stringify(payload) })
      try {
        await loadProjectInfo(projectId)
      } catch (e) {
        console.info('post-save project info refresh failed', e)
      }
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : 'Failed to save personality')
    }
  }, [creativity, domainFocus, formatPref, loadProjectInfo, onError, projectId, systemPrompt, tone, verbosity])

  /**
   * Load the project's USER_PROFILE.txt content into hook state; clears it on failure.
   *
   * @param pid - Project id whose profile to load.
   */
  const loadUserProfile = useCallback(
    async (pid: string) => {
      if (!pid) return
      try {
        const data = await api<{ project_id: string; content: string; exists: boolean }>(`/projects/${pid}/user_profile`)
        setUserProfile(data.content || '')
      } catch (e: unknown) {
        onError(e instanceof Error ? e.message : 'Failed to load user profile')
        setUserProfile('')
      }
    },
    [onError],
  )

  /**
   * Persist the edited USER_PROFILE.txt for the current project, then refresh
   * stats. The backend rewrites the file and rebuilds the RAG index.
   */
  const saveUserProfile = useCallback(async () => {
    if (!projectId) return
    setSavingUserProfile(true)
    try {
      await api(`/projects/${projectId}/user_profile`, { method: 'PUT', body: JSON.stringify({ content: userProfile }) })
      try {
        await loadStats(projectId)
      } catch (e) {
        console.info('post-save stats refresh failed', e)
      }
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : 'Failed to save user profile')
    } finally {
      setSavingUserProfile(false)
    }
  }, [loadStats, onError, projectId, userProfile])

  /** Persist per-item keep/remember review decisions for the project's dream items. */
  const saveDreamItems = useCallback(async () => {
    if (!projectId || dreamItems.length === 0) return
    setSavingDream(true)
    try {
      const payload = {
        items: dreamItems.map((k) => ({
          id: k.id,
          origin_text: k.origin_text,
          assistant_response: k.assistant_response,
          origin_type: k.origin_type,
          source_resolution: k.source_resolution,
          research: k.research,
          keep: !!k.keep,
          remember: !!k.remember,
        })),
      }
      const res = await fetch(`/projects/${projectId}/dream/keep`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) await throwRequestError(res)
      const data = (await readJsonSafe<{ failed?: number; errors?: string[] }>(res)) || {}
      if (data?.failed && data.failed > 0) {
        const msg = Array.isArray(data?.errors)
          ? data.errors.join('; ')
          : extractErrorMessage(data, 'One or more dream items failed')
        throw new Error(msg)
      }
      setHasDreamItems(false)
      setDreamItems([])
      window.alert('Dream items saved')
      return true
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : 'Failed to save dream items')
      return false
    } finally {
      setSavingDream(false)
    }
  }, [dreamItems, onError, projectId])

  useEffect(() => {
    loadProjects()
  }, [loadProjects])

  return {
    projects,
    projectId,
    setProjectId,
    files,
    stats,
    projectInfo,
    showSleepModal,
    setShowSleepModal,
    sleepSince,
    setSleepSince,
    projectSummary,
    setProjectSummary,
    hasDreamItems,
    setHasDreamItems,
    dreamItems,
    setDreamItems,
    savingDream,

    dragOver,
    setDragOver,

    systemPrompt,
    setSystemPrompt,
    tone,
    setTone,
    verbosity,
    setVerbosity,
    formatPref,
    setFormatPref,
    creativity,
    setCreativity,
    domainFocus,
    setDomainFocus,

    loadProjects,
    loadFiles,
    loadStats,
    loadProjectInfo,
    loadDreamSummary,
    refreshProjectData,
    checkSleeping,
    createProject,
    renameProject,
    deleteProject,
    uploadFiles,
    deleteFile,
    loadPersonality,
    savePersonality,
    userProfile,
    setUserProfile,
    savingUserProfile,
    loadUserProfile,
    saveUserProfile,
    saveDreamItems,
  }
}
