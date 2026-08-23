export type Summary = {
  cases: number;
  intended_change_coverage: number;
  collateral_damage_rate: number;
  precision_loss: number;
  latency_ms: number;
  operations_used: number;
};

export type UnitDiff = {
  chunk_id: string;
  classification: string;
  before_html: string | null;
  after_html: string | null;
};

export type Failure = {
  case_id: string;
  instruction_type: string;
  approach: string;
  score: {
    intended_change_coverage: number;
    collateral_damage_rate: number;
    precision_loss: number;
    unit_diffs: UnitDiff[];
  };
};

export type Report = {
  data_source: "fixture" | "live" | "configured";
  notice?: string;
  mode: string;
  operation_cap: number;
  actual_operations: number;
  overall: Summary;
  by_instruction_type: Record<string, Summary>;
  by_approach: Record<string, Summary>;
  failures: Failure[];
};

export type CorpusSummary = {
  cases: number;
  by_instruction_type: Record<string, number>;
  by_review_status: Record<string, number>;
  ambiguous_cases: string[];
};
