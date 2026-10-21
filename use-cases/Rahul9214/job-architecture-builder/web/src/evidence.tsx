import { createContext, useContext, type ReactNode } from "react";

type EvidenceContextValue = {
  openEvidence: () => void;
};

const EvidenceContext = createContext<EvidenceContextValue>({
  openEvidence: () => {},
});

export function EvidenceProvider({
  openEvidence,
  children,
}: {
  openEvidence: () => void;
  children: ReactNode;
}) {
  return <EvidenceContext.Provider value={{ openEvidence }}>{children}</EvidenceContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useEvidence() {
  return useContext(EvidenceContext);
}
