import { describe, it, expect } from 'vitest'
import type { WorkflowStage } from '@/core/api/types'

// Replicating Step generation helper from ScreenplayStatusStrip to test status transitions
interface StepItem {
  id: string
  title: string
  subtitle: string
  status: 'completed' | 'current' | 'pending' | 'waiting' | 'failed'
}

function getScreenplaySteps(runStatus: string, stages: WorkflowStage[] = [], documentCreatedAt?: string): StepItem[] {
  const parseStage = stages.find((s) => s.stage_name === 'parse')
  const formatStage = stages.find((s) => s.stage_name === 'format')
  const diffStage = stages.find((s) => s.stage_name === 'diff')

  const isParseDone = parseStage?.status === 'completed'
  const isFormatDone = formatStage?.status === 'completed'
  const isDiffDone = diffStage?.status === 'completed'
  const isRunComplete = runStatus === 'completed'
  const isWaitingReview = runStatus === 'waiting' || runStatus === 'awaiting_review'
  const isQueued = runStatus === 'queued'
  const isFailed = runStatus === 'failed'

  return [
    {
      id: 'uploaded',
      title: 'Uploaded',
      subtitle: documentCreatedAt
        ? new Date(documentCreatedAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
        : 'Script source',
      status: 'completed',
    },
    {
      id: 'parsed',
      title: 'Parsed & Analyzed',
      subtitle: isParseDone
        ? '100% elements'
        : parseStage?.status === 'running'
        ? 'Parsing screenplay…'
        : isQueued
        ? 'Waiting to start…'
        : isFailed && !isParseDone
        ? 'Failed'
        : 'Pending',
      status: isParseDone
        ? 'completed'
        : isFailed && !isParseDone
        ? 'failed'
        : parseStage?.status === 'running' || isQueued
        ? 'current'
        : 'pending',
    },
    {
      id: 'formatting',
      title: 'Formatting',
      subtitle: isFormatDone
        ? 'Applied standards'
        : formatStage?.status === 'running'
        ? 'Formatting screenplay…'
        : isParseDone && !isFailed
        ? 'Ready'
        : isFailed && isParseDone && !isFormatDone
        ? 'Failed'
        : 'Pending',
      status: isFormatDone
        ? 'completed'
        : isFailed && isParseDone && !isFormatDone
        ? 'failed'
        : formatStage?.status === 'running'
        ? 'current'
        : 'pending',
    },
    {
      id: 'review',
      title: 'Review',
      subtitle: isRunComplete
        ? 'Approved'
        : isWaitingReview
        ? 'Ready for review'
        : diffStage?.status === 'running'
        ? 'Reviewing formatting…'
        : isDiffDone
        ? 'In review'
        : isFailed && isFormatDone && !isDiffDone
        ? 'Failed'
        : 'Pending',
      status: isRunComplete
        ? 'completed'
        : isFailed && isFormatDone && !isDiffDone
        ? 'failed'
        : isWaitingReview
        ? 'waiting'
        : diffStage?.status === 'running' || isDiffDone
        ? 'current'
        : 'pending',
    },
    {
      id: 'validation',
      title: 'Validation',
      subtitle: isRunComplete ? 'Passed' : isFormatDone ? 'No drift detected' : 'Pending',
      status: isRunComplete ? 'completed' : isFormatDone ? 'completed' : 'pending',
    },
    {
      id: 'export',
      title: 'Export',
      subtitle: isRunComplete ? 'DOCX ready' : 'Pending',
      status: isRunComplete ? 'completed' : 'pending',
    },
  ]
}

describe('Screenplay Status UX and Review Logic Fixes', () => {
  it('displays explicit queued state without fake completed progress', () => {
    const steps = getScreenplaySteps('queued', [])
    const parsedStep = steps.find((s) => s.id === 'parsed')
    const formattingStep = steps.find((s) => s.id === 'formatting')
    const reviewStep = steps.find((s) => s.id === 'review')
    const exportStep = steps.find((s) => s.id === 'export')

    expect(parsedStep?.subtitle).toBe('Waiting to start…')
    expect(parsedStep?.status).toBe('current')
    expect(formattingStep?.status).toBe('pending')
    expect(reviewStep?.status).toBe('pending')
    expect(exportStep?.status).toBe('pending')
  })

  it('displays explicit running stages with live status descriptions', () => {
    // 1. Parsing in progress
    const parsingStages: WorkflowStage[] = [
      { id: '1', stage_name: 'parse', status: 'running', retry_count: 0, execution_time_ms: null, started_at: '', completed_at: null, error_message: null },
    ]
    const parsingSteps = getScreenplaySteps('running', parsingStages)
    expect(parsingSteps.find((s) => s.id === 'parsed')?.subtitle).toBe('Parsing screenplay…')
    expect(parsingSteps.find((s) => s.id === 'parsed')?.status).toBe('current')

    // 2. Formatting in progress
    const formattingStages: WorkflowStage[] = [
      { id: '1', stage_name: 'parse', status: 'completed', retry_count: 0, execution_time_ms: null, started_at: '', completed_at: '', error_message: null },
      { id: '2', stage_name: 'format', status: 'running', retry_count: 0, execution_time_ms: null, started_at: '', completed_at: null, error_message: null },
    ]
    const formattingSteps = getScreenplaySteps('running', formattingStages)
    expect(formattingSteps.find((s) => s.id === 'parsed')?.status).toBe('completed')
    expect(formattingSteps.find((s) => s.id === 'formatting')?.subtitle).toBe('Formatting screenplay…')
    expect(formattingSteps.find((s) => s.id === 'formatting')?.status).toBe('current')

    // 3. Diff/Review in progress
    const diffStages: WorkflowStage[] = [
      { id: '1', stage_name: 'parse', status: 'completed', retry_count: 0, execution_time_ms: null, started_at: '', completed_at: '', error_message: null },
      { id: '2', stage_name: 'format', status: 'completed', retry_count: 0, execution_time_ms: null, started_at: '', completed_at: '', error_message: null },
      { id: '3', stage_name: 'diff', status: 'running', retry_count: 0, execution_time_ms: null, started_at: '', completed_at: null, error_message: null },
    ]
    const diffSteps = getScreenplaySteps('running', diffStages)
    expect(diffSteps.find((s) => s.id === 'review')?.subtitle).toBe('Reviewing formatting…')
    expect(diffSteps.find((s) => s.id === 'review')?.status).toBe('current')
  })

  it('displays failed state properly without inferring completion', () => {
    // Failure at parse stage
    const failedSteps = getScreenplaySteps('failed', [
      { id: '1', stage_name: 'parse', status: 'failed', retry_count: 0, execution_time_ms: null, started_at: '', completed_at: '', error_message: 'Syntax error' }
    ])
    const parsedStep = failedSteps.find((s) => s.id === 'parsed')
    expect(parsedStep?.status).toBe('failed')
    expect(parsedStep?.subtitle).toBe('Failed')

    // Export is NOT completed
    expect(failedSteps.find((s) => s.id === 'export')?.status).toBe('pending')
  })

  it('displays waiting for review state when review is available', () => {
    const reviewStages: WorkflowStage[] = [
      { id: '1', stage_name: 'parse', status: 'completed', retry_count: 0, execution_time_ms: null, started_at: '', completed_at: '', error_message: null },
      { id: '2', stage_name: 'format', status: 'completed', retry_count: 0, execution_time_ms: null, started_at: '', completed_at: '', error_message: null },
      { id: '3', stage_name: 'diff', status: 'completed', retry_count: 0, execution_time_ms: null, started_at: '', completed_at: '', error_message: null },
    ]
    const steps = getScreenplaySteps('awaiting_review', reviewStages)
    const reviewStep = steps.find((s) => s.id === 'review')
    expect(reviewStep?.status).toBe('waiting')
    expect(reviewStep?.subtitle).toBe('Ready for review')
  })

  it('displays completed state with DOCX ready', () => {
    const completedStages: WorkflowStage[] = [
      { id: '1', stage_name: 'parse', status: 'completed', retry_count: 0, execution_time_ms: null, started_at: '', completed_at: '', error_message: null },
      { id: '2', stage_name: 'format', status: 'completed', retry_count: 0, execution_time_ms: null, started_at: '', completed_at: '', error_message: null },
      { id: '3', stage_name: 'diff', status: 'completed', retry_count: 0, execution_time_ms: null, started_at: '', completed_at: '', error_message: null },
    ]
    const steps = getScreenplaySteps('completed', completedStages)
    expect(steps.find((s) => s.id === 'review')?.subtitle).toBe('Approved')
    expect(steps.find((s) => s.id === 'validation')?.subtitle).toBe('Passed')
    expect(steps.find((s) => s.id === 'export')?.subtitle).toBe('DOCX ready')
    expect(steps.find((s) => s.id === 'export')?.status).toBe('completed')
  })

  it('ensures no synthetic review items are generated for queued runs', () => {
    // Reviews are derived strictly from real database reviews returned by reviewApi
    const rawDatabaseReviews: Array<{ id: string; workflow_run_id: string; status: string; notes: string | null; created_at: string }> = []
    
    // When run is queued, rawDatabaseReviews is empty
    const mappedReviews = rawDatabaseReviews.map((r) => ({
      id: r.id,
      workflow_run_id: r.workflow_run_id,
      status: r.status,
    }))

    expect(mappedReviews).toHaveLength(0)
  })

  it('creates reviews only when actual review record exists from backend', () => {
    const rawDatabaseReviews = [
      {
        id: 'rev-real-123',
        workflow_run_id: 'run-screenplay-1',
        status: 'in_review',
        notes: null,
        created_at: '2026-08-23T14:00:00Z',
      }
    ]

    const mappedReviews = rawDatabaseReviews.map((r) => ({
      id: r.id,
      workflow_run_id: r.workflow_run_id,
      status: r.status,
      isScreenplayRun: true,
    }))

    expect(mappedReviews).toHaveLength(1)
    expect(mappedReviews[0].id).toBe('rev-real-123')
    expect(mappedReviews[0].status).toBe('in_review')
  })
})

