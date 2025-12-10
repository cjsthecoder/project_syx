/**
 * Copyright (c) 2025 Christopher Shuler. All rights reserved.
 *
 * This source code is part of the Morpheus project and is proprietary.
 *
 * Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.
 *
 * Use of this software requires explicit written permission from the copyright holder.
 */
import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Select } from '@/components/ui/select'
import { Toast } from '@/components/ui/toast'
import { Dialog, DialogHeader, DialogFooter } from '@/components/ui/dialog'

type Message = { id?: number; role: 'user' | 'assistant'; content: string; forget?: boolean; keep?: boolean }
type Project = { id: string; name?: string }
type ModelItem = string

async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export default function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState<string>('')
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [ragBuilding, setRagBuilding] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [model, setModel] = useState('gpt-5.1')
  const [models, setModels] = useState<ModelItem[]>(['gpt-5.1'])

  // V2.1 UI state
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showManageModal, setShowManageModal] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [renameProjectName, setRenameProjectName] = useState('')
  const [files, setFiles] = useState<any[]>([])
  const [stats, setStats] = useState<{ storage_bytes: number; index_size_bytes: number; tokens_indexed: number; context_tokens: number; file_count: number; daily_index_size_bytes?: number; daily_tokens_indexed?: number; daily_vector_count?: number; active_pairs?: number } | null>(null)
  const [projectInfo, setProjectInfo] = useState<{ name?: string; description?: string; created_at?: string; system?: boolean; daily_rag_enabled?: boolean } | null>(null)
  const [showSleepModal, setShowSleepModal] = useState(false)
  const [sleepSince, setSleepSince] = useState<string | null>(null)
  // FR-4.5.1 Dream UI
  const [projectSummary, setProjectSummary] = useState<string | null>(null)
  const [dreamWarning, setDreamWarning] = useState<string | null>(null)
  const [hasDreamItems, setHasDreamItems] = useState(false)
  const [showDreamModal, setShowDreamModal] = useState(false)

  // V2.6 Personality UI state
  const [showPersonalityModal, setShowPersonalityModal] = useState(false)
  const [systemPrompt, setSystemPrompt] = useState('')
  const [tone, setTone] = useState<'analytical'|'friendly'|'creative'|'formal'>('analytical')
  const [verbosity, setVerbosity] = useState<'concise'|'balanced'|'detailed'>('concise')
  const [formatPref, setFormatPref] = useState<'markdown'|'plain'|'html'>('markdown')
  const [creativity, setCreativity] = useState(0.4)
  const [domainFocus, setDomainFocus] = useState('')

  const listRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const loadProjects = useCallback(async () => {
    try {
      const data = await api<{ available_projects?: string[]; current_project?: string; project_names?: Record<string,string> }>('/projects')
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

  const loadModels = useCallback(async () => {
    try {
      const data = await api<{ models: string[] }>('/models')
      if (Array.isArray(data.models) && data.models.length) {
        setModels(data.models)
        if (!data.models.includes(model)) setModel(data.models[0])
      }
    } catch {}
  }, [model])

  const loadFiles = useCallback(async (pid: string) => {
    try {
      const data = await api<{ project_id: string; files: any[]; storage_bytes: number; token_count: number }>(`/projects/${pid}/files`)
      setFiles(data.files || [])
    } catch {
      setFiles([])
    }
  }, [])

  const loadChats = useCallback(async (pid: string) => {
    try {
      const data = await api<{ project_id: string; messages: { id: number; role: 'user'|'assistant'; content: string; created_at: string; forget?: boolean|null; keep?: boolean|null }[] }>(`/projects/${pid}/chats`)
      const msgs: Message[] = (data.messages || []).map(m => ({ id: m.id, role: m.role, content: m.content, forget: !!m.forget, keep: !!m.keep }))
      setMessages(msgs)
    } catch {
      setMessages([])
    }
  }, [])

  const loadStats = useCallback(async (pid: string) => {
    try {
      const data = await api<{ storage_bytes: number; index_size_bytes: number; tokens_indexed: number; context_tokens: number; file_count: number; daily_index_size_bytes?: number; daily_tokens_indexed?: number; daily_vector_count?: number }>(`/projects/${pid}/stats`)
      setStats(data)
    } catch {
      setStats(null)
    }
  }, [])

  const loadProjectInfo = useCallback(async (pid: string) => {
    try {
      const data = await api<{ project: any }>(`/projects/${pid}`)
      setProjectInfo(data.project || {})
    } catch {
      setProjectInfo(null)
    }
  }, [])

  // FR-4.5.1.2: Load dream summary card data
  const loadDreamSummary = useCallback(async (pid: string) => {
    try {
      const data = await api<{ project_id?: string; dream?: any; error?: any }>(`/projects/${pid}/dream`)
      const dream = data?.dream
      const summary = dream?.project_summary
      const items = Array.isArray(dream?.items) ? dream.items : []
      if (typeof summary === 'string' && summary.trim().length > 0) {
        setProjectSummary(summary.trim())
        setHasDreamItems(items.length > 0)
      } else {
        setProjectSummary(null)
        setHasDreamItems(false)
      }
    } catch (e: any) {
      setProjectSummary(null)
      setHasDreamItems(false)
      console.warn('loadDreamSummary failed', e)
    }
  }, [])

  // FR-4.5.1.1: Refresh all project data
  const refreshProjectData = useCallback(async (pid: string) => {
    if (!pid) return
    try {
      await Promise.all([
        loadChats(pid),
        loadFiles(pid),
        loadStats(pid),
        loadProjectInfo(pid),
        loadDreamSummary(pid),
      ])
    } catch (e) {
      // Log but don't block - individual load functions handle their own errors
      console.error('Failed to refresh project data:', e)
    }
  }, [loadChats, loadFiles, loadStats, loadProjectInfo, loadDreamSummary])

  async function checkSleeping(): Promise<boolean> {
    try {
      const r = await fetch('/sleep/status')
      if (!r.ok) return false
      const j = await r.json()
      if (j && j.sleeping) {
        setSleepSince(j.since || null)
        setShowSleepModal(true)
        return true
      }
    } catch {}
    return false
  }

  useEffect(() => {
    loadProjects()
    loadModels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // FR-4.5.1.1: Refresh project data when project changes
  useEffect(() => {
    if (projectId) {
      refreshProjectData(projectId)
      // Preload personality when switching projects
      loadPersonality(projectId)
    } else {
      // Clear state when no project selected
      setMessages([])
      setFiles([])
      setStats(null)
      setProjectInfo(null)
    }
  }, [projectId, refreshProjectData])

  // FR-4.5.1.1: Monitor sleep status and refresh when sleep ends
  useEffect(() => {
    if (!showSleepModal || !projectId) return

    let cancelled = false
    const interval = setInterval(async () => {
      if (cancelled) return
      try {
        const r = await fetch('/sleep/status')
        if (!r.ok) return
        const j = await r.json()

        // Transition detected: was sleeping, now awake
        if (!j?.sleeping) {
          cancelled = true
          clearInterval(interval)
          setShowSleepModal(false)
          setSleepSince(null)
          // Refresh all project data when sleep ends
          await refreshProjectData(projectId)
        }
      } catch {
        // Ignore polling errors, continue checking
      }
    }, 5000) // Poll every 5 seconds while sleep modal is visible

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [showSleepModal, projectId, refreshProjectData])

  const canSend = useMemo(() => input.trim().length > 0 && !loading, [input, loading])

  async function send() {
    if (!canSend) return
    // Clear dream UI so it rolls off when a new chat starts
    setProjectSummary(null)
    setDreamWarning(null)
    setError(null)
    setLoading(true)
    // If sleeping, show modal and bail early
    if (await checkSleeping()) {
      setLoading(false)
      return
    }
    const userMsg: Message = { role: 'user', content: input }
    // Add user only; defer assistant bubble until first token arrives
    setMessages((m) => [...m, userMsg])
    const toSend = input
    setInput('')
    try {
      const res = await fetch('/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_id: projectId, message: toSend, model }),
      })
      if (!res.ok || !res.body) {
        const txt = await res.text().catch(() => '')
        if (res.status === 423 || /sleep/i.test(txt)) {
          await checkSleeping()
          throw new Error('System is sleeping')
        }
        throw new Error(txt || `HTTP ${res.status}`)
      }
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let done = false
      let assistantCreated = false
      while (!done) {
        const { value, done: d } = await reader.read()
        done = d
        if (value) {
          const chunk = decoder.decode(value, { stream: true })
          const text = chunk.replace(/\n::event:\s*done\s*\n?/g, '')
          // Only act on non-whitespace text
          if (text && text.trim().length > 0) {
            setMessages((m) => {
              if (m.length === 0) return m
              // Create assistant bubble on first token
              if (!assistantCreated) {
                assistantCreated = true
                // Hide "Thinking..." once real content starts streaming
                setLoading(false)
                return [...m, { role: 'assistant', content: text }]
              }
              // Append to latest assistant message
              const copy = [...m]
              const idx = copy.length - 1
              if (copy[idx]?.role !== 'assistant') {
                // If somehow last isn't assistant, create one
                return [...copy, { role: 'assistant', content: text }]
              }
              copy[idx] = { ...copy[idx], content: (copy[idx].content || '') + text }
              return copy
            })
          }
        }
      }
      // Refresh stats/chats to sync with DB-persisted assistant entry
      if (projectId) {
        try { await loadStats(projectId) } catch {}
        try { await loadChats(projectId) } catch {}
      }
    } catch (e: any) {
      setError(e?.message || 'Stream failed')
    } finally {
      // If no content ever arrived, clear "Thinking..." now
      setLoading(false)
    }
  }

  function fmtMB(bytes?: number) {
    if (bytes === undefined || bytes === null) return '—'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  async function createProject() {
    if (!newProjectName.trim()) return
    try {
      await api('/projects', { method: 'POST', body: JSON.stringify({ project_name: newProjectName.trim() }) })
      await loadProjects()
      setNewProjectName('')
      setShowCreateModal(false)
    } catch (e: any) {
      setError(e?.message || 'Create project failed')
    }
  }

  async function renameProject() {
    if (!renameProjectName.trim() || !projectId) return
    try {
      await api(`/projects/${projectId}`, { method: 'PATCH', body: JSON.stringify({ project_name: renameProjectName.trim() }) })
      setRenameProjectName('')
      await loadProjects()
      await loadProjectInfo(projectId)
    } catch (e: any) {
      setError(e?.message || 'Rename failed')
    }
  }

  async function deleteProject() {
    if (!projectId) return
    try {
      await api(`/projects/${projectId}`, { method: 'DELETE' })
      await loadProjects()
      setShowManageModal(false)
    } catch (e: any) {
      setError(e?.message || 'Delete failed')
    }
  }

  async function uploadFiles(selected: FileList) {
    if (!projectId || !selected || selected.length === 0) return
    const form = new FormData()
    Array.from(selected).forEach((f) => form.append('files', f))
    try {
      await fetch(`/projects/${projectId}/files`, { method: 'POST', body: form })
      await loadFiles(projectId)
      await loadStats(projectId)
    } catch (e: any) {
      setError(e?.message || 'Upload failed')
    }
  }

  async function deleteFile(fileId: number) {
    if (!projectId) return
    try {
      await api(`/projects/${projectId}/files/${fileId}`, { method: 'DELETE' })
      await loadFiles(projectId)
      await loadStats(projectId)
    } catch (e: any) {
      setError(e?.message || 'Delete failed')
    }
  }

  // V2.6: Personality endpoints
  async function loadPersonality(pid: string) {
    try {
      const data = await api<{ project_id: string; personality: any; system_prompt: string }>(`/projects/${pid}/personality`)
      const p = data.personality || {}
      setSystemPrompt(data.system_prompt || '')
      setTone((p.tone || 'analytical').toLowerCase())
      setVerbosity((p.verbosity || 'concise').toLowerCase())
      setFormatPref((p.format || 'markdown').toLowerCase())
      setCreativity(parseFloat(p.creativity ?? 0.4) || 0.4)
      setDomainFocus(Array.isArray(p.domain_focus) ? p.domain_focus.join(', ') : '')
    } catch (e: any) {
      setError(e?.message || 'Failed to load personality')
    }
  }

  async function savePersonality() {
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
      setShowPersonalityModal(false)
      // Return to Manage Project modal after saving
      if (projectId) {
        try { await loadProjectInfo(projectId) } catch {}
      }
      setTimeout(() => setShowManageModal(true), 0)
    } catch (e: any) {
      setError(e?.message || 'Failed to save personality')
    }
  }

  // Drag-and-drop handlers
  const [dragOver, setDragOver] = useState(false)
  const onDrop: React.DragEventHandler<HTMLDivElement> = async (e) => {
    e.preventDefault()
    setDragOver(false)
    if (e.dataTransfer?.files?.length) {
      await uploadFiles(e.dataTransfer.files)
    }
  }

  return (
    <div className="h-full flex flex-col">
      <header className="border-b py-2 grid grid-cols-3 items-center">
        {/* Left: Project selector and actions, inset 15% from left */}
        <div className="flex items-center gap-2 justify-start ml-[15%]">
          <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name ?? p.id}
              </option>
            ))}
          </Select>
          <Button
            className="bg-white !text-black hover:bg-gray-100 border-transparent dark:!bg-black dark:!text-white dark:hover:!bg-gray-900"
            onClick={() => setShowCreateModal(true)}
          >
            New
          </Button>
          <Button
            className="bg-white !text-black hover:bg-gray-100 border-transparent dark:!bg-black dark:!text-white dark:hover:!bg-gray-900"
            onClick={() => setShowManageModal(true)}
          >
            Manage
          </Button>
        </div>

        {/* Center: Title */}
        <div className="flex justify-center">
          <h1 className="text-2xl font-bold">Morpheus</h1>
        </div>

        {/* Right: Model selector, inset 15% from right */}
        <div className="flex items-center gap-3 justify-end mr-[15%] text-sm text-gray-700 dark:text-gray-300">
          <label className="text-sm">Model:</label>
          <Select value={model} onChange={(e) => setModel(e.target.value)}>
            {models.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </Select>
        </div>
      </header>

      {/* Stats Bar */}
      <div className="px-4 py-2 border-b text-sm w-full flex justify-center">
        <div className="flex flex-wrap gap-8 items-center text-center">
          <div>Files: {fmtMB(stats?.storage_bytes)}</div>
          <div>FAISS index: {fmtMB(stats?.index_size_bytes)}</div>
          <div>Tokens indexed: {stats?.tokens_indexed ?? '—'}</div>
          <div>Context tokens: {stats?.context_tokens ?? '—'}</div>
          <div>Daily index: {fmtMB(stats?.daily_index_size_bytes)}</div>
          <div>Daily tokens: {stats?.daily_tokens_indexed ?? '—'}</div>
          <div>Active pairs: {stats?.active_pairs ?? '—'}</div>
        </div>
      </div>

      <main className="flex-1 overflow-hidden">
        <div ref={listRef} className="h-full overflow-auto p-4 space-y-3">
          {projectSummary && (
            <div
              className="ml-[20%] mr-[20%] mb-3 rounded px-3 py-3 text-sm"
              style={{ backgroundColor: '#66b5ff', color: '#000' }}
            >
              <div className="font-semibold mb-1">Project Summary</div>
              <div className="whitespace-pre-wrap break-words">{projectSummary}</div>
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={m.role === 'user' ? 'text-right' : 'text-left'}>
              <div
                className={`inline-block rounded px-3 py-2 whitespace-pre-wrap break-words max-w-[800px] w-fit text-left ${
                  m.role === 'user'
                    ? 'mr-[20%] bg-gray-200 text-black'
                    : 'ml-[20%] text-white'
                }`}
                style={m.role === 'assistant' ? { backgroundColor: '#202123' } : undefined}
              >
                {m.content}
              </div>
              {m.role === 'assistant' && m.id != null && (
                <div className="ml-[20%] mt-1 flex items-center gap-4 text-xs text-gray-600 dark:text-gray-400">
                  <label className="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={!!m.forget}
                      onChange={async (e) => {
                        if (!projectId || m.id == null) return
                        const next = e.target.checked
                        try {
                          await api(`/projects/${projectId}/chats/${m.id}`, { method: 'PATCH', body: JSON.stringify({ forget: next }) })
                          setMessages((list) => list.map((mm, idx) => idx === i ? { ...mm, forget: next } : mm))
                        } catch (err: any) {
                          setError(err?.message || 'Failed to update forget flag')
                        }
                      }}
                    />
                    <span>Forget</span>
                  </label>
                  <label className="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={!!(m as any).keep}
                      onChange={async (e) => {
                        if (!projectId || m.id == null) return
                        const next = e.target.checked
                        try {
                          await api(`/projects/${projectId}/chats/${m.id}`, { method: 'PATCH', body: JSON.stringify({ keep: next }) })
                          setMessages((list) => list.map((mm, idx) => idx === i ? { ...mm, keep: next } : mm))
                        } catch (err: any) {
                          setError(err?.message || 'Failed to update keep flag')
                        }
                      }}
                    />
                    <span>Keep</span>
                  </label>
                </div>
              )}
            </div>
          ))}
          {ragBuilding && !loading && <div className="text-sm text-gray-500">Building RAG Query…</div>}
          {loading && <div className="text-sm text-gray-500">Thinking…</div>}
        </div>
      </main>

      {error && (
        <Toast message={error} onRetry={send} onClose={() => setError(null)} />
      )}

      {/* Centered Analyze Dreams button above the prompt box */}
      {hasDreamItems && (
        <div className="w-full flex justify-center pb-2">
          <Button
            className="bg-white !text-black hover:bg-gray-100 border border-gray-200"
            onClick={() => setShowDreamModal(true)}
          >
            Analyze Dreams
          </Button>
        </div>
      )}

      <footer className="border-t p-6">
        <div className="w-3/5 mx-auto">
          <form
            onSubmit={(e) => {
              e.preventDefault()
              send()
            }}
          >
            <Textarea
              className="w-full min-h-[96px] max-h-64 resize-y text-left"
              placeholder="Type your message..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
            />
            <div className="mt-3 flex justify-center">
              <Button type="submit" disabled={!canSend}>
                Send
              </Button>
            </div>
          </form>
        </div>
      </footer>

      {/* System Sleeping Modal */}
      <Dialog open={showSleepModal} onClose={() => setShowSleepModal(false)}>
        <DialogHeader>System Sleeping</DialogHeader>
        <div className="px-4 pb-2 text-sm">
          The system is currently running its sleep cycle. Please try again after it finishes.
          {sleepSince && <div className="mt-2 text-gray-600">Sleeping since: {sleepSince}</div>}
        </div>
        <DialogFooter>
          <Button onClick={() => setShowSleepModal(false)}>OK</Button>
        </DialogFooter>
      </Dialog>

      {/* Dream Analysis Modal (placeholder for FR-4.5.1.3) */}
      <Dialog
        open={showDreamModal}
        onClose={() => setShowDreamModal(false)}
        contentClassName="max-w-8xl w-[1280px] max-h-[90vh] h-[85vh] overflow-hidden flex flex-col"
      >
        <DialogHeader>Analyze Dreams</DialogHeader>
        <div className="px-4 pb-2 text-sm flex-1 overflow-auto">
          {projectSummary ? (
            <div className="whitespace-pre-wrap break-words">{projectSummary}</div>
          ) : (
            <div>No dream summary available.</div>
          )}
        </div>
        <DialogFooter>
          <Button onClick={() => setShowDreamModal(false)}>Close</Button>
          <Button disabled>Submit (coming soon)</Button>
        </DialogFooter>
      </Dialog>

      {/* Create Project Modal */}
      <Dialog open={showCreateModal} onClose={() => setShowCreateModal(false)}>
        <DialogHeader>New Project</DialogHeader>
        <div className="space-y-3 px-4 pb-2">
          <input className="border rounded px-2 py-1 w-full" placeholder="Project name" value={newProjectName} onChange={(e) => setNewProjectName(e.target.value)} />
        </div>
        <DialogFooter>
          <Button onClick={() => setShowCreateModal(false)}>Cancel</Button>
          <Button onClick={createProject}>Create</Button>
        </DialogFooter>
      </Dialog>

      {/* Personality Modal (V2.6) */}
      <Dialog open={showPersonalityModal} onClose={() => setShowPersonalityModal(false)}>
        <DialogHeader>Project Personality</DialogHeader>
        <div className="space-y-4 px-4 pb-2">
          <div>
            <label className="block text-sm mb-1">System Prompt</label>
            <Textarea className="w-full min-h-[700px]" value={systemPrompt} onChange={(e) => setSystemPrompt(e.target.value)} />
          </div>
          <div className="grid grid-cols-3 gap-3 items-end">
            <div>
              <label className="block text-sm mb-1">Tone</label>
              <Select value={tone} onChange={(e) => setTone(e.target.value as any)}>
                {['analytical','friendly','creative','formal'].map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </Select>
            </div>
            <div>
              <label className="block text-sm mb-1">Verbosity</label>
              <Select value={verbosity} onChange={(e) => setVerbosity(e.target.value as any)}>
                {['concise','balanced','detailed'].map((v) => (
                  <option key={v} value={v}>{v}</option>
                ))}
              </Select>
            </div>
            <div>
              <label className="block text-sm mb-1">Format</label>
              <Select value={formatPref} onChange={(e) => setFormatPref(e.target.value as any)}>
                {['markdown','plain','html'].map((f) => (
                  <option key={f} value={f}>{f}</option>
                ))}
              </Select>
            </div>
          </div>
          <div>
            <label className="block text-sm mb-1">Creativity ({creativity.toFixed(2)})</label>
            <input type="range" min={0} max={1} step={0.01} value={creativity} onChange={(e) => setCreativity(parseFloat(e.target.value))} className="w-full" />
          </div>
          <div>
            <label className="block text-sm mb-1">Domain Focus (comma-separated)</label>
            <input className="border rounded px-2 py-1 w-full" value={domainFocus} onChange={(e) => setDomainFocus(e.target.value)} placeholder="AI, neuroscience" />
          </div>
        </div>
        <DialogFooter>
          <Button onClick={() => setShowPersonalityModal(false)}>Cancel</Button>
          <Button onClick={savePersonality}>Save</Button>
        </DialogFooter>
      </Dialog>

      {/* Manage Project Modal */}
      <Dialog open={showManageModal} onClose={() => { setShowManageModal(false); if (projectId) loadStats(projectId) }}>
        <DialogHeader>Manage Project</DialogHeader>
        <div className="space-y-4 px-4 pb-2">
          <div className="text-sm text-gray-700 dark:text-gray-300">
            <div><strong>Name:</strong> {projectInfo?.name ?? projectId}</div>
            {projectInfo?.created_at && <div><strong>Created:</strong> {new Date(projectInfo.created_at).toLocaleString()}</div>}
            {projectInfo?.system && <div className="text-amber-600">System project</div>}
          </div>

          {/* V2.6: Personality manager entry point */}
          <div className="flex items-center justify-start">
            <Button
              className="bg-black !text-white hover:bg-gray-900 border-transparent dark:!bg-black dark:!text-white dark:hover:!bg-gray-900"
              onClick={async () => {
                if (projectId) {
                  await loadPersonality(projectId)
                }
                setShowManageModal(false)
                setTimeout(() => setShowPersonalityModal(true), 0)
              }}
            >
              Personality
            </Button>
          </div>

          {!projectInfo?.system && (
            <div className="flex items-center gap-2">
              <label className="text-sm">Keep Daily History</label>
              <input
                type="checkbox"
                checked={!!projectInfo?.daily_rag_enabled}
                onChange={async (e) => {
                  if (!projectId) return
                  try {
                    await api(`/projects/${projectId}`, { method: 'PATCH', body: JSON.stringify({ daily_rag_enabled: e.target.checked }) })
                    await loadProjectInfo(projectId)
                    await loadStats(projectId)
                  } catch (err: any) {
                    setError(err?.message || 'Failed to update setting')
                  }
                }}
              />
            </div>
          )}

          <div className="flex items-center gap-2">
            <input className="border rounded px-2 py-1 flex-1" placeholder="Rename to…" value={renameProjectName} onChange={(e) => setRenameProjectName(e.target.value)} />
            <Button onClick={renameProject} disabled={!!projectInfo?.system}>Rename</Button>
          </div>

          <div
            className={`border-2 ${dragOver ? 'border-blue-500' : 'border-dashed border-gray-300'} rounded p-4 text-center`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
            onDragLeave={() => setDragOver(false)}
            onDrop={onDrop}
          >
            Drag & drop files here, or
            <label className="ml-2 underline cursor-pointer">
              choose files<input type="file" multiple className="hidden" onChange={(e) => e.target.files && uploadFiles(e.target.files)} />
            </label>
          </div>

          <div>
            <div className="font-semibold mb-2">Files</div>
            <ul className="space-y-2 max-h-64 overflow-auto">
              {files.map((f: any) => (
                <li key={f.id} className="flex items-center justify-between text-sm">
                  <div className="truncate mr-3">{f.filename}</div>
                  <div className="flex items-center gap-3">
                    <span className="text-gray-500">{(f.size_bytes / (1024*1024)).toFixed(1)} MB</span>
                    <Button onClick={() => deleteFile(f.id)}>Delete</Button>
                  </div>
                </li>
              ))}
              {files.length === 0 && <li className="text-gray-500 text-sm">No files uploaded</li>}
            </ul>
          </div>

          {!projectInfo?.system && (
            <div className="flex items-center justify-end">
              <Button onClick={deleteProject}>Delete Project</Button>
            </div>
          )}
        </div>
        <DialogFooter>
          <Button onClick={() => { setShowManageModal(false); if (projectId) loadStats(projectId) }}>Close</Button>
        </DialogFooter>
      </Dialog>
    </div>
  )
}


