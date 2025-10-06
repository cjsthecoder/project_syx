import { useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Select } from '@/components/ui/select'
import { Toast } from '@/components/ui/toast'

type Message = { role: 'user' | 'assistant'; content: string }
type Project = { id: string; name: string }

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
  const [projectId, setProjectId] = useState<string>('default')
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [model, setModel] = useState('gpt-5')
  const [tokens, setTokens] = useState<number | null>(null)

  const listRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    api<{ available_projects?: string[]; current_project?: string }>('/projects')
      .then((data) => {
        const list = (data.available_projects ?? ['default']).map((id) => ({ id, name: id === 'default' ? 'Default' : id }))
        setProjects(list)
        if (!projectId) {
          setProjectId(data.current_project ?? list[0]?.id ?? 'default')
        }
      })
      .catch(() => {
        setProjects([{ id: 'default', name: 'Default' }])
        if (!projectId) setProjectId('default')
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const canSend = useMemo(() => input.trim().length > 0 && !loading, [input, loading])

  async function send() {
    if (!canSend) return
    setError(null)
    setLoading(true)
    const userMsg: Message = { role: 'user', content: input }
    setMessages((m) => [...m, userMsg])
    setInput('')
    try {
      const res = await api<{ response: string; llm_model: string; tokens_used: number | null }>('/chat', {
        method: 'POST',
        body: JSON.stringify({ message: userMsg.content, project_id: projectId }),
      })
      setModel(res.llm_model)
      setTokens(res.tokens_used ?? null)
      setMessages((m) => [...m, { role: 'assistant', content: res.response }])
    } catch (e: any) {
      setError(e?.message || 'Request failed')
    } finally {
      setLoading(false)
    }
  }

  // Removed Query RAG and Sleep Cycle for v1

  return (
    <div className="h-full flex flex-col">
      <header className="border-b px-4 py-2 flex items-center gap-4">
        <h1 className="text-lg font-semibold">Morpheus</h1>
        <Select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </Select>
        <div className="ml-auto text-sm text-gray-700 dark:text-gray-300 flex items-center gap-3">
          <span>Model: {model || '—'}</span>
          <span>Tokens: {tokens ?? '—'}</span>
        </div>
      </header>

      <main className="flex-1 overflow-hidden">
        <div ref={listRef} className="h-full overflow-auto p-4 space-y-3">
          {messages.map((m, i) => (
            <div key={i} className={m.role === 'user' ? 'text-right' : 'text-left'}>
              <div className={`inline-block rounded px-3 py-2 ${m.role === 'user' ? 'bg-gray-200 text-black' : 'bg-gray-900 text-white'}`}>
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
    </div>
  )
}


