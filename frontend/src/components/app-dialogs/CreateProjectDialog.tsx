/**
 * Copyright (c) 2025-2026 Syx Project Contributors
 *
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Create-project dialog.
 *
 * Renders a modal with a controlled project-name input and Cancel/Create
 * actions, delegating name changes and creation to parent callbacks.
 */
import { Button } from '@/components/ui/button'
import { Dialog, DialogFooter, DialogHeader } from '@/components/ui/dialog'

type CreateProjectDialogProps = {
  open: boolean
  projectName: string
  onProjectNameChange: (name: string) => void
  onClose: () => void
  onCreate: () => void
}

export function CreateProjectDialog({
  open,
  projectName,
  onProjectNameChange,
  onClose,
  onCreate,
}: CreateProjectDialogProps) {
  return (
    <Dialog open={open} onClose={onClose}>
      <DialogHeader>New Project</DialogHeader>
      <div className="space-y-3 px-4 pb-2">
        <input
          className="border rounded px-2 py-1 w-full"
          placeholder="Project name"
          value={projectName}
          onChange={(e) => onProjectNameChange(e.target.value)}
        />
      </div>
      <DialogFooter>
        <Button onClick={onClose}>Cancel</Button>
        <Button onClick={onCreate}>Create</Button>
      </DialogFooter>
    </Dialog>
  )
}
