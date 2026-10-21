export type RunAction = 'view' | 'kill' | 'resume' | 'openReview' | 'screenplayReview' | 'lineage' | 'replay' | 'export'

interface RunActionInput {
  status: string
  resumable?: boolean
  review_id?: string | null
  workflow_slug?: string | null
}

export function getRunActions(run: RunActionInput): RunAction[] {
  const actions: RunAction[] = ['view']
  const isScreenplay = run.workflow_slug === 'screenplay'
  switch (run.status) {
    case 'queued':
    case 'running':
      actions.push('kill')
      break
    case 'waiting':
      if (isScreenplay) actions.push('screenplayReview')
      else if (run.review_id) actions.push('openReview')
      actions.push('resume')
      break
    case 'failed':
    case 'cancelled':
    case 'blocked':
      if (run.resumable) {
        actions.push('resume')
      } else {
        actions.push('replay')
      }
      break
    case 'completed':
      if (!isScreenplay && run.review_id) actions.push('openReview')
      if (isScreenplay) actions.push('screenplayReview')
      actions.push('lineage', 'replay', 'export')
      break
  }
  return actions
}

