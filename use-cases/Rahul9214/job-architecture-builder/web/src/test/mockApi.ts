import type {
  ArchitectureSummary,
  CorpusSummary,
  ExceptionCard,
  FrameworkPayload,
  ImpactPayload,
  ProfileDetail,
  ProfileSummary,
  ReviewPayload,
  RoleDetail,
  SuperDocsStatus,
  UpdatePlanView,
} from "../types";

type MockOptions = {
  analyzed?: boolean;
  failArchitecture?: boolean;
  superdocsConfigured?: boolean;
  reviewEmpty?: boolean;
};

const corporaBase: CorpusSummary[] = [
  {
    corpus_id: "corpus-a",
    organization: "Northstar Systems",
    description: "Synthetic product company",
    role_count: 21,
    analyzed: false,
    roles: [
      {
        role_id: "ns-senior-swe-internal-tools",
        title: "Senior Software Engineer, Workplace Tools",
        team: "Workplace Tools",
        filename: "senior-swe-workplace-tools.md",
      },
      {
        role_id: "ns-swe-ii-payments",
        title: "Software Engineer II, Payments",
        team: "Payments",
        filename: "swe-ii-payments.md",
      },
    ],
  },
  {
    corpus_id: "corpus-b",
    organization: "Meridian HealthTech",
    description: "Synthetic health-tech company",
    role_count: 12,
    analyzed: false,
    roles: [
      {
        role_id: "mh-clinical-ops-analyst",
        title: "Clinical Operations Analyst",
        team: "Clinical Ops",
        filename: "clinical-ops-analyst.md",
      },
    ],
  },
];

const architecture: ArchitectureSummary = {
  corpus_id: "corpus-a",
  organization: "Northstar Systems",
  metrics: {
    total_roles: 21,
    proposed_families: 5,
    tracks: 2,
    strong_fits: 12,
    provisional: 6,
    misfits: 2,
    unclustered: 1,
    bridge_roles: 1,
  },
  families: [{ id: "software-engineering", name: "Software Engineering", description: "Product engineering." }],
  tracks: [{ id: "ic", name: "Individual Contributor", kind: "ic", description: "IC track." }],
  clusters: [
    {
      cluster_id: "cluster-eng",
      proposed_family: "Software Engineering",
      member_role_ids: ["ns-swe-ii-payments"],
      members: [
        {
          role_id: "ns-swe-ii-payments",
          title: "Software Engineer II, Payments",
          cohesion: 0.82,
          nearest_other_cluster_id: "cluster-pm",
          nearest_other_similarity: 0.21,
          is_ambiguous: false,
        },
      ],
      cohesion: 0.8,
      nearest_cluster_id: "cluster-pm",
      nearest_cluster_similarity: 0.21,
      separation: 0.59,
      ambiguous_role_ids: [],
      label_confidence: 0.9,
      notes: "",
    },
  ],
  unclustered_role_ids: ["ns-special-projects"],
  bridge_role_ids: ["ns-hybrid"],
  title_conflicts: [
    {
      role_id: "ns-senior-swe-internal-tools",
      title: "Senior Software Engineer, Workplace Tools",
      fit_status: "provisional",
      proposed_level: "IC1",
      proposed_track: "ic",
      title_conflict: {
        kind: "title_seniority_overstates_evidence",
        summary: "The title signals seniority, but evidence supports a junior individual-contributor level.",
        title_signal: "senior-style title",
        evidence_result: "individual contributor IC1",
      },
    },
  ],
};

