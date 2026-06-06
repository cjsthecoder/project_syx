/**
 * Copyright (c) 2025-2026 Syx Project Contributors
 *
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Select } from '@/components/ui/select'
import { Toast } from '@/components/ui/toast'
import { api } from '@/pages/app/api'
import { Message, ModelItem } from '@/pages/app/types'
import { useProjectData } from '@/hooks/useProjectData'
import { useChatStream } from '@/hooks/useChatStream'
import { SleepDialog } from '@/components/app-dialogs/SleepDialog'
import { CreateProjectDialog } from '@/components/app-dialogs/CreateProjectDialog'
import { PersonalityDialog } from '@/components/app-dialogs/PersonalityDialog'
import { ManageProjectDialog } from '@/components/app-dialogs/ManageProjectDialog'
import { DreamAnalysisDialog } from '@/components/app-dialogs/DreamAnalysisDialog'

// Survives component remounts in the same page session.
const bootstrappedProjects = new Set<string>()

export default function App() {
  // Opt-in: unset or non-truthy strings keep the stats bar hidden (matches Makefile default false).
  const showDebugValues = ['true', '1', 'yes', 'on'].includes(
    String(import.meta.env.VITE_SHOW_DEBUG_VALUES ?? '').trim().toLowerCase(),
  )
  const [error, setError] = useState<string | null>(null)
  const dismissError = useCallback(() => setError(null), [])
  const handleError = useCallback((message: string) => setError(message), [])

  const {
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
    loadStats,
    loadProjectInfo,
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
  } = useProjectData({
    showDebugValues,
    onError: handleError,
  })

  const handleBeforeSend = useCallback(() => {
    setProjectSummary(null)
    setError(null)
  }, [setProjectSummary])

  const [model, setModel] = useState('gpt-5.5')
  const [models, setModels] = useState<ModelItem[]>(['gpt-5.5'])

  // UI state
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showManageModal, setShowManageModal] = useState(false)
  const [newProjectName, setNewProjectName] = useState('')
  const [renameProjectName, setRenameProjectName] = useState('')
  const [showDreamModal, setShowDreamModal] = useState(false)
  const [showPersonalityModal, setShowPersonalityModal] = useState(false)
  const streamHandlersRef = useRef<{
    loadStats: (pid: string) => Promise<void>
    loadChats: (pid: string) => Promise<void>
  } | null>(null)

  const {
    messages,
    setMessages,
    input,
    setInput,
    loading,
    canSend,
    send,
    loadChats,
  } = useChatStream({
    projectId,
    model,
    onBeforeSend: handleBeforeSend,
    onError: handleError,
    checkSleeping,
    onAfterStream: useCallback(async (pid: string) => {
      const handlers = streamHandlersRef.current
      if (!handlers) return
      try {
        await handlers.loadStats(pid)
      } catch (e) {
        console.info('post-stream stats refresh failed', e)
      }
      try {
        await handlers.loadChats(pid)
      } catch (e) {
        console.info('post-stream chat refresh failed', e)
      }
    }, []),
  })
  useEffect(() => {
    streamHandlersRef.current = { loadStats, loadChats }
  }, [loadChats, loadStats])

  const toggleDreamKeep = (idx: number) => {
    setDreamItems((prev) => prev.map((it, i) => (i === idx ? { ...it, keep: !it.keep } : it)))
  }

  const toggleDreamRemember = (idx: number) => {
    setDreamItems((prev) => prev.map((it, i) => (i === idx ? { ...it, remember: !it.remember } : it)))
  }

  const setAssistantFlag = useCallback((
    message: Message,
    flag: 'forget' | 'keep',
    value: boolean,
  ) => {
    setMessages((list) => list.map((mm) => {
      const matchesPersisted = message.id != null && mm.id === message.id
      const matchesPending = message.id == null && message.clientId != null && mm.clientId === message.clientId
      return matchesPersisted || matchesPending ? { ...mm, [flag]: value } : mm
    }))
  }, [setMessages])

  const updateAssistantFlag = useCallback(async (
    message: Message,
    flag: 'forget' | 'keep',
    value: boolean,
  ) => {
    setAssistantFlag(message, flag, value)
    if (!projectId || message.id == null) return
    try {
      await api(`/projects/${projectId}/chats/${message.id}`, { method: 'PATCH', body: JSON.stringify({ [flag]: value }) })
    } catch (err: unknown) {
      setAssistantFlag(message, flag, !value)
      setError(err instanceof Error ? err.message : `Failed to update ${flag} flag`)
    }
  }, [projectId, setAssistantFlag])

  const listRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const loadModels = useCallback(async () => {
    try {
      const data = await api<{ models: string[] }>('/models')
      if (Array.isArray(data.models) && data.models.length) {
        setModels(data.models)
        if (!data.models.includes(model)) setModel(data.models[0])
      }
    } catch (e) {
      console.warn('loadModels failed', e)
    }
  }, [model])

  useEffect(() => {
    loadModels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadModels])

  // Refresh project data when project changes
  useEffect(() => {
    if (!projectId) {
      // Clear state when no project selected
      setMessages([])
      return
    }

    // Guard against repeated bootstraps for the same project, even across remounts.
    if (bootstrappedProjects.has(projectId)) {
      return
    }
    bootstrappedProjects.add(projectId)

    if (projectId) {
      refreshProjectData(projectId, loadChats)
      // Preload personality when switching projects
      loadPersonality(projectId)
    }
  }, [loadChats, loadPersonality, projectId, refreshProjectData, setMessages])

  // Monitor sleep status and refresh when sleep ends
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
          await refreshProjectData(projectId, loadChats)
        }
      } catch (e) {
        // Expected to be best-effort; continue polling even if a check fails.
        console.info('sleep status polling failed', e)
      }
    }, 5000) // Poll every 5 seconds while sleep modal is visible

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [loadChats, projectId, refreshProjectData, setShowSleepModal, setSleepSince, showSleepModal])

  function fmtMB(bytes?: number) {
    if (bytes === undefined || bytes === null) return '—'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  // Drag-and-drop handlers
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
          <h1 className="text-2xl font-bold">Syx</h1>
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
      {showDebugValues && (
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
      )}

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
            <div key={m.id ?? m.clientId ?? i} className={m.role === 'user' ? 'text-right' : 'text-left'}>
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
              {m.role === 'assistant' && (m.id != null || m.streamComplete) && (
                <div className="ml-[20%] mt-1 flex items-center gap-4 text-xs text-gray-600 dark:text-gray-400">
                  <label className="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={!!m.forget}
                      disabled={m.id == null}
                      onChange={(e) => updateAssistantFlag(m, 'forget', e.target.checked)}
                    />
                    <span>Forget</span>
                  </label>
                  <label className="inline-flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={!!m.keep}
                      disabled={m.id == null}
                      onChange={(e) => updateAssistantFlag(m, 'keep', e.target.checked)}
                    />
                    <span>Keep</span>
                  </label>
                </div>
              )}
            </div>
          ))}
          {loading && <div className="text-sm text-gray-500">Thinking…</div>}
        </div>
      </main>

      {error && (
        <Toast message={error} onClose={dismissError} />
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

      <SleepDialog open={showSleepModal} sleepSince={sleepSince} onClose={() => setShowSleepModal(false)} />

      <DreamAnalysisDialog
        open={showDreamModal}
        dreamItems={dreamItems}
        savingDream={savingDream}
        onClose={() => setShowDreamModal(false)}
        onToggleRemember={toggleDreamRemember}
        onToggleKeep={toggleDreamKeep}
        onSubmit={async () => {
          const ok = await saveDreamItems()
          if (ok) setShowDreamModal(false)
        }}
      />

      <CreateProjectDialog
        open={showCreateModal}
        projectName={newProjectName}
        onProjectNameChange={setNewProjectName}
        onClose={() => setShowCreateModal(false)}
        onCreate={async () => {
          await createProject(newProjectName)
          setNewProjectName('')
          setShowCreateModal(false)
        }}
      />

      <PersonalityDialog
        open={showPersonalityModal}
        systemPrompt={systemPrompt}
        tone={tone}
        verbosity={verbosity}
        formatPref={formatPref}
        creativity={creativity}
        domainFocus={domainFocus}
        onClose={() => setShowPersonalityModal(false)}
        onSave={async () => {
          await savePersonality()
          setShowPersonalityModal(false)
          setTimeout(() => setShowManageModal(true), 0)
        }}
        onSystemPromptChange={setSystemPrompt}
        onToneChange={setTone}
        onVerbosityChange={setVerbosity}
        onFormatPrefChange={setFormatPref}
        onCreativityChange={setCreativity}
        onDomainFocusChange={setDomainFocus}
      />

      <ManageProjectDialog
        open={showManageModal}
        projectId={projectId}
        projectInfo={projectInfo}
        renameProjectName={renameProjectName}
        files={files}
        dragOver={dragOver}
        onClose={() => {
          setShowManageModal(false)
          if (projectId) void loadStats(projectId)
        }}
        onRenameProjectNameChange={setRenameProjectName}
        onRename={async () => {
          await renameProject(renameProjectName)
          setRenameProjectName('')
        }}
        onDeleteProject={async () => {
          await deleteProject()
          setShowManageModal(false)
        }}
        onDeleteFile={deleteFile}
        onUploadFiles={uploadFiles}
        onOpenPersonality={async () => {
          if (projectId) {
            await loadPersonality(projectId)
          }
          setShowManageModal(false)
          setTimeout(() => setShowPersonalityModal(true), 0)
        }}
        onToggleDailyHistory={async (next) => {
          if (!projectId) return
          try {
            await api(`/projects/${projectId}`, { method: 'PATCH', body: JSON.stringify({ daily_rag_enabled: next }) })
            await loadProjectInfo(projectId)
            await loadStats(projectId)
          } catch (err: unknown) {
            setError(err instanceof Error ? err.message : 'Failed to update setting')
          }
        }}
        onDragOver={(e) => {
          e.preventDefault()
          setDragOver(true)
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
      />
    </div>
  )
}


