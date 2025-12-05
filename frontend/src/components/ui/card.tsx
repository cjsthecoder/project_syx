/**
 * Copyright (c) 2025 Syx Project Contributors. All rights reserved.
 *
 * This source code is part of the Morpheus project and is proprietary.
 *
 * Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.
 *
 * Use of this software requires explicit written permission from the copyright holder.
 */
import * as React from 'react'
import { cn } from '@/lib/utils'

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('rounded-lg border bg-white dark:bg-black', className)} {...props} />
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('border-b px-4 py-2', className)} {...props} />
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('p-4', className)} {...props} />
}
