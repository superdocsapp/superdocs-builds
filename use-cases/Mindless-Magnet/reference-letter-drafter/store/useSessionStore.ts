import { create } from "zustand";
import type { Intake } from "@/lib/types";

export type Stage = "intake" | "drafting" | "review" | "done";

interface SessionState {
  stage: Stage;
  sessionId: string | null;
  jobId: string | null;
  intake: Intake | null;
  error: string | null;
  setStage: (stage: Stage) => void;
  setSessionId: (id: string) => void;
  setJobId: (id: string | null) => void;
  setIntake: (intake: Intake) => void;
  setError: (error: string | null) => void;
  reset: () => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  stage: "intake",
  sessionId: null,
  jobId: null,
  intake: null,
  error: null,
  setStage: (stage) => set({ stage }),
  setSessionId: (sessionId) => set({ sessionId }),
  setJobId: (jobId) => set({ jobId }),
  setIntake: (intake) => set({ intake }),
  setError: (error) => set({ error }),
  reset: () =>
    set({
      stage: "intake",
      sessionId: null,
      jobId: null,
      intake: null,
      error: null,
    }),
}));
