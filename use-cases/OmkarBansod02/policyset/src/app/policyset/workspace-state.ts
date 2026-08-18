import type { ChangeSet, PolicyDocumentType } from "@/domain";
import type {
  PolicyDocumentContentStateMap,
  SuperDocsJobView,
  SuperDocsTargetedJob,
} from "./superdocs-contract";

export type EditTarget = {
  documentType: PolicyDocumentType;
  documentId: string;
};

export type EditState =
  | { stage: "idle" }
  | { stage: "submitting"; target: EditTarget }
  | { stage: "processing"; target: EditTarget; job: SuperDocsJobView }
  | { stage: "awaiting_review"; target: EditTarget; job: SuperDocsJobView }
  | {
      stage: "applying";
      target: EditTarget;
      job: SuperDocsJobView;
      message: string;
    }
  | { stage: "completed"; message: string }
  | { stage: "error"; message: string };

export type SynchronizedState =
  | { stage: "idle" }
  | { stage: "error"; message: string }
  | { stage: "preparing"; changeSet: ChangeSet }
  | {
      stage: "processing";
      changeSet: ChangeSet;
      preEditState: PolicyDocumentContentStateMap;
      jobs: readonly SuperDocsTargetedJob[];
    }
  | {
      stage: "awaiting_review";
      changeSet: ChangeSet;
      preEditState: PolicyDocumentContentStateMap;
      jobs: readonly SuperDocsTargetedJob[];
    }
  | {
      stage: "applying";
      changeSet: ChangeSet;
      preEditState: PolicyDocumentContentStateMap;
      jobs: readonly SuperDocsTargetedJob[];
      message: string;
    }
  | { stage: "rejected"; changeSet: ChangeSet; message: string }
  | { stage: "failed"; changeSet: ChangeSet; message: string }
  | {
      stage: "synchronized";
      changeSet: ChangeSet;
      unchangedDocuments: readonly PolicyDocumentType[];
    };

/** Replaces one job's entry within a "processing"-stage jobs array. No-op for any other stage. */
export function withUpdatedJob(
  state: SynchronizedState,
  documentType: PolicyDocumentType,
  nextJob: SuperDocsJobView,
): SynchronizedState {
  if (state.stage !== "processing") {
    return state;
  }
  return {
    ...state,
    jobs: state.jobs.map((targeted) =>
      targeted.documentType === documentType
        ? { documentType, job: nextJob }
        : targeted,
    ),
  };
}

export function isEditBusy(stage: EditState["stage"]): boolean {
  return (
    stage === "submitting" ||
    stage === "processing" ||
    stage === "awaiting_review" ||
    stage === "applying"
  );
}

export function isSynchronizedBusy(stage: SynchronizedState["stage"]): boolean {
  return (
    stage === "preparing" ||
    stage === "processing" ||
    stage === "awaiting_review" ||
    stage === "applying"
  );
}

export function activeSynchronizedChangeSet(
  state: SynchronizedState,
): ChangeSet | null {
  return "changeSet" in state ? state.changeSet : null;
}
