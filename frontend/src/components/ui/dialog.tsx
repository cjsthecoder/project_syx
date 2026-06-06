/**
 * Copyright (c) 2025-2026 Syx Project Contributors
 *
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Dialog UI primitives.
 *
 * Provides a modal Dialog component with a click-to-dismiss backdrop, plus
 * DialogHeader and DialogFooter layout helpers styled with Tailwind.
 */
import * as React from 'react'
import { cn } from '@/lib/utils'

export function Dialog({
  open,
  onClose,
  children,
  contentClassName,
}: {
  open: boolean
  onClose: () => void
  children: React.ReactNode
  contentClassName?: string
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className={cn('relative w-full max-w-lg rounded-lg border bg-white dark:bg-black shadow-lg p-4', contentClassName)}>
        {children}
      </div>
    </div>
  )
}

export function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('mb-3 text-lg font-semibold', className)} {...props} />
}

export function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('mt-4 flex gap-2 justify-end', className)} {...props} />
}


