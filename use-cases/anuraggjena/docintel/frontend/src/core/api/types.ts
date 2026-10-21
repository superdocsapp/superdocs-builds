export interface WorkflowRun {
  id: string
  workspace_id: string
  workflow_id: string
  workflow_slug?: string | null
  status: string
  resumable?: boolean
  current_stage: string | null
  workflow_version: string
  created_by: string
  version_number: number
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
  review_id?: string | null
  review_status?: string | null
}

export interface WorkflowStage {
  id: string
  stage_name: string
  status: string
  retry_count: number
  execution_time_ms: number | null
  started_at: string | null
  completed_at: string | null
  error_message: string | null
  decision_type?: string | null
  decision_reason?: string | null
}

export interface CreateRunRequest {
  workflow_slug: string
  document_id: string
  created_by?: string
}

export interface Workspace {
  id: string
  name: string
  owner_user_id: string
  workflow_type: string | null
  status: string
  created_at: string
  updated_at: string
}

export interface CreateWorkspaceRequest {
  name: string
  workflow_type?: string
}

export interface UpdateWorkspaceRequest {
  name?: string
  workflow_type?: string
}

export interface Evidence {
  id: string
  workflow_run_id: string
  document_id: string
  chunk_id: string | null
  extracted_text: string
  evidence_type: string
  page_number: string | null
  relevance_score: number | null
  created_at: string
}

export interface Citation {
  id: string
  claim_id: string
  evidence_id: string
  excerpt: string | null
  relevance_score: number | null
  created_at: string
}
