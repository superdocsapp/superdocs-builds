import type { ReactNode } from "react";

export function InfoBanner({ children }: { children: ReactNode }) {
  return <div className="info-banner">{children}</div>;
}
