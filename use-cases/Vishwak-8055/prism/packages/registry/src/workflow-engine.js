// @ts-check
/**
 * Explicit workflow states, per the directive: "Never model complicated
 * workflow state with scattered booleans." Illegal transitions throw
 * immediately rather than being silently allowed.
 */
export const STATES = [
  'CREATED', 'INGESTING', 'UNDERSTANDING', 'PLANNING', 'PROPOSED',
  'AWAITING_REVIEW', 'PARTIALLY_APPROVED', 'APPLYING', 'VERIFYING',
  'VERIFIED', 'EXPORTED',
];
export const FAILURE_STATES = ['FAILED', 'CANCELLED', 'CONFLICT', 'STALE', 'NEEDS_REVIEW', 'UNVERIFIED'];

const TRANSITIONS = {
  CREATED: ['INGESTING', 'CANCELLED', 'FAILED'],
  INGESTING: ['UNDERSTANDING', 'FAILED', 'CANCELLED'],
  UNDERSTANDING: ['PLANNING', 'FAILED', 'CANCELLED'],
  PLANNING: ['PROPOSED', 'FAILED', 'CANCELLED'],
  PROPOSED: ['AWAITING_REVIEW', 'FAILED', 'CANCELLED'],
  AWAITING_REVIEW: ['PARTIALLY_APPROVED', 'NEEDS_REVIEW', 'STALE', 'CANCELLED'],
  PARTIALLY_APPROVED: ['APPLYING', 'AWAITING_REVIEW', 'CANCELLED'],
  APPLYING: ['VERIFYING', 'CONFLICT', 'FAILED'],
  VERIFYING: ['VERIFIED', 'NEEDS_REVIEW', 'UNVERIFIED', 'FAILED'],
  VERIFIED: ['EXPORTED', 'FAILED'],
  EXPORTED: [],
  FAILED: ['CREATED'],
  CANCELLED: [],
  CONFLICT: ['AWAITING_REVIEW', 'CANCELLED'],
  STALE: ['AWAITING_REVIEW', 'CANCELLED'],
  NEEDS_REVIEW: ['AWAITING_REVIEW', 'CANCELLED'],
  UNVERIFIED: ['CANCELLED'], // spec: do not publish as verified — no path from here to EXPORTED
};

export class Workflow {
  constructor(taskId) {
    this.taskId = taskId;
    this.state = 'CREATED';
    this.history = [{ state: 'CREATED', at: new Date().toISOString() }];
  }

  transition(newState) {
    const allowed = TRANSITIONS[this.state] || [];
    if (!allowed.includes(newState)) {
      throw new Error(`Workflow(${this.taskId}): illegal transition ${this.state} -> ${newState}. Allowed: ${allowed.join(', ') || '(none — terminal state)'}`);
    }
    this.state = newState;
    this.history.push({ state: newState, at: new Date().toISOString() });
    return this.state;
  }

  isTerminal() {
    return (TRANSITIONS[this.state] || []).length === 0;
  }
}
