import { WorkspaceState, ReviewStatus, ChangeItem } from './types';

function isReviewDecision(status: ReviewStatus): status is 'approved' | 'applied' | 'rejected' {
  return status === 'approved' || status === 'applied' || status === 'rejected';
}

function withStatus(change: ChangeItem, status: ReviewStatus): ChangeItem {
  if (status === 'approved' || status === 'applied') {
    return { ...change, status, artifactState: change.after };
  }
  if (status === 'reverted') {
    return { ...change, status, artifactState: change.before };
  }
  return { ...change, status };
}

export function canRevert(change: Pick<ChangeItem, 'status'>): boolean {
  return change.status === 'approved' || change.status === 'applied';
}

export function updateChangeStatus(state: WorkspaceState, id: string, status: ReviewStatus): WorkspaceState {
  const target = state.changes.find(change => change.id === id);
  if (!target || target.status !== 'pending' || !isReviewDecision(status)) {
    return state;
  }
  const changes = state.changes.map(change => change.id === id ? withStatus(change, status) : change);
  const next = changes.find(c => c.status === 'pending');
  return { ...state, changes, selectedChangeId: next?.id ?? id };
}

export function revertChange(state: WorkspaceState, id: string): WorkspaceState {
  const target = state.changes.find(change => change.id === id);
  if (!target || !canRevert(target)) {
    return state;
  }
  const changes = state.changes.map(change => change.id === id ? withStatus(change, 'reverted') : change);
  return { ...state, changes, selectedChangeId: id };
}

export function summary(state: WorkspaceState) {
  const counts = { pending: 0, approved: 0, rejected: 0, applied: 0, reverted: 0, verified: 0, mismatch: 0 };
  for (const change of state.changes) {
    counts[change.status] += 1;
    counts[change.verification] += 1;
  }
  return counts;
}

export function evidenceRecord(state: WorkspaceState) {
  return {
    generatedAt: new Date().toISOString(),
    product: 'SuperDocs Agent Review Workspace',
    documents: state.documents,
    decisions: state.changes.map(({ id, documentId, agent, turn, section, claim, actual, verification, status, artifactState, before }) => ({
      id,
      documentId,
      agent,
      turn,
      section,
      claim,
      actual,
      verification,
      reviewerDecision: status,
      status,
      artifactState,
      revertedState: status === 'reverted' ? before : null
    }))
  };
}
