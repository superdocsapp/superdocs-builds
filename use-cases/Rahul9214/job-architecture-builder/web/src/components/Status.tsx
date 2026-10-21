export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="loading" role="status">
      {label}
    </div>
  );
}

export function Empty({ children }: { children: string }) {
  return <div className="empty">{children}</div>;
}

export function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="error" role="alert">
      {message}
    </div>
  );
}

export function FitChip({ status }: { status: string }) {
  const tone =
    status === "strong_fit" ? "good" : status === "misfit" ? "misfit" : status === "provisional" ? "warn" : "neutral";
  return <span className={`chip ${tone}`}>{status.replace(/_/g, " ")}</span>;
}
