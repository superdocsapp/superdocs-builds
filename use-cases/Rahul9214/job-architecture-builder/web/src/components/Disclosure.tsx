import type { ReactNode } from "react";

export function Disclosure({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details className="disclosure" open={defaultOpen || undefined}>
      <summary>{title}</summary>
      <div className="disclosure-body">{children}</div>
    </details>
  );
}
