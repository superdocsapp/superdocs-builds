import { ApiError } from "../api.js";

/**
 * Everything the pane says when it cannot show a result.
 *
 * A stack trace is not a message. Each error code maps to a sentence that tells
 * the reader what happened and what to do about it; the underlying detail is
 * kept as the hint rather than thrown away, so a developer still has something
 * to work with.
 */

const TITLES: Record<string, string> = {
  no_api_key: "No SuperDocs API key",
  auth_failed: "SuperDocs rejected the API key",
  quota_exhausted: "Monthly operation quota is used up",
  invalid_selection: "That selection cannot be used",
  empty_instruction: "No rewrite instruction",
  upstream_error: "SuperDocs could not be reached",
  timeout: "SuperDocs took too long",
  unexpected_response: "Unexpected response from SuperDocs",
  job_failed: "The rewrite job failed",
  server_unreachable: "The TokenScope server is not running",
  host_error: "The document could not be changed"
};

export function ErrorCallout({
  error,
  onDismiss
}: {
  error: Error;
  onDismiss?: () => void;
}): JSX.Element {
  const code = error instanceof ApiError ? error.code : "host_error";
  const hint = error instanceof ApiError ? error.hint : undefined;

  return (
    <div className="callout callout--error" role="alert">
      <div className="callout__title">{TITLES[code] ?? "Something went wrong"}</div>
      <p className="callout__body">{error.message}</p>
      {hint !== undefined && hint.length > 0 && <p className="callout__hint">{hint}</p>}
      {onDismiss !== undefined && (
        <button type="button" className="button button--quiet" onClick={onDismiss}>
          Dismiss
        </button>
      )}
    </div>
  );
}

export function Callout({
  tone,
  title,
  children
}: {
  tone: "info" | "warn";
  title: string;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <div className={`callout callout--${tone}`}>
      <div className="callout__title">{title}</div>
      <div className="callout__body">{children}</div>
    </div>
  );
}
