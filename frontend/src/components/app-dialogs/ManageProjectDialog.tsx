/**
 * Copyright (c) 2025-2026 Syx Project Contributors
 *
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Project management dialog.
 *
 * Renders a modal for managing a project: viewing metadata, opening personality
 * settings, toggling daily history, renaming, uploading/deleting files via
 * drag-and-drop or file picker, and deleting the project.
 */
import { Button } from '@/components/ui/button'
import { Dialog, DialogFooter, DialogHeader } from '@/components/ui/dialog'
import { ProjectInfo } from '@/pages/app/types'
import type { DragEventHandler } from 'react'

type ManageProjectDialogProps = {
  open: boolean
  projectId: string
  projectInfo: ProjectInfo | null
  renameProjectName: string
  files: any[]
  dragOver: boolean
  onClose: () => void
  onRenameProjectNameChange: (value: string) => void
  onRename: () => void
  onDeleteProject: () => void
  onDeleteFile: (id: number) => void
  onUploadFiles: (files: FileList) => Promise<void>
  onOpenPersonality: () => void
  onOpenUserProfile: () => void
  onToggleDailyHistory: (next: boolean) => Promise<void>
  onDragOver: DragEventHandler<HTMLDivElement>
  onDragLeave: () => void
  onDrop: DragEventHandler<HTMLDivElement>
}

export function ManageProjectDialog({
  open,
  projectId,
  projectInfo,
  renameProjectName,
  files,
  dragOver,
  onClose,
  onRenameProjectNameChange,
  onRename,
  onDeleteProject,
  onDeleteFile,
  onUploadFiles,
  onOpenPersonality,
  onOpenUserProfile,
  onToggleDailyHistory,
  onDragOver,
  onDragLeave,
  onDrop,
}: ManageProjectDialogProps) {
  return (
    <Dialog open={open} onClose={onClose}>
      <DialogHeader>Manage Project</DialogHeader>
      <div className="space-y-4 px-4 pb-2">
        <div className="text-sm text-gray-700 dark:text-gray-300">
          <div>
            <strong>Name:</strong> {projectInfo?.name ?? projectId}
          </div>
          {projectInfo?.created_at && (
            <div>
              <strong>Created:</strong> {new Date(projectInfo.created_at).toLocaleString()}
            </div>
          )}
          {projectInfo?.system && <div className="text-amber-600">System project</div>}
        </div>

        <div className="flex items-center justify-start gap-2">
          <Button
            className="bg-black !text-white hover:bg-gray-900 border-transparent dark:!bg-black dark:!text-white dark:hover:!bg-gray-900"
            onClick={onOpenPersonality}
          >
            Personality
          </Button>
          <Button
            className="bg-black !text-white hover:bg-gray-900 border-transparent dark:!bg-black dark:!text-white dark:hover:!bg-gray-900"
            onClick={onOpenUserProfile}
          >
            User Profile
          </Button>
        </div>

        {!projectInfo?.system && (
          <div className="flex items-center gap-2">
            <label className="text-sm">Keep Daily History</label>
            <input
              type="checkbox"
              checked={!!projectInfo?.daily_rag_enabled}
              onChange={(e) => void onToggleDailyHistory(e.target.checked)}
            />
          </div>
        )}

        <div className="flex items-center gap-2">
          <input
            className="border rounded px-2 py-1 flex-1"
            placeholder="Rename to…"
            value={renameProjectName}
            onChange={(e) => onRenameProjectNameChange(e.target.value)}
          />
          <Button onClick={onRename} disabled={!!projectInfo?.system}>
            Rename
          </Button>
        </div>

        <div
          className={`border-2 ${dragOver ? 'border-blue-500' : 'border-dashed border-gray-300'} rounded p-4 text-center`}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
        >
          Drag &amp; drop files here, or
          <label className="ml-2 underline cursor-pointer">
            choose files
            <input type="file" multiple className="hidden" onChange={(e) => e.target.files && void onUploadFiles(e.target.files)} />
          </label>
        </div>

        <div>
          <div className="font-semibold mb-2">Files</div>
          <ul className="space-y-2 max-h-64 overflow-auto">
            {files.map((f: any) => (
              <li key={f.id} className="flex items-center justify-between text-sm">
                <div className="truncate mr-3">{f.filename}</div>
                <div className="flex items-center gap-3">
                  <span className="text-gray-500">{(f.size_bytes / (1024 * 1024)).toFixed(1)} MB</span>
                  <Button onClick={() => onDeleteFile(f.id)}>Delete</Button>
                </div>
              </li>
            ))}
            {files.length === 0 && <li className="text-gray-500 text-sm">No files uploaded</li>}
          </ul>
        </div>

        {!projectInfo?.system && (
          <div className="flex items-center justify-end">
            <Button onClick={onDeleteProject}>Delete Project</Button>
          </div>
        )}
      </div>
      <DialogFooter>
        <Button onClick={onClose}>Close</Button>
      </DialogFooter>
    </Dialog>
  )
}