const roleDetail: RoleDetail = {
  role_id: "ns-senior-swe-internal-tools",
  title: "Senior Software Engineer, Workplace Tools",
  team: "Workplace Tools",
  organization: "Northstar Systems",
  filename: "senior-swe-workplace-tools.md",
  proposed_family: "Software Engineering",
  career_track: "ic",
  level: "IC1",
  fit_status: "provisional",
  confidence: 0.5,
  supporting_evidence: ["Works from defined tickets with close review."],
  counter_evidence: ["Title suggests seniority; evidence is IC1 scoped."],
  misfit_reasons: [],
  source_references: [{ document_id: "jd-1", locator: "responsibilities", excerpt: "Implements assigned tickets." }],
  signals: {
    scope: "Single-team tickets",
    autonomy: "Needs review",
    impact: "Local tooling",
    leadership: "None",
  },
  cluster_id: "cluster-eng",
  profile_id: "profile-ns-senior-swe-internal-tools",
  title_conflict: {
    kind: "title_seniority_overstates_evidence",
    summary: "The title signals seniority, but evidence supports a junior individual-contributor level.",
    title_signal: "senior-style title",
    evidence_result: "individual contributor IC1",
  },
};

const exceptions = {
  provisional: [
    exception("ns-senior-swe-internal-tools", "provisional", "Title suggests seniority; evidence remains junior."),
  ],
  hybrid_bridge: [
    exception("ns-hybrid", "hybrid_bridge", "Evidence spans two crafts; left as a bridge."),
  ],
  misfit: [
    exception(
      "ns-facilities-coordinator",
      "misfit",
      "Facilities operations sit outside the supported architecture.",
      "requires_architecture_decision",
    ),
  ],
};

const framework: FrameworkPayload = {
  organization: "Northstar Systems",
  purpose: "A defensible career framework from job-description evidence.",
  principles: ["Evidence over titles"],
  tracks: [
    { id: "ic", name: "Individual Contributor", kind: "ic", description: "IC ladder." },
    { id: "manager", name: "People Manager", kind: "manager", description: "Manager ladder." },
  ],
  levels: [
    level("ic1", "IC1", "Local tickets", "Guided", "Familiar work", "Team", "Peer help", ""),
    level("ic4", "IC4", "Cross-team domain", "Sets sequencing", "Novel systems", "Org", "Technical leadership", ""),
    level("m1", "M1", "One team", "Hires and coaches", "People systems", "Team outcomes", "People leadership", "Direct reports"),
  ],
  families: [{ id: "software-engineering", name: "Software Engineering", description: "Engineering craft." }],
  competency_matrices: [
    {
      family_id: "software-engineering",
      family_name: "Software Engineering",
      evidence_limited: false,
      limitation: "",
      competencies: [{ id: "systems", name: "Systems thinking", description: "Designs durable services." }],
    },
  ],
  role_mappings: [],
  provisional_summary: [{ role_id: "ns-senior-swe-internal-tools", title: "Senior SWE", summary: "Provisional IC1", fit_status: "provisional" }],
  misfit_summary: [{ role_id: "ns-facilities-coordinator", title: "Facilities Coordinator", summary: "Outside architecture", fit_status: "misfit" }],
  profile_count: 1,
  default_occupied_level_id: "ic4",
  editable_dimensions: ["scope", "autonomy", "decision_authority", "complexity", "impact", "leadership", "people_management"],
};

const profileSummary: ProfileSummary = {
  profile_id: "profile-ns-swe-ii-payments",
  role_id: "ns-swe-ii-payments",
  display_title: "Software Engineer II, Payments",
  family_name: "Software Engineering",
  track_name: "Individual Contributor",
  level_label: "IC4",
  classification: "strong_fit",
  is_provisional: false,
};

const profileDetail: ProfileDetail = {
  ...profileSummary,
  role_purpose: "Owns payment sequencing.",
  responsibilities: ["Designs payment services."],
  scope_decision_making: "Cross-team domain.",
  core_competencies: "Systems thinking.",
  level_expectations: "Scope: Cross-team domain\nComplexity: Novel systems",
  progression: "Toward IC5 staff-shaped work.",
  source_evidence_note: "Drawn from the Payments JD.",
};

const impact: ImpactPayload = {
  level_id: "ic4",
  level_label: "IC4",
  changed_dimensions: ["scope"],
  affected_profiles_count: 1,
  unaffected_profiles_count: 8,
  affected_profile_ids: ["profile-ns-swe-ii-payments"],
  unaffected_profile_ids: ["profile-other"],
  affected_sections: [
    {
      profile_id: "profile-ns-swe-ii-payments",
      section_id: "level_expectations",
      reason: "Depends on IC4 scope",
      edge_id: "edge-ic4-payments",
    },
  ],
  reason: "Canonical IC4 scope changed.",
  old_level: { scope: "Cross-team domain" },
  new_level: { scope: "Cross-team domain plus sequencing veto." },
};

