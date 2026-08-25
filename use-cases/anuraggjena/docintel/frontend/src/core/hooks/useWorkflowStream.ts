import { useCallback, useEffect, useRef, useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { authApi } from '../api/authApi'

export interface StageUpdate {
  stage_name: string
  status: 'running' | 'completed' | 'failed'
  stage_index: number
  started_at: string | null
  completed_at: string | null
  execution_time_ms: number | null
  error_message: string | null
  decision_type?: string | null
  decision_reason?: string | null
}

export interface RunStatus {
  status: string
  current_stage: string | null
  error_message: string | null
}

export type StreamConnectionState = 'idle' | 'connecting' | 'connected' | 'disconnected'

export interface WorkflowStreamState {
  stages: StageUpdate[]
  runStatus: RunStatus | null
  isDone: boolean
  error: string | null
  isConnected: boolean
  connectionState: StreamConnectionState
}

export interface UseWorkflowStreamOptions {
  enabled?: boolean
  onInvalidate?: () => void
}

export function useWorkflowStream(
  runId: string | null,
  options?: UseWorkflowStreamOptions
): WorkflowStreamState {
  const { enabled = true, onInvalidate } = options ?? {}
  const { accessToken } = useAuth()
  const [stages, setStages] = useState<StageUpdate[]>([])
  const [runStatus, setRunStatus] = useState<RunStatus | null>(null)
  const [isDone, setIsDone] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [connectionState, setConnectionState] = useState<StreamConnectionState>('idle')
  const eventSourceRef = useRef<EventSource | null>(null)
  const onInvalidateRef = useRef(onInvalidate)

  onInvalidateRef.current = onInvalidate

  const triggerInvalidate = useCallback(() => {
    onInvalidateRef.current?.()
  }, [])

  useEffect(() => {
    if (!runId || !accessToken || !enabled) {
      setConnectionState('idle')
      setIsConnected(false)
      return
    }

    let es: EventSource | null = null
    let cancelled = false

    setConnectionState('connecting')
    setIsConnected(false)

    const connectStream = async () => {
      try {
        const streamToken = await authApi.createStreamToken(runId, accessToken)
        if (cancelled) return

        const url = `/api/v1/stream/workflow-run/${runId}?token=${encodeURIComponent(streamToken)}`
        es = new EventSource(url)
        eventSourceRef.current = es

        es.onopen = () => {
          if (cancelled) return
          setIsConnected(true)
          setConnectionState('connected')
        }

        es.addEventListener('stage_update', (e: MessageEvent) => {
          const data: StageUpdate = JSON.parse(e.data)
          setStages((prev) => {
            const exists = prev.findIndex((s) => s.stage_name === data.stage_name)
            if (exists >= 0) {
              const updated = [...prev]
              updated[exists] = data
              return updated
            }
            return [...prev, data]
          })
          triggerInvalidate()
        })

        es.addEventListener('run_status', (e: MessageEvent) => {
          const data: RunStatus = JSON.parse(e.data)
          setRunStatus(data)
          triggerInvalidate()
        })

        es.addEventListener('done', () => {
          setIsDone(true)
          triggerInvalidate()
          es?.close()
          setIsConnected(false)
          setConnectionState('disconnected')
        })

        es.addEventListener('error', (e: MessageEvent) => {
          try {
            const data = JSON.parse(e.data)
            setError(data.message)
          } catch {
            setError('Stream error')
          }
          es?.close()
          setIsConnected(false)
          setConnectionState('disconnected')
        })

        es.addEventListener('timeout', () => {
          setError('Stream timed out')
          es?.close()
          setIsConnected(false)
          setConnectionState('disconnected')
        })

        es.onerror = () => {
          setIsConnected(false)
          setConnectionState('disconnected')
        }
      } catch (err) {
        setError('Failed to create stream token')
        setConnectionState('disconnected')
        console.error('Stream token error:', err)
      }
    }

    connectStream()

    return () => {
      cancelled = true
      es?.close()
      eventSourceRef.current = null
      setIsConnected(false)
      setConnectionState('idle')
    }
  }, [runId, accessToken, enabled, triggerInvalidate])

  return { stages, runStatus, isDone, error, isConnected, connectionState }
}
