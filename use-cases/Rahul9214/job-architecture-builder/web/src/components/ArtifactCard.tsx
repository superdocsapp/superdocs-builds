import type { ReactNode } from "react";

export function ArtifactCard({
  title,
  status,
  children,
}: {
  title: string;
  status?: ReactNode;
  children: ReactNode;
}) {
  return (
    <article className="card artifact-card">
      <header className="artifact-head">
        <h2>{title}</h2>
        {status}
      </header>
      {children}
    </article>
  );
}
