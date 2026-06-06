/**
 * Copyright (c) 2025-2026 Syx Project Contributors
 *
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Sleep status dialog.
 *
 * Displays a modal informing the user that the system is running its sleep
 * cycle, optionally showing the timestamp since sleeping began.
 */
import { Button } from '@/components/ui/button'
import { Dialog, DialogFooter, DialogHeader } from '@/components/ui/dialog'

type SleepDialogProps = {
  open: boolean
  sleepSince: string | null
  onClose: () => void
}

export function SleepDialog({ open, sleepSince, onClose }: SleepDialogProps) {
  return (
    <Dialog open={open} onClose={onClose}>
      <DialogHeader>System Sleeping</DialogHeader>
      <div className="px-4 pb-2 text-sm">
        The system is currently running its sleep cycle. Please try again after it finishes.
        {sleepSince && <div className="mt-2 text-gray-600">Sleeping since: {sleepSince}</div>}
      </div>
      <DialogFooter>
        <Button onClick={onClose}>OK</Button>
      </DialogFooter>
    </Dialog>
  )
}
