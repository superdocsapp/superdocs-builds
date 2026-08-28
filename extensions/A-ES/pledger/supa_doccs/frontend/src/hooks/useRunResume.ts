import { useState, useCallback } from "react";
import { resumeRun, fetchRunProgress } from "@/services/approvalApi";
import { useRunProgressStore } from "@/stores/runProgressStore";

interface UseRunResumeResult {
  /** Whether a resume request is currently in-flight */
  isResuming: boolean;
  /** Error message from the last failed resume attempt, null if none */
  resumeError: string | null;
  /** Trigger a resume for the given run */
  handleResume: (runId: string) => Promise<void>;
  /** Clear the current error */
  clearResumeError: () => void;
}

/**
 * Hook to manage run resume lifecycle:
 * - Calls POST /runs/{run_id}/resume
 * - On success: fetches fresh progress and updates runProgressStore
 * - On failure: sets resumeError for display (e.g., toast)
 */
export function useRunResume(): UseRunResumeResult {
  const [isResuming, setIsResuming] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);
  const setProgress = useRunProgressStore((s) => s.setProgress);

  const handleResume = useCallback(
    async (runId: string) => {
      setIsResuming(true);
      setResumeError(null);

      try {
        await resumeRun(runId);
        // Fetch fresh progress to update stepper and status badge
        const progress = await fetchRunProgress(runId);
        setProgress(progress);
      } catch (error: unknown) {
        const message =
          error instanceof Error ? error.message : "Failed to resume run";
        setResumeError(message);
      } finally {
        setIsResuming(false);
      }
    },
    [setProgress]
  );

  const clearResumeError = useCallback(() => {
    setResumeError(null);
  }, []);

  return { isResuming, resumeError, handleResume, clearResumeError };
}
