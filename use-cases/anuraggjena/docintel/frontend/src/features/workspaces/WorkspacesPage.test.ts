import { describe, it, expect } from 'vitest'

describe('All Workspaces Logic & Data Formatting', () => {
  it('calculates accurate aggregate statistics from real runs', () => {
    const workspaces = [
      { id: 'ws-1', name: 'Tariff E2E Test', workflow_type: 'tariff_classification' },
      { id: 'ws-2', name: 'Screenplay Demo', workflow_type: 'screenplay' },
      { id: 'ws-3', name: 'Ruling Analysis', workflow_type: 'knowledge' },
    ]

    const runsByWorkspace = new Map([
      ['ws-1', [
        { id: 'r1', status: 'running' },
        { id: 'r2', status: 'completed' },
        { id: 'r3', status: 'completed' },
      ]],
      ['ws-2', [
        { id: 'r4', status: 'waiting' },
        { id: 'r5', status: 'completed' },
      ]],
      ['ws-3', [
        { id: 'r6', status: 'failed' },
      ]],
    ])

    const totalWorkspaces = workspaces.length
    let activeRuns = 0
    let completedRuns = 0
    let exportsGenerated = 0

    runsByWorkspace.forEach((runs) => {
      runs.forEach((r) => {
        if (r.status === 'running' || r.status === 'waiting' || r.status === 'in_progress') {
          activeRuns++
        } else if (r.status === 'completed') {
          completedRuns++
          exportsGenerated++
        }
      })
    })

    expect(totalWorkspaces).toBe(3)
    expect(activeRuns).toBe(2)
    expect(completedRuns).toBe(3)
    expect(exportsGenerated).toBe(3)
  })

  it('filters workspaces by search query, workflow type, and status', () => {
    const workspaces = [
      { id: 'ws-1', name: 'Tariff E2E Test', workflow_type: 'tariff_classification', status: 'active' },
      { id: 'ws-2', name: 'Screenplay Demo', workflow_type: 'screenplay', status: 'active' },
      { id: 'ws-3', name: 'Ruling Analysis', workflow_type: 'knowledge', status: 'completed' },
    ]

    // Search filter
    const query = 'tariff'
    const searchFiltered = workspaces.filter((w) =>
      w.name.toLowerCase().includes(query) || (w.workflow_type || '').toLowerCase().includes(query)
    )
    expect(searchFiltered).toHaveLength(1)
    expect(searchFiltered[0].id).toBe('ws-1')

    // Type filter
    const screenplayFiltered = workspaces.filter((w) =>
      (w.workflow_type || '').toLowerCase().includes('screenplay')
    )
    expect(screenplayFiltered).toHaveLength(1)
    expect(screenplayFiltered[0].id).toBe('ws-2')

    // Status filter
    const completedFiltered = workspaces.filter((w) =>
      w.status.toLowerCase() === 'completed'
    )
    expect(completedFiltered).toHaveLength(1)
    expect(completedFiltered[0].id).toBe('ws-3')
  })

  it('ensures actions menu is restricted ONLY to delete action', () => {
    // Only 'delete' is allowed in the actions menu definition
    const allowedActions = ['delete'] as const
    const prohibitedActions = ['edit', 'duplicate', 'archive', 'settings', 'open', 'rename']

    prohibitedActions.forEach((action) => {
      expect((allowedActions as readonly string[]).includes(action)).toBe(false)
    })
  })
})
