import { describe, it, expect, vi } from 'vitest'

interface AutoDownloadState {
  initialStatusMap: Map<string, string>
  hasAutoDownloaded: Set<string>
}


function simulateStatusObservation(
  state: AutoDownloadState,
  runId: string,
  status: string,
  downloadCallback: () => void
) {
  // 1. Track initial status on mount/open
  if (!state.initialStatusMap.has(runId)) {
    state.initialStatusMap.set(runId, status)
    if (status === 'completed') {
      // Already completed on initial load - prevent auto download
      state.hasAutoDownloaded.add(runId)
    }
  }

  // 2. Auto-download effect
  if (status !== 'completed') return
  if (state.hasAutoDownloaded.has(runId)) return

  state.hasAutoDownloaded.add(runId)
  downloadCallback()
}

describe('RunDetailPage auto-download guard', () => {
  it('squelches auto-download when opening an already-completed run', () => {
    const state: AutoDownloadState = {
      initialStatusMap: new Map(),
      hasAutoDownloaded: new Set(),
    }
    const downloadFn = vi.fn()

    // Open already-completed run
    simulateStatusObservation(state, 'run-123', 'completed', downloadFn)

    expect(downloadFn).not.toHaveBeenCalled()
    expect(state.hasAutoDownloaded.has('run-123')).toBe(true)
  })

  it('triggers auto-download only when running workflow transitions to completed', () => {
    const state: AutoDownloadState = {
      initialStatusMap: new Map(),
      hasAutoDownloaded: new Set(),
    }
    const downloadFn = vi.fn()

    // 1. Mount while still running
    simulateStatusObservation(state, 'run-456', 'running', downloadFn)
    expect(downloadFn).not.toHaveBeenCalled()

    // 2. Workflow transitions to completed
    simulateStatusObservation(state, 'run-456', 'completed', downloadFn)
    expect(downloadFn).toHaveBeenCalledTimes(1)
    expect(state.hasAutoDownloaded.has('run-456')).toBe(true)

    // 3. Subsequent renders don't download again
    simulateStatusObservation(state, 'run-456', 'completed', downloadFn)
    expect(downloadFn).toHaveBeenCalledTimes(1)
  })
})