const plan: UpdatePlanView = {
  plan_id: "profile-ns-swe-ii-payments:level_expectations",
  profile_id: "profile-ns-swe-ii-payments",
  section_id: "level_expectations",
  before: "Scope: Cross-team domain",
  after: "Scope: Cross-team domain plus sequencing veto.",
  reason: "IC4 scope changed",
  status: "proposed",
  preserved_rendered_fields: ["complexity", "impact"],
  changed_rendered_fields: ["scope"],
  dependency: {
    id: "edge-ic4-payments",
    source_id: "ic4",
    source_version: 1,
    target_id: "profile-ns-swe-ii-payments",
  },
  decision: null,
};

function exception(
  roleId: string,
  bucket: string,
  why: string,
  status = "review_required",
): ExceptionCard {
  return {
    role_id: roleId,
    title: roleId,
    bucket,
    fit_status: bucket === "misfit" ? "misfit" : "provisional",
    confidence: 0.5,
    proposed_family: bucket === "misfit" ? null : "Software Engineering",
    proposed_track: "ic",
    proposed_level: bucket === "misfit" ? null : "IC1",
    why,
    reasons: [{ code: bucket, summary: why, detail: why }],
    supporting_evidence: [why],
    counter_evidence: [],
    nearest_cluster_id: bucket === "misfit" ? "cluster-eng" : null,
    nearest_similarity: bucket === "misfit" ? 0.12 : null,
    status,
    has_normalized_profile: bucket !== "misfit",
  };
}

function level(
  id: string,
  label: string,
  scope: string,
  autonomy: string,
  complexity: string,
  impactValue: string,
  leadership: string,
  people: string,
): FrameworkPayload["levels"][number] {
  return {
    id,
    label,
    track_id: label.startsWith("M") ? "manager" : "ic",
    version: 1,
    scope,
    autonomy_decision: autonomy,
    complexity,
    impact: impactValue,
    leadership,
    people_management: people,
  };
}

function json(data: unknown, status = 200): Promise<Response> {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: async () => data,
  } as Response);
}

