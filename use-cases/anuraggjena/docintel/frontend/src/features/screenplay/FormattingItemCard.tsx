import React, { useState } from 'react'
import type { FormattingItem } from '@/core/api/screenplayApi'
import { formatElementType, getElementBadgeClass } from '@/core/labels'
import { ScreenplayDiffView } from './ScreenplayDiffView'

interface Props {
  item: FormattingItem
  onApprove: (itemId: string) => void
  onReject: (itemId: string, comment?: string) => void
}

export const FormattingItemCard: React.FC<Props> = ({ item, onApprove, onReject }) => {
  const [comment, setComment] = useState('')
  const [showRejectInput, setShowRejectInput] = useState(false)

  const hasChange = item.change_type !== 'no_change'
  const badgeClass = getElementBadgeClass(item.element_type)

  const statusColor =
    item.status === 'approved' ? 'border-green-300 bg-green-50' :
    item.status === 'rejected' ? 'border-red-300 bg-red-50' :
    'border-gray-200 bg-white'

  return (
    <div className={`border rounded-lg p-4 ${statusColor}`}>
      <div className="flex items-center gap-2 mb-2">
        <span className={`text-xs font-semibold px-2 py-0.5 rounded ${badgeClass}`}>
          {formatElementType(item.element_type)}
        </span>
        {item.scene_number && (
          <span className="text-xs text-gray-500">Scene {item.scene_number}</span>
        )}
        {item.content_drift && (
          <span className="text-xs bg-orange-100 text-orange-700 px-2 py-0.5 rounded">
            drift detected
          </span>
        )}
        <span className={`ml-auto text-xs font-semibold px-2 py-0.5 rounded ${
          item.status === 'approved' ? 'bg-green-100 text-green-700' :
          item.status === 'rejected' ? 'bg-red-100 text-red-700' :
          'bg-yellow-100 text-yellow-700'
        }`}>
          {item.status}
        </span>
      </div>

      {hasChange ? (
        <div className="mb-3">
          <p className="text-xs text-gray-500 mb-1">Change ({item.change_type})</p>
          {item.diff_tokens && item.diff_tokens.length > 0 ? (
            <ScreenplayDiffView tokens={item.diff_tokens} />
          ) : (
            <div className="grid grid-cols-2 gap-2 text-sm">
              <div className="bg-red-50 rounded p-2">
                <p className="text-xs text-gray-500 mb-1">Original</p>
                <p className="font-mono">{item.original_text}</p>
              </div>
              <div className="bg-green-50 rounded p-2">
                <p className="text-xs text-gray-500 mb-1">Formatted</p>
                <p className="font-mono">{item.formatted_text}</p>
              </div>
            </div>
          )}
          {item.reason && (
            <p className="text-xs text-gray-500 mt-1 italic">{item.reason}</p>
          )}
        </div>
      ) : (
        <p className="text-sm text-gray-500 mb-3 font-mono">{item.original_text}</p>
      )}

      {item.status === 'pending' && hasChange && (
        <div className="flex gap-2 mt-2">
          <button
            onClick={() => onApprove(item.id)}
            className="px-3 py-1 text-sm bg-green-600 text-white rounded hover:bg-green-700"
          >
            Approve
          </button>
          {!showRejectInput ? (
            <button
              onClick={() => setShowRejectInput(true)}
              className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700"
            >
              Reject
            </button>
          ) : (
            <div className="flex gap-2 flex-1">
              <input
                type="text"
                value={comment}
                onChange={e => setComment(e.target.value)}
                placeholder="Optional comment for regeneration"
                className="flex-1 text-sm border rounded px-2 py-1"
              />
              <button
                onClick={() => { onReject(item.id, comment); setShowRejectInput(false) }}
                className="px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700"
              >
                Confirm
              </button>
              <button
                onClick={() => setShowRejectInput(false)}
                className="px-3 py-1 text-sm bg-gray-200 text-gray-700 rounded"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
