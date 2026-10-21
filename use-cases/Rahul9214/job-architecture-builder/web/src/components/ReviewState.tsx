import { Metric } from "./Metric";

export function ReviewState({
  remoteOperation,
  reviewOutcome,
  mutationApplied,
  domainApplied,
}: {
  remoteOperation: string;
  reviewOutcome: string;
  mutationApplied: boolean;
  domainApplied: boolean;
}) {
  return (
    <div className="review-state" aria-label="Review state">
      <Metric value={remoteOperation} label="Remote operation" />
      <Metric value={reviewOutcome} label="Review outcome" />
      <Metric value={mutationApplied ? "yes" : "no"} label="Document mutation" />
      <Metric value={domainApplied ? "yes" : "no"} label="Domain update" />
    </div>
  );
}