export function installApiMock(options: MockOptions = {}) {
  const analyzed = new Set<string>();
  if (options.analyzed !== false) {
    analyzed.add("corpus-a");
    analyzed.add("corpus-b");
  }
  const reviewState: { payload: ReviewPayload } = {
    payload: options.reviewEmpty
      ? emptyReview()
      : {
          empty: false,
          corpus_id: "corpus-a",
          remote_operation: "none",
          review_outcome: "pending",
          mutation_applied: false,
          domain_applied: false,
          plans: [{ ...plan, decision: null }],
          impact,
          preservation: null,
        },
  };

  const superdocs: SuperDocsStatus = {
    configured: Boolean(options.superdocsConfigured),
    offline_demo: !options.superdocsConfigured,
    live_export_available: false,
    live_export_reason: options.superdocsConfigured
      ? "Live SuperDocs export stays in the CLI."
      : "SUPERDOCS_API_KEY is not configured. Browse the architecture offline.",
    live: { present: false },
  };

  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method ?? "GET").toUpperCase();
    if (url === "/api/health") return json({ ok: true });
    if (url === "/api/superdocs/status") return json(superdocs);
    if (url === "/api/corpora") {
      return json({
        corpora: corporaBase.map((item) => ({ ...item, analyzed: analyzed.has(item.corpus_id) })),
      });
    }
    const corpusMatch = url.match(/^\/api\/corpora\/([^/]+)(\/analyze)?$/);
    if (corpusMatch && method === "GET") {
      const item = corporaBase.find((row) => row.corpus_id === corpusMatch[1]);
      if (!item) return json({ ok: false, code: "corpus_not_found", message: "Unknown corpus" }, 404);
      return json({ ...item, analyzed: analyzed.has(item.corpus_id) });
    }
    if (corpusMatch && method === "POST") {
      analyzed.add(corpusMatch[1]);
      return json(architecture);
    }
    if (url.startsWith("/api/architecture/") && options.failArchitecture) {
      return json({ ok: false, code: "error", message: "Architecture service unavailable." }, 500);
    }
    const arch = url.match(/^\/api\/architecture\/([^/]+)$/);
    if (arch) return json(architecture);
    const role = url.match(/^\/api\/architecture\/([^/]+)\/roles\/([^/]+)$/);
    if (role) return json(roleDetail);
    if (url.startsWith("/api/exceptions/")) return json(exceptions);
    if (url.startsWith("/api/framework/")) return json(framework);
    const profileOne = url.match(/^\/api\/profiles\/([^/]+)\/([^/]+)$/);
    if (profileOne) return json(profileDetail);
    if (url.startsWith("/api/profiles/")) {
      return json({
        profiles: [
          profileSummary,
          {
            ...profileSummary,
            profile_id: "profile-ns-swe-backend",
            role_id: "ns-swe-backend",
            display_title: "Software Engineer, Backend",
            level_label: "IC3",
          },
        ],
        review_artifacts: [
          {
            kind: "review_artifact",
            role_id: "ns-facilities-coordinator",
            title: "Facilities Coordinator",
            fit_status: "misfit",
            summary: "Outside the supported architecture.",
            normalized_profile: false,
          },
        ],
      });
    }
    if (url.includes("/level-change") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as { value?: string };
      if (!body.value) {
        return json({ ok: false, code: "malformed_level_edit", message: "Dimension values must be non-empty strings." }, 400);
      }
      return json(impact);
    }
    if (url.includes("/updates/") && method === "POST") {
      reviewState.payload = {
        empty: false,
        corpus_id: "corpus-a",
        remote_operation: "none",
        review_outcome: "pending",
        mutation_applied: false,
        domain_applied: false,
        plans: [{ ...plan, decision: null }],
        impact,
        preservation: null,
      };
      return json({ impact, plans: reviewState.payload.plans, review: reviewState.payload });
    }
    if (url.includes("/review/") && url.endsWith("/decisions") && method === "POST") {
      const body = JSON.parse(String(init?.body ?? "{}")) as {
        items: Array<{ plan_id: string; approved: boolean }>;
      };
      const nextPlans = reviewState.payload.plans.map((item) => {
        const found = body.items.find((decision) => decision.plan_id === item.plan_id);
        return found ? { ...item, decision: found.approved } : item;
      });
      reviewState.payload = {
        ...reviewState.payload,
        plans: nextPlans,
        review_outcome: nextPlans.every((item) => item.decision) ? "approved" : "mixed",
      };
      return json(reviewState.payload);
    }
    if (url.includes("/review/") && url.endsWith("/apply") && method === "POST") {
      reviewState.payload = {
        ...reviewState.payload,
        remote_operation: "local_completed",
        mutation_applied: true,
        domain_applied: true,
        review_outcome: "approved",
        preservation: {
          ok: true,
          unrelated_sections_preserved: true,
          unchanged_section_count: 7,
          changed_section_count: 1,
          violations: [],
        },
      };
      return json(reviewState.payload);
    }
    if (url.startsWith("/api/review/")) return json(reviewState.payload);
    if (url.startsWith("/api/export/") && method === "POST") {
      return json({
        ok: true,
        path: "exports/web/corpus-a/framework.docx",
        filename: "framework.docx",
        via: "local_docx",
        superdocs: false,
      });
    }
    return json({ ok: false, code: "not_mocked", message: `Unmocked ${method} ${url}` }, 404);
  };
}

function emptyReview(): ReviewPayload {
  return {
    empty: true,
    corpus_id: "corpus-a",
    remote_operation: "none",
    review_outcome: "none",
    mutation_applied: false,
    domain_applied: false,
    plans: [],
    message: "No pending review. Propose a level change first.",
  };
}
