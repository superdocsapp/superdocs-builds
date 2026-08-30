import type { Change, ChangeStatus } from "./types";

export type TransitionActionType =
  | "approve"
  | "reject"
  | "revert"
  | "markConflicted"
  | "resolveConflict"
  | "markFailed"
  | "supersede";

export type TransitionAction =
  | { type: "approve"; by: string; at: string }
  | { type: "reject"; by: string; at: string }
  | { type: "revert"; by: string; at: string }
  | { type: "markConflicted"; at: string }
  | { type: "resolveConflict"; resolution: "approved" | "rejected"; by: string; at: string }
  | { type: "markFailed"; at: string }
  | { type: "supersede"; at: string };

export class IllegalTransitionError extends Error {
  constructor(
    public readonly from: ChangeStatus,
    public readonly action: TransitionActionType
  ) {
    super(`Cannot apply "${action}" to a Change in status "${from}"`);
    this.name = "IllegalTransitionError";
  }
}

const TERMINAL_STATUSES: ReadonlySet<ChangeStatus> = new Set([
  "rejected",
  "reverted",
  "superseded",
  "failed",
]);

/**
 * Apply one transition to a Change, returning a new Change (never mutates
 * its argument). Re-applying the action a Change is already in the target
 * state for is a safe no-op — not an error — so that a decision submitted
 * twice (a named failure mode in the brief) can never double-write the
 * audit trail or throw at the user. Applying an action that's genuinely
 * illegal from the current state (e.g. reverting something that was never
 * approved) throws `IllegalTransitionError` rather than silently coercing
 * the status, so bugs surface immediately instead of corrupting state.
 */
export function applyTransition(change: Change, action: TransitionAction): Change {
  switch (action.type) {
    case "approve": {
      if (change.status === "approved") return change;
      if (change.status !== "proposed" && change.status !== "conflicted") {
        throw new IllegalTransitionError(change.status, action.type);
      }
      return {
        ...change,
        status: "approved",
        decidedBy: action.by,
        decidedAt: action.at,
        updatedAt: action.at,
      };
    }

    case "reject": {
      if (change.status === "rejected") return change;
      if (change.status !== "proposed" && change.status !== "conflicted") {
        throw new IllegalTransitionError(change.status, action.type);
      }
      return {
        ...change,
        status: "rejected",
        decidedBy: action.by,
        decidedAt: action.at,
        updatedAt: action.at,
      };
    }

    case "revert": {
      if (change.status === "reverted") return change;
      if (change.status !== "approved") {
        throw new IllegalTransitionError(change.status, action.type);
      }
      return {
        ...change,
        status: "reverted",
        decidedBy: action.by,
        decidedAt: action.at,
        updatedAt: action.at,
      };
    }

    case "markConflicted": {
      if (change.status === "conflicted") return change;
      if (TERMINAL_STATUSES.has(change.status)) {
        throw new IllegalTransitionError(change.status, action.type);
      }
      return { ...change, status: "conflicted", updatedAt: action.at };
    }

    case "resolveConflict": {
      if (change.status !== "conflicted") {
        throw new IllegalTransitionError(change.status, action.type);
      }
      return {
        ...change,
        status: action.resolution,
        decidedBy: action.by,
        decidedAt: action.at,
        updatedAt: action.at,
      };
    }

    case "markFailed": {
      if (TERMINAL_STATUSES.has(change.status)) {
        throw new IllegalTransitionError(change.status, action.type);
      }
      return { ...change, status: "failed", updatedAt: action.at };
    }

    case "supersede": {
      if (change.status === "superseded") return change;
      if (change.status !== "proposed") {
        throw new IllegalTransitionError(change.status, action.type);
      }
      return { ...change, status: "superseded", updatedAt: action.at };
    }
  }
}

export function isTerminal(status: ChangeStatus): boolean {
  return TERMINAL_STATUSES.has(status);
}
