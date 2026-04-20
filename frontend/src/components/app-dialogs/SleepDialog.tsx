/**
 * Copyright (c) 2025 Christopher Shuler. All rights reserved.
 *
 * This source code is part of the Syx project and is proprietary.
 *
 * Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.
 *
 * Use of this software requires explicit written permission from the copyright holder.
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
