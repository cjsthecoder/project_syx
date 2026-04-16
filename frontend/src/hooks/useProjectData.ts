import { useCallback, useEffect, useState } from 'react'
import { api } from '@/pages/app/api'
import { toDreamViewState } from '@/pages/app/dream'
import { extractErrorMessage, readJsonSafe, throwRequestError } from '@/pages/app/request'
import { DreamItem, Project, ProjectInfo, ProjectStats } from '@/pages/app/types'

type UseProjectDataArgs = {
  showDebugValues: boolean
  onError: (message: string) => void
}

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

  const [dragOver, setDragOver] = useState(false)

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

  const loadFiles = useCallback(async (pid: string) => {
    try {
      const data = await api<{ project_id: string; files: any[] }>(`/projects/${pid}/files`)
      setFiles(data.files || [])
    } catch {
      setFiles([])
    }
  }, [])

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

  const loadProjectInfo = useCallback(async (pid: string) => {
    try {
      const data = await api<{ project: ProjectInfo }>(`/projects/${pid}`)
      setProjectInfo(data.project || {})
    } catch {
      setProjectInfo(null)
    }
  }, [])

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

  const refreshProjectData = useCallback(
    async (pid: string, loadChats: (projectId: string) => Promise<void>) => {
      if (!pid) return
      try {
        await Promise.all([loadChats(pid), loadFiles(pid), loadStats(pid), loadProjectInfo(pid), loadDreamSummary(pid)])
      } catch (e) {
        console.error('Failed to refresh project data:', e)
      }
    },
    [loadDreamSummary, loadFiles, loadProjectInfo, loadStats],
  )

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

  const deleteProject = useCallback(async () => {
    if (!projectId) return
    try {
      await api(`/projects/${projectId}`, { method: 'DELETE' })
      await loadProjects()
    } catch (e: unknown) {
      onError(e instanceof Error ? e.message : 'Delete failed')
    }
  }, [loadProjects, onError, projectId])

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

  const loadPersonality = useCallback(
    async (pid: string) => {
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
      }
    },
    [onError],
  )

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
    saveDreamItems,
  }
}
