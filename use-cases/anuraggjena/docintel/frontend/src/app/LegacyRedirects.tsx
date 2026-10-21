import type { ReactNode } from 'react'
import { Navigate, useParams } from 'react-router-dom'

import { ProtectedRoute } from '@/core/auth'

const LAST_WORKSPACE_KEY = 'lastWorkspaceId'

function getLastWorkspaceId(): string | null {
  return sessionStorage.getItem(LAST_WORKSPACE_KEY)
}

function withAuth(children: ReactNode) {
  return <ProtectedRoute>{children}</ProtectedRoute>
}

export function LegacyRunLineageRedirect() {
  const { runId } = useParams<{ runId: string }>()
  const lastWorkspace = getLastWorkspaceId()

  if (lastWorkspace && runId) {
    return <Navigate to={`/workspace/${lastWorkspace}/lineage/run/${runId}`} replace />
  }

  return <Navigate to="/workspaces" replace />
}

export function LegacyClaimLineageRedirect() {
  const { claimId } = useParams<{ claimId: string }>()
  const lastWorkspace = getLastWorkspaceId()

  if (lastWorkspace && claimId) {
    return <Navigate to={`/workspace/${lastWorkspace}/lineage/claim/${claimId}`} replace />
  }

  return <Navigate to="/workspaces" replace />
}

export function LegacyReplayRedirect() {
  const { runId } = useParams<{ runId: string }>()
  const lastWorkspace = getLastWorkspaceId()

  if (lastWorkspace && runId) {
    return <Navigate to={`/workspace/${lastWorkspace}/replay/${runId}`} replace />
  }

  return <Navigate to="/workspaces" replace />
}

export function LegacyReviewRedirect() {
  const { workspaceId, reviewId } = useParams<{ workspaceId: string; reviewId: string }>()

  if (workspaceId && reviewId) {
    return <Navigate to={`/workspace/${workspaceId}/reviews/${reviewId}`} replace />
  }

  return <Navigate to="/workspaces" replace />
}

export function LegacyScreenplayRedirect() {
  const { workspaceId, runId } = useParams<{ workspaceId: string; runId: string }>()

  if (workspaceId && runId) {
    return <Navigate to={`/workspace/${workspaceId}/runs/${runId}/review`} replace />
  }

  return <Navigate to="/workspaces" replace />
}

export function ProtectedLegacyRunLineageRedirect() {
  return withAuth(<LegacyRunLineageRedirect />)
}

export function ProtectedLegacyClaimLineageRedirect() {
  return withAuth(<LegacyClaimLineageRedirect />)
}

export function ProtectedLegacyReplayRedirect() {
  return withAuth(<LegacyReplayRedirect />)
}

export function ProtectedLegacyReviewRedirect() {
  return withAuth(<LegacyReviewRedirect />)
}

export function ProtectedLegacyScreenplayRedirect() {
  return withAuth(<LegacyScreenplayRedirect />)
}
