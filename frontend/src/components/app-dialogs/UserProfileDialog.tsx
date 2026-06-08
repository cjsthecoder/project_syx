/**
 * Copyright (c) 2025-2026 Syx Project Contributors
 *
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Modal dialog for editing a project's USER_PROFILE.txt baseline.
 *
 * The user profile is a plain-text file (about, background, projects, interests)
 * that seeds each project's retrieval context. Saving rewrites the file and
 * triggers a RAG rebuild on the backend.
 */
import { Button } from '@/components/ui/button'
import { Dialog, DialogFooter, DialogHeader } from '@/components/ui/dialog'
import { Textarea } from '@/components/ui/textarea'

type UserProfileDialogProps = {
  open: boolean
  content: string
  saving: boolean
  onClose: () => void
  onSave: () => void
  onContentChange: (value: string) => void
}

export function UserProfileDialog({ open, content, saving, onClose, onSave, onContentChange }: UserProfileDialogProps) {
  return (
    <Dialog open={open} onClose={onClose}>
      <DialogHeader>User Profile</DialogHeader>
      <div className="space-y-3 px-4 pb-2">
        <p className="text-sm text-gray-600 dark:text-gray-400">
          Baseline information about you (about, background/resume, current projects, interests). This text is indexed into
          retrieval, so the assistant has context from the first message. Saving rebuilds this project's index.
        </p>
        <Textarea
          className="w-full min-h-[600px] font-mono text-sm"
          value={content}
          onChange={(e) => onContentChange(e.target.value)}
          placeholder="# User Profile&#10;&#10;## About Me&#10;..."
        />
      </div>
      <DialogFooter>
        <Button onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button onClick={onSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </DialogFooter>
    </Dialog>
  )
}
