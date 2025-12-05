/**
 *
 *
 *
 * Copyright (c) 2025 Christopher Shuler. All rights reserved.
 *
 * This source code is part of the Morpheus project and is proprietary.
 *
 * Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.
 *
 * Use of this software requires explicit written permission from the copyright holder.
 */

import * as React from 'react'
import { cn } from '@/lib/utils'

export function Dialog({ open, onClose, children }: { open: boolean; onClose: () => void; children: React.ReactNode }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className={cn('relative w-full max-w-lg rounded-lg border bg-white dark:bg-black shadow-lg p-4')}>{children}</div>
    </div>
  )
}

export function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('mb-3 text-lg font-semibold', className)} {...props} />
}

export function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('mt-4 flex gap-2 justify-end', className)} {...props} />
}


