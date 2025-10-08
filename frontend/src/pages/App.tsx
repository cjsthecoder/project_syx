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
  const [error, setError] = useState<string | null>(null)
  const [model, setModel] = useState('gpt-5')
  const [models, setModels] = useState<ModelItem[]>(['gpt-5'])

  // V2.1 UI state
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showManageModal, setShowManageModal] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [renameProjectName, setRenameProjectName] = useState('')
  const [files, setFiles] = useState<any[]>([])
  const [stats, setStats] = useState<{ storage_bytes: number; index_size_bytes: number; tokens_indexed: number; context_tokens: number; file_count: number } | null>(null)
  const [projectInfo, setProjectInfo] = useState<{ name?: string; description?: string; created_at?: string; system?: boolean } | null>(null)

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

  const loadStats = useCallback(async (pid: string) => {
    try {
      const data = await api<{ storage_bytes: number; index_size_bytes: number; tokens_indexed: number; context_tokens: number; file_count: number }>(`/projects/${pid}/stats`)
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
      loadFiles(projectId)
      loadStats(projectId)
      loadProjectInfo(projectId)
    }
  }, [projectId, loadFiles, loadStats, loadProjectInfo])

  const canSend = useMemo(() => input.trim().length > 0 && !loading, [input, loading])

  async function send() {
    if (!canSend) return
    setError(null)
    setLoading(true)
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
      if (projectId) loadStats(projectId)
    } catch (e: any) {
      setError(e?.message || 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  function fmtMB(bytes?: number) {
    if (!bytes && bytes !== 0) return '—'
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
          <Button onClick={() => setShowCreateModal(true)}>New</Button>
          <Button onClick={() => setShowManageModal(true)}>Manage</Button>
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
          <div>📁 Files: {fmtMB(stats?.storage_bytes)}</div>
          <div>🧠 FAISS index: {fmtMB(stats?.index_size_bytes)}</div>
          <div>🔢 Tokens indexed: {stats?.tokens_indexed ?? '—'}</div>
          <div>🔢 Context Tokens: {stats?.context_tokens ?? '—'}</div>
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
                    : 'ml-[20%] bg-gray-900 text-white'
                }`}
              >
                {m.content}
              </div>
            </div>
          ))}
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

      {/* Manage Project Modal */}
      <Dialog open={showManageModal} onClose={() => { setShowManageModal(false); if (projectId) loadStats(projectId) }}>
        <DialogHeader>Manage Project</DialogHeader>
        <div className="space-y-4 px-4 pb-2">
          <div className="text-sm text-gray-700 dark:text-gray-300">
            <div><strong>Name:</strong> {projectInfo?.name ?? projectId}</div>
            {projectInfo?.created_at && <div><strong>Created:</strong> {new Date(projectInfo.created_at).toLocaleString()}</div>}
            {projectInfo?.system && <div className="text-amber-600">System project</div>}
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


