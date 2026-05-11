/**
 * Copyright (c) 2025-2026 Christopher Shuler. All rights reserved.
 *
 * This source code is part of the Syx project and is proprietary.
 *
 * Unauthorized copying, modification, distribution, or use of this software is strictly prohibited.
 *
 * Use of this software requires explicit written permission from the copyright holder.
 */
import { Button } from '@/components/ui/button'
import { Dialog, DialogFooter, DialogHeader } from '@/components/ui/dialog'
import { DreamItem } from '@/pages/app/types'

type DreamAnalysisDialogProps = {
  open: boolean
  dreamItems: DreamItem[]
  savingDream: boolean
  onClose: () => void
  onToggleRemember: (idx: number) => void
  onToggleKeep: (idx: number) => void
  onSubmit: () => Promise<void>
}

export function DreamAnalysisDialog({
  open,
  dreamItems,
  savingDream,
  onClose,
  onToggleRemember,
  onToggleKeep,
  onSubmit,
}: DreamAnalysisDialogProps) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      contentClassName="max-w-8xl w-[1280px] max-h-[90vh] h-[85vh] overflow-hidden flex flex-col"
    >
      <DialogHeader>Analyze Dreams</DialogHeader>
      <div className="px-4 pb-2 text-sm flex-1 overflow-auto space-y-4">
        {dreamItems.length === 0 && <div className="text-sm text-gray-600">No dream items available.</div>}

        {dreamItems.map((item, idx) => (
          <div key={item.id || idx} className="space-y-2 border border-gray-200 rounded-lg p-3 bg-white">
            <div className="text-xs font-semibold text-gray-600">
              {item.origin_type && typeof item.origin_type === 'string'
                ? item.origin_type.charAt(0).toUpperCase() + item.origin_type.slice(1)
                : 'User/Agent'}
            </div>
            <div
              className="rounded bg-gray-200 text-black px-3 py-2 whitespace-pre-wrap break-words"
              style={{ width: 'calc(100% - 100px)' }}
            >
              {item.origin_text || '(no origin text)'}
            </div>

            <div className="text-xs font-semibold text-gray-600" style={{ paddingLeft: '100px' }}>
              AI/Response
            </div>
            <div className="flex justify-end">
              <div
                className="rounded px-3 py-2 whitespace-pre-wrap break-words text-left"
                style={{ backgroundColor: '#66b5ff', color: '#000', width: 'calc(100% - 100px)' }}
              >
                {item.assistant_response || '(no response)'}
              </div>
            </div>

            {Array.isArray(item.research) && item.research.length > 0 && (
              <div className="space-y-2">
                {item.research.map((r, rIdx) => (
                  <div key={rIdx} className="rounded border border-gray-200 px-3 py-2 bg-white text-black">
                    <div className="text-xs font-semibold text-gray-700 mb-1">[RESEARCH]</div>
                    <div className="text-sm font-semibold text-black">Topic: {r?.research_topic || '(unknown topic)'}</div>
                    <div className="text-sm whitespace-pre-wrap break-words text-black">
                      {r?.research_summary || '(no summary)'}
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="flex items-center gap-4">
              <label className="inline-flex items-center gap-2">
                <input type="checkbox" checked={!!item.remember} onChange={() => onToggleRemember(idx)} />
                <span className="text-sm text-gray-700">Remember</span>
              </label>
              <label className="inline-flex items-center gap-2">
                <input type="checkbox" checked={!!item.keep} onChange={() => onToggleKeep(idx)} />
                <span className="text-sm text-gray-700">Keep</span>
              </label>
            </div>
          </div>
        ))}
      </div>
      <DialogFooter>
        <Button onClick={onClose}>Close</Button>
        <Button onClick={() => void onSubmit()} disabled={savingDream || dreamItems.length === 0}>
          {savingDream ? 'Saving…' : 'Submit'}
        </Button>
      </DialogFooter>
    </Dialog>
  )
}
