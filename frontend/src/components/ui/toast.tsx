/**
 * Copyright (c) 2025-2026 Syx Project Contributors
 *
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Toast notification component.
 *
 * Renders a fixed bottom-center message banner with optional Retry and Dismiss
 * actions, auto-dismissing after a 5-second timeout.
 */
import { useEffect } from 'react'
import { Button } from '@/components/ui/button'

export function Toast({ message, onRetry, onClose }: { message: string; onRetry?: () => void; onClose: () => void }) {
  useEffect(() => {
    const id = setTimeout(onClose, 5000)
    return () => clearTimeout(id)
  }, [onClose])

  return (
    <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 max-w-lg w-[90%] rounded border bg-white text-black dark:bg-black dark:text-white shadow px-4 py-3 flex items-center gap-3">
      <span className="text-sm">{message}</span>
      {onRetry && (
        <Button className="ml-auto" onClick={onRetry}>
          Retry
        </Button>
      )}
      <Button onClick={onClose}>
        Dismiss
      </Button>
    </div>
  )
}


