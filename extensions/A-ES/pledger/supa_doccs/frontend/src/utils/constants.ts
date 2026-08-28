export const STATUS_COLORS: Record<string, string> = {
  pending: "bg-amber-500/20 text-amber-300 border-amber-500/40",
  approved: "bg-green-500/20 text-green-300 border-green-500/40",
  rejected: "bg-red-500/20 text-red-300 border-red-500/40",
  unverifiable: "bg-gray-500/20 text-gray-400 border-gray-500/40",
};

export interface StageDefinition {
  name: string;
  nodes: string[];
}

export const STAGES: StageDefinition[] = [
  { name: "Understand", nodes: ["ingest", "extract_text", "classify_document", "chunk", "embed"] },
  { name: "Examine", nodes: ["extract_claims", "match_rules", "match_rules_against_sources", "merge_findings", "score_confidence"] },
  { name: "Stay-Alive", nodes: ["route_to_queue", "human_review", "finalize"] },
];

export const DEFAULT_POLLING_INTERVAL_MS = 10_000;
