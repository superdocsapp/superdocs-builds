import type { ReactNode } from "react";

export function PageHeader({
  kicker,
  title,
  children,
}: {
  kicker?: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <header className="page-header">
      {kicker ? <p className="kicker">{kicker}</p> : null}
      <h1>{title}</h1>
      {children ? <p className="page-lede">{children}</p> : null}
    </header>
  );
}
