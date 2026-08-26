// Shape of evidence/integrity-report.json — service.integrity_report()'s
// output. One language entry's `packs` sharing one `expected` hash is the
// build's central proof (e.g. FR and SN both under the fr hash); `identical`
// is false only if a pack's own re-hashed export failed to match it.

export interface CoreIdentityEntry {
  expected: string;
  packs: string[];
  identical: boolean;
}

export interface IntegrityReport {
  core_version: number;
  packs: number;
  languages: Record<string, number>;
  core_identity: Record<string, CoreIdentityEntry>;
  all_packs_pass: boolean;
  annex_divergence: Record<string, string>;
  // Not produced by service.integrity_report today — a pack that fails
  // verification raises PackIntegrityError and is never included in a
  // report at all (CLAUDE.md: a mismatch quarantines the pack, the run
  // does not report success). Optional here so the screen can show a
  // quarantine list the moment a report ever carries one, without lying
  // about a shape the current pipeline doesn't emit.
  quarantined_packs?: string[];
}

// GET /api/countries
export interface AnnexSummary {
  legal_instruments: number;
  external_reporting_channels: number;
  escalation_tier_1: string;
}

export interface Country {
  code: string;
  country: string;
  language: string;
  office: string;
  safeguarding_lead: string;
  annex_summary: AnnexSummary;
}

// GET /api/packs, GET /api/packs/{code}
export interface CoreVerification {
  passed: boolean;
  missing_sections: number[];
  unexpected_sections: number[];
  diverged_sections: number[];
  core_hash_matches: boolean;
}

export interface PackSummary {
  code: string;
  country: string;
  language: string;
  generated: boolean;
  core_hash?: string;
  exports?: { markdown: string; docx: string };
}

export interface PackVerification {
  code: string;
  passed: boolean;
  core: CoreVerification;
  unlocalised_annex_sections: number[];
  core_hash: string;
}

// POST/GET /api/runs/*
export type RunStatus = 'pending' | 'running' | 'done' | 'error';

export interface RunSummary {
  run_id: string;
  kind: 'rollout' | 'amendment';
  status: RunStatus;
  created_at: string;
  finished_at: string | null;
}

export interface RunDetail extends RunSummary {
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface LedgerEntry {
  step: string;
  subject: string;
  operations: number;
  wall_time: number;
  status: string;
  content_key: string | null;
}

export interface RunLedger {
  run_id: string;
  status: RunStatus;
  entries: LedgerEntry[];
  total_operations: number;
}

// The shape of a completed amendment run's `result` field
// (service.run_amendment, minus the Ledger object api/runs.py strips out).
export interface AmendmentDiff {
  language: string;
  from_version: number;
  to_version: number;
  core_sections_total: number;
  changed_sections: number[];
  unchanged_sections: number[];
}

export interface NoticeResult {
  country_code: string;
  exports: { markdown: string; docx: string };
  skipped: boolean;
}

export interface AmendmentResult {
  diff: AmendmentDiff;
  notices: Record<string, NoticeResult>;
  verification: {
    from_version: number;
    to_version: number;
    all_packs_pass: boolean;
    all_annexes_untouched: boolean;
    all_v2_identity_consistent: boolean;
  };
}
