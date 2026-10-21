import { useCallback, useMemo } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { useWorkflowStream } from '@/core/hooks/useWorkflowStream'
import type { LiveIndicatorState } from '@/core/layout/LiveIndicator'

const ACTIVE_STREAM_STATUSES = new Set(['queued', 'running', 'waiting', 'blocked', 'awaiting_review'])

export type RunLiveState = LiveIndicatorState

export function useRunLiveUpdates(
  workspaceId: string | undefined,
  runId: string | undefined,
  runStatus: string | undefined
) {
  const queryClient = useQueryClient()
  const isActive = !!runStatus && ACTIVE_STREAM_STATUSES.has(runStatus)

  const invalidateRunQueries = useCallback(() => {
    if (!workspaceId || !runId) return
    void queryClient.invalidateQueries({ queryKey: ['run-stages', runId] })
    void queryClient.invalidateQueries({ queryKey: ['run', workspaceId, runId] })
    void queryClient.invalidateQueries({ queryKey: ['runs', workspaceId] })
    void queryClient.invalidateQueries({ queryKey: ['run-claims', runId] })
    void queryClient.invalidateQueries({ queryKey: ['evidence', runId] })
    void queryClient.invalidateQueries({ queryKey: ['quality-gate', runId] })
    void queryClient.invalidateQueries({ queryKey: ['reviews', workspaceId] })
    void queryClient.invalidateQueries({ queryKey: ['exports', workspaceId] })
    void queryClient.invalidateQueries({ queryKey: ['screenplay-items', runId] })
    void queryClient.invalidateQueries({ queryKey: ['screenplay-preview', runId] })
  }, [workspaceId, runId, queryClient])

  const { connectionState } = useWorkflowStream(isActive ? (runId ?? null) : null, {
    enabled: isActive,
    onInvalidate: invalidateRunQueries,
  })

  const liveState: RunLiveState = useMemo(() => {
    if (!isActive) return 'hidden'
    if (connectionState === 'connecting') return 'reconnecting'
    if (connectionState === 'connected') return 'live'
    return 'polling'
  }, [isActive, connectionState])

  const isPolling = liveState === 'polling'

  return {
    liveState,
    invalidateRunQueries,
    isPolling,
  }
}
