import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { Intake } from "@/lib/types";

export type Stage = "intake" | "review" | "done";

interface SessionState {
  stage: Stage;
  sessionId: string | null;
  jobId: string | null;
  intake: Intake | null;
  error: string | null;
  setStage: (stage: Stage) => void;
  setSession: (sessionId: string, jobId: string) => void;
  setIntake: (intake: Intake) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

const EMPTY = {
  stage: "intake" as Stage,
  sessionId: null,
  jobId: null,
  intake: null,
  error: null,
};

/**
 * Session state, persisted to sessionStorage.
 *
 * A draft costs a SuperDocs operation and can take minutes. Losing the session
 * id to a page refresh means the work is paid for and unreachable: the job is
 * still running upstream, but nothing on this machine knows its id any more.
 * Persisting three strings turns that from lost work into a resumed review.
 *
 * sessionStorage rather than localStorage on purpose. The intake contains a
 * third party's performance history, so it should not outlive the browser tab.
 * That is a deliberate trade of convenience for not leaving someone's negative
 * reference sitting in a shared machine's local storage indefinitely.
 */
export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      ...EMPTY,
      setStage: (stage) => set({ stage }),
      setSession: (sessionId, jobId) => set({ sessionId, jobId }),
      setIntake: (intake) => set({ intake }),
      setError: (error) => set({ error }),
      reset: () => set(EMPTY),
    }),
    {
      name: "reference-letter-drafter",
      storage: createJSONStorage(() => sessionStorage),
      partialize: (state) => ({
        stage: state.stage,
        sessionId: state.sessionId,
        jobId: state.jobId,
        intake: state.intake,
      }),
    },
  ),
);
