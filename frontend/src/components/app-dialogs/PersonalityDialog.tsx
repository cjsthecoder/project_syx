/**
 * Copyright (c) 2025-2026 Syx Project Contributors
 *
 * SPDX-License-Identifier: MIT
 *
 * This file is part of the Syx project. See the LICENSE file in the project
 * root for full license information.
 */
import { Button } from '@/components/ui/button'
import { Dialog, DialogFooter, DialogHeader } from '@/components/ui/dialog'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'

type PersonalityDialogProps = {
  open: boolean
  systemPrompt: string
  tone: 'analytical' | 'friendly' | 'creative' | 'formal'
  verbosity: 'concise' | 'balanced' | 'detailed'
  formatPref: 'markdown' | 'plain' | 'html'
  creativity: number
  domainFocus: string
  onClose: () => void
  onSave: () => void
  onSystemPromptChange: (value: string) => void
  onToneChange: (value: 'analytical' | 'friendly' | 'creative' | 'formal') => void
  onVerbosityChange: (value: 'concise' | 'balanced' | 'detailed') => void
  onFormatPrefChange: (value: 'markdown' | 'plain' | 'html') => void
  onCreativityChange: (value: number) => void
  onDomainFocusChange: (value: string) => void
}

export function PersonalityDialog({
  open,
  systemPrompt,
  tone,
  verbosity,
  formatPref,
  creativity,
  domainFocus,
  onClose,
  onSave,
  onSystemPromptChange,
  onToneChange,
  onVerbosityChange,
  onFormatPrefChange,
  onCreativityChange,
  onDomainFocusChange,
}: PersonalityDialogProps) {
  return (
    <Dialog open={open} onClose={onClose}>
      <DialogHeader>Project Personality</DialogHeader>
      <div className="space-y-4 px-4 pb-2">
        <div>
          <label className="block text-sm mb-1">System Prompt</label>
          <Textarea className="w-full min-h-[700px]" value={systemPrompt} onChange={(e) => onSystemPromptChange(e.target.value)} />
        </div>
        <div className="grid grid-cols-3 gap-3 items-end">
          <div>
            <label className="block text-sm mb-1">Tone</label>
            <Select value={tone} onChange={(e) => onToneChange(e.target.value as 'analytical' | 'friendly' | 'creative' | 'formal')}>
              {['analytical', 'friendly', 'creative', 'formal'].map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <label className="block text-sm mb-1">Verbosity</label>
            <Select value={verbosity} onChange={(e) => onVerbosityChange(e.target.value as 'concise' | 'balanced' | 'detailed')}>
              {['concise', 'balanced', 'detailed'].map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <label className="block text-sm mb-1">Format</label>
            <Select value={formatPref} onChange={(e) => onFormatPrefChange(e.target.value as 'markdown' | 'plain' | 'html')}>
              {['markdown', 'plain', 'html'].map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </Select>
          </div>
        </div>
        <div>
          <label className="block text-sm mb-1">Creativity ({creativity.toFixed(2)})</label>
          <input
            type="range"
            min={0}
            max={1}
            step={0.01}
            value={creativity}
            onChange={(e) => onCreativityChange(parseFloat(e.target.value))}
            className="w-full"
          />
        </div>
        <div>
          <label className="block text-sm mb-1">Domain Focus (comma-separated)</label>
          <input
            className="border rounded px-2 py-1 w-full"
            value={domainFocus}
            onChange={(e) => onDomainFocusChange(e.target.value)}
            placeholder="AI, neuroscience"
          />
        </div>
      </div>
      <DialogFooter>
        <Button onClick={onClose}>Cancel</Button>
        <Button onClick={onSave}>Save</Button>
      </DialogFooter>
    </Dialog>
  )
}
