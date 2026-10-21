import { apiClient } from './client'

export interface Claim {
  id: string
  workflow_run_id: string
  review_id: string | null
  claim_type: string
  content: string
  status: string
  original_content: string | null
  edited_by: string | null
  source_stage: string | null
  created_at: string
}

export interface Review {
  id: string
  workflow_run_id: string
  workspace_id: string
  status: string
  reviewer_id: string | null
  notes: string | null
  created_at: string
}

export interface CreateReviewRequest {
  workflow_run_id: string
  workspace_id: string
  reviewer_id?: string
}

export interface UpdateReviewRequest {
  status: string
  notes?: string
}

export interface CreateClaimRequest {
  workflow_run_id: string
  claim_type: string
  content: string
  review_id?: string
  source_stage?: string
}

export interface UpdateClaimRequest {
  content: string
  edited_by?: string
}

export const reviewApi = {
  // Review operations
  createReview: async (data: CreateReviewRequest): Promise<Review> => {
    const response = await apiClient.post<Review>('/reviews', data)
    return response.data
  },

  getReview: async (reviewId: string): Promise<Review> => {
    const response = await apiClient.get<Review>(`/reviews/${reviewId}`)
    return response.data
  },

  listWorkspaceReviews: async (workspaceId: string): Promise<Review[]> => {
    const response = await apiClient.get<Review[]>(`/reviews/workspace/${workspaceId}`)
    return response.data
  },

  updateReview: async (reviewId: string, data: UpdateReviewRequest): Promise<Review> => {
    const response = await apiClient.patch<Review>(`/reviews/${reviewId}`, data)
    return response.data
  },

  // Claim operations
  createClaim: async (data: CreateClaimRequest): Promise<Claim> => {
    const response = await apiClient.post<Claim>('/reviews/claims', data)
    return response.data
  },

  listReviewClaims: async (reviewId: string): Promise<Claim[]> => {
    const response = await apiClient.get<Claim[]>(`/reviews/${reviewId}/claims`)
    return response.data
  },

  updateClaim: async (claimId: string, data: UpdateClaimRequest): Promise<Claim> => {
    const response = await apiClient.patch<Claim>(`/reviews/claims/${claimId}`, data)
    return response.data
  },

  approveClaim: async (claimId: string): Promise<Claim> => {
    const response = await apiClient.post<Claim>(`/reviews/claims/${claimId}/approve`)
    return response.data
  },

  rejectClaim: async (claimId: string): Promise<Claim> => {
    const response = await apiClient.post<Claim>(`/reviews/claims/${claimId}/reject`)
    return response.data
  },

  approveAllReviewClaims: async (reviewId: string): Promise<{ approved_count: number; review_id: string }> => {
    const response = await apiClient.post<{ approved_count: number; review_id: string }>(
      `/reviews/${reviewId}/approve-all`
    )
    return response.data
  },
}
