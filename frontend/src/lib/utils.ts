/**
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
/**
 * Shared frontend utility helpers.
 *
 * Exports `cn`, which merges conditional class names via clsx and resolves
 * conflicting Tailwind classes with tailwind-merge.
 */
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/**
 * Merge conditional class names, resolving conflicting Tailwind utilities so the
 * last-specified class wins.
 *
 * @param inputs - Class values (strings, arrays, or conditional maps) to combine.
 * @returns The merged, conflict-resolved class string.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}


