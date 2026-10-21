export default function FailureBanner({ failure }) {
  if (!failure) return null;
  return (
    <div className="failure-banner">
      <strong>Failed:</strong> {failure.what}
      <div><em>Likely cause:</em> {failure.likely_cause}</div>
      <div><em>Next action:</em> {failure.next_action}</div>
    </div>
  );
}
