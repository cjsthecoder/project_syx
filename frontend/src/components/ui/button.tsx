/**
 * Copyright (c) 2025 Syx Project Contributors. All rights reserved.
 *
 * This source code is part of the Syx project and is proprietary.
 *
 * Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.
 *
 * Use of this software requires explicit written permission from the copyright holder.
 */
import * as React from 'react'
import { cn } from '@/lib/utils'

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, ...props }, ref) => {
    return (
      <button
        ref={ref}
        className={cn(
          'inline-flex items-center justify-center rounded-md border px-3 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 disabled:opacity-50',
          'bg-black text-white hover:bg-gray-800 dark:bg-white dark:text-black dark:hover:bg-gray-200',
          className
        )}
        {...props}
      />
    )
  }
)
Button.displayName = 'Button'
