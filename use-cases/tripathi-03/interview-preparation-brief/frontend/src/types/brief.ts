/** Shared TypeScript types mirroring backend Brief schemas. */

export type BriefStatus = "pending" | "running" | "completed" | "failed";

export interface SkillItem {
  name: string;
  category?: string | null;
  evidence?: string | null;
}

export interface EvidenceAnswer {
  question: string;
  answer: string;
  evidence_spans: string[];
  has_evidence: boolean;
}

export interface StarAnswer {
  question: string;
  situation: string;
  task: string;
  action: string;
  result: string;
  has_evidence: boolean;
  note?: string | null;
}

export interface RoadmapPhase {
  phase: string;
  goals: string[];
  actions: string[];
}

export interface BriefContent {
  company_overview: string;
  role_summary: string;
  required_skills: SkillItem[];
  matching_skills: SkillItem[];
  missing_skills: SkillItem[];
  resume_improvements: string[];
  likely_interview_questions: string[];
  evidence_backed_answers: EvidenceAnswer[];
  technical_topics: string[];
  company_specific_questions: string[];
  star_answers: StarAnswer[];
  roadmap: RoadmapPhase[];
}

export interface BriefResponse {
  brief_id: string;
  session_id: string;
  status: BriefStatus;
  company_name: string;
  content: BriefContent | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentUploadResponse {
  session_id: string;
  resume_document_id: string;
  jd_document_id: string;
  company_name: string;
  message: string;
}

export interface BriefStatusResponse {
  brief_id: string;
  session_id: string;
  status: BriefStatus;
  current_step?: string | null;
  error?: string | null;
}

export interface HistoryItem {
  brief_id: string;
  session_id: string;
  company_name: string;
  status: BriefStatus;
  created_at: string;
  role_summary?: string;
}

export interface WizardDraft {
  resumeFile: File | null;
  resumeFileName: string | null;
  jobDescriptionHtml: string;
  jobDescriptionText: string;
  companyName: string;
  companyUrl: string;
}
