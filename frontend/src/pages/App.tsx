import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Select } from '@/components/ui/select'
import { Toast } from '@/components/ui/toast'
import { Dialog, DialogHeader, DialogFooter } from '@/components/ui/dialog'

type Message = { role: 'user' | 'assistant'; content: string }
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
  const [model, setModel] = useState('gpt-5')
  const [models, setModels] = useState<ModelItem[]>(['gpt-5'])

  // V2.1 UI state
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showManageModal, setShowManageModal] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [renameProjectName, setRenameProjectName] = useState('')
  const [files, setFiles] = useState<any[]>([])
  const [stats, setStats] = useState<{ storage_bytes: number; index_size_bytes: number; tokens_indexed: number; context_tokens: number; file_count: number; daily_index_size_bytes?: number; daily_tokens_indexed?: number; daily_vector_count?: number; active_pairs?: number } | null>(null)
  const [projectInfo, setProjectInfo] = useState<{ name?: string; description?: string; created_at?: string; system?: boolean; daily_rag_enabled?: boolean } | null>(null)

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
      const data = await api<{ project_id: string; messages: { id: number; role: 'user'|'assistant'; content: string; created_at: string }[] }>(`/projects/${pid}/chats`)
      const msgs: Message[] = (data.messages || []).map(m => ({ role: m.role, content: m.content }))
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

  useEffect(() => {
    loadProjects()
    loadModels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (projectId) {
      loadChats(projectId)
      loadFiles(projectId)
      loadStats(projectId)
      loadProjectInfo(projectId)
      // Preload personality when switching projects
      loadPersonality(projectId)
    }
  }, [projectId, loadChats, loadFiles, loadStats, loadProjectInfo])

  const canSend = useMemo(() => input.trim().length > 0 && !loading, [input, loading])

  async function send() {
    if (!canSend) return
    setError(null)
    // Indicate RAG builder phase immediately; switch to Thinking… on next tick
    setRagBuilding(true)
    setTimeout(() => setLoading(true), 0)
    const userMsg: Message = { role: 'user', content: input }
    setMessages((m) => [...m, userMsg])
    setInput('')
    try {
      const res = await api<{ response: string; llm_model: string }>('/chat', {
        method: 'POST',
        body: JSON.stringify({ message: userMsg.content, project_id: projectId, model }),
      })
      setModel(res.llm_model)
      setMessages((m) => [...m, { role: 'assistant', content: res.response }])
      if (projectId) {
        loadStats(projectId)
        loadChats(projectId)
      }
    } catch (e: any) {
      setError(e?.message || 'Request failed')
    } finally {
      setRagBuilding(false)
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
          {messages.map((m, i) => (
            <div key={i} className={m.role === 'user' ? 'text-right' : 'text-left'}>
              <div
                className={`inline-block rounded px-3 py-2 whitespace-pre-wrap break-words max-w-[800px] w-fit ${
                  m.role === 'user'
                    ? 'mr-[20%] bg-gray-200 text-black'
                    : 'ml-[20%] text-white'
                }`}
                style={m.role === 'assistant' ? { backgroundColor: '#202123' } : undefined}
              >
                {m.content}
              </div>
            </div>
          ))}
          {ragBuilding && !loading && <div className="text-sm text-gray-500">Building RAG Query…</div>}
          {loading && <div className="text-sm text-gray-500">Thinking…</div>}
        </div>
      </main>

      {error && (
        <Toast message={error} onRetry={send} onClose={() => setError(null)} />
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
              className="w-full min-h-[96px] max-h-64 resize-y"
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


