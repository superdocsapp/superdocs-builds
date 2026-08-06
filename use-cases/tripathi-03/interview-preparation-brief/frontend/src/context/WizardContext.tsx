import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import type { WizardDraft } from "@/types/brief";

const STORAGE_KEY = "ipb-wizard-draft";

type WizardContextValue = {
  draft: WizardDraft;
  setResume: (file: File | null) => void;
  setJobDescription: (html: string, text: string) => void;
  setCompany: (name: string, url?: string) => void;
  resetDraft: () => void;
  isResumeReady: boolean;
  isJdReady: boolean;
  isCompanyReady: boolean;
};

const emptyDraft: WizardDraft = {
  resumeFile: null,
  resumeFileName: null,
  jobDescriptionHtml: "",
  jobDescriptionText: "",
  companyName: "",
  companyUrl: "",
};

function loadMeta(): Partial<WizardDraft> {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    return JSON.parse(raw) as Partial<WizardDraft>;
  } catch {
    return {};
  }
}

function persistMeta(draft: WizardDraft) {
  const meta = {
    resumeFileName: draft.resumeFileName,
    jobDescriptionHtml: draft.jobDescriptionHtml,
    jobDescriptionText: draft.jobDescriptionText,
    companyName: draft.companyName,
    companyUrl: draft.companyUrl,
  };
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(meta));
}

const WizardContext = createContext<WizardContextValue | null>(null);

export function WizardProvider({ children }: { children: ReactNode }) {
  const meta = loadMeta();
  const [draft, setDraft] = useState<WizardDraft>({
    ...emptyDraft,
    ...meta,
    resumeFile: null,
  });

  const setResume = useCallback((file: File | null) => {
    setDraft((prev) => {
      const next = {
        ...prev,
        resumeFile: file,
        resumeFileName: file?.name ?? null,
      };
      persistMeta(next);
      return next;
    });
  }, []);

  const setJobDescription = useCallback((html: string, text: string) => {
    setDraft((prev) => {
      const next = { ...prev, jobDescriptionHtml: html, jobDescriptionText: text };
      persistMeta(next);
      return next;
    });
  }, []);

  const setCompany = useCallback((name: string, url = "") => {
    setDraft((prev) => {
      const next = { ...prev, companyName: name, companyUrl: url };
      persistMeta(next);
      return next;
    });
  }, []);

  const resetDraft = useCallback(() => {
    setDraft(emptyDraft);
    sessionStorage.removeItem(STORAGE_KEY);
  }, []);

  const value = useMemo<WizardContextValue>(
    () => ({
      draft,
      setResume,
      setJobDescription,
      setCompany,
      resetDraft,
      isResumeReady: Boolean(draft.resumeFile || draft.resumeFileName),
      isJdReady: draft.jobDescriptionText.trim().length > 40,
      isCompanyReady: draft.companyName.trim().length > 1,
    }),
    [draft, setResume, setJobDescription, setCompany, resetDraft],
  );

  return <WizardContext.Provider value={value}>{children}</WizardContext.Provider>;
}

export function useWizard() {
  const ctx = useContext(WizardContext);
  if (!ctx) throw new Error("useWizard must be used within WizardProvider");
  return ctx;
}
