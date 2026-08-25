import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { screenplayApi } from '@/core/api/screenplayApi'
import { apiClient } from '@/core/api/client'
import { FormattingItemCard } from './FormattingItemCard'

interface Props {
  runId: string
  workspaceId: string
  onBack: () => void
}

export const ScreenplayReviewPanel: React.FC<Props> = ({ runId, workspaceId, onBack }) => {
  const qc = useQueryClient()
  const [regenerating, setRegenerating] = useState(false)
  const [exportMessage, setExportMessage] = useState<string | null>(null)

  const { data: items, isLoading } = useQuery({
    queryKey: ['screenplay-items', runId],
    queryFn: () => screenplayApi.listItems(runId),
    refetchInterval: regenerating ? 2000 : false,
  })

  const invalidateAll = () => {
    qc.invalidateQueries({ queryKey: ['screenplay-items', runId] })
    qc.invalidateQueries({ queryKey: ['reviews', workspaceId] })
    qc.invalidateQueries({ queryKey: ['reviews'] })
    qc.invalidateQueries({ queryKey: ['runs', workspaceId] })
  }

  const approveMutation = useMutation({
    mutationFn: (itemId: string) => screenplayApi.approveItem(runId, itemId),
    onSuccess: invalidateAll,
  })

  const rejectMutation = useMutation({
    mutationFn: ({ itemId, comment }: { itemId: string; comment?: string }) =>
      screenplayApi.rejectItem(runId, itemId, comment),
    onSuccess: invalidateAll,
  })

  const approveAllMutation = useMutation({
    mutationFn: () => screenplayApi.approveAll(runId),
    onSuccess: invalidateAll,
  })

  const handleRegenerate = async () => {
    setRegenerating(true)
    await screenplayApi.regenerate(runId)
    setTimeout(() => {
      invalidateAll()
      setRegenerating(false)
    }, 3000)
  }

  const handleExport = async () => {
    try {
      await apiClient.post(`/exports/screenplay/${runId}`, null, {
        params: { workspace_id: workspaceId },
      })
      setExportMessage('Export created. Check the exports list.')
    } catch (e) {
      setExportMessage('Export failed.')
    }
  }

  if (isLoading) return <div className="text-center py-8">Loading screenplay review...</div>

  const pending = items?.filter(i => i.status === 'pending').length ?? 0
  const approved = items?.filter(i => i.status === 'approved').length ?? 0
  const rejected = items?.filter(i => i.status === 'rejected').length ?? 0
  const changed = items?.filter(i => i.change_type !== 'no_change').length ?? 0

  return (
    <div className="space-y-6">
      <div className="bg-white p-6 rounded-lg shadow">
        <div className="flex items-center justify-between mb-4">
          <button onClick={onBack} className="text-sm text-blue-600 hover:text-blue-700">
            &larr; Back
          </button>
          <div className="flex gap-2">
            {rejected > 0 && (
              <button
                onClick={handleRegenerate}
                disabled={regenerating}
                className="px-4 py-2 text-sm bg-orange-600 text-white rounded hover:bg-orange-700 disabled:opacity-50"
              >
                {regenerating ? 'Regenerating...' : `Regenerate ${rejected} rejected`}
              </button>
            )}
            {pending > 0 && (
              <button
                onClick={() => approveAllMutation.mutate()}
                className="px-4 py-2 text-sm bg-green-600 text-white rounded hover:bg-green-700"
              >
                Approve All
              </button>
            )}
            <button
              onClick={handleExport}
              className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700"
            >
              Export DOCX
            </button>
          </div>
        </div>

        <h1 className="text-2xl font-bold text-gray-900 mb-2">Screenplay Formatting Review</h1>
        <p className="text-sm text-gray-600 mb-4">
          {changed} formatting changes detected across {items?.length ?? 0} elements
        </p>

        {exportMessage && (
          <p className="text-sm text-gray-700 mb-4">{exportMessage}</p>
        )}

        <div className="grid grid-cols-3 gap-4">
          <div className="bg-yellow-50 p-3 rounded">
            <p className="text-xs text-gray-500">Pending</p>
            <p className="text-2xl font-bold text-yellow-700">{pending}</p>
          </div>
          <div className="bg-green-50 p-3 rounded">
            <p className="text-xs text-gray-500">Approved</p>
            <p className="text-2xl font-bold text-green-700">{approved}</p>
          </div>
          <div className="bg-red-50 p-3 rounded">
            <p className="text-xs text-gray-500">Rejected</p>
            <p className="text-2xl font-bold text-red-700">{rejected}</p>
          </div>
        </div>
      </div>

      <div className="space-y-3">
        {items?.map(item => (
          <FormattingItemCard
            key={item.id}
            item={item}
            onApprove={id => approveMutation.mutate(id)}
            onReject={(id, comment) => rejectMutation.mutate({ itemId: id, comment })}
          />
        ))}
      </div>
    </div>
  )
}
