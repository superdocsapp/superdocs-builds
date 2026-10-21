const COLORS = {
  pending: "#9aa0a6",
  analysing: "#4285f4",
  requires_review: "#f9ab00",
  blocked: "#ea4335",
  proposed: "#8430ce",
  partially_approved: "#f9ab00",
  approved: "#34a853",
  exported: "#1e8e3e",
  failed: "#d93025",
};

export default function StateBadge({ state }) {
  const color = COLORS[state] || "#9aa0a6";
  return (
    <span
      className="state-badge"
      style={{ backgroundColor: color }}
    >
      {state.replace(/_/g, " ")}
    </span>
  );
}
