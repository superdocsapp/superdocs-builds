const RUN_STATUS: Record<string, string> = {
  queued: 'Queued',
  running: 'Processing',
  waiting: 'Waiting for review',
  completed: 'Completed',
  failed: 'Failed',
  cancelled: 'Cancelled',
  blocked: 'Blocked',
}

const REVIEW_STATUS: Record<string, string> = {
  in_review: 'Needs review',
  approved: 'Approved',
  rejected: 'Rejected',
  escalated: 'Escalated',
}

const CLAIM_STATUS: Record<string, string> = {
  pending: 'Needs review',
  approved: 'Approved',
  rejected: 'Rejected',
  edited: 'Edited',
  applied: 'Approved',
  rejected_applied: 'Rejected',
}

export function formatRunStatus(status: string): string {
  return RUN_STATUS[status] ?? status
}

export function formatStageStatus(status: string): string {
  const map: Record<string, string> = {
    queued: 'Queued',
    running: 'Running',
    completed: 'Completed',
    skipped: 'Skipped',
    escalated: 'Escalated',
    blocked: 'Blocked',
    failed: 'Failed',
  }
  return map[status] ?? status
}

export function formatReviewStatus(status: string): string {
  return REVIEW_STATUS[status] ?? status
}

export function formatClaimStatus(status: string): string {
  return CLAIM_STATUS[status] ?? status
}
