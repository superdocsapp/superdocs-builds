import { Navigate, Route, Routes } from 'react-router-dom'

import { ProtectedRoute } from '@/core/auth'
import { LoginPage, RegisterPage } from '@/features/auth'
import { OverviewPage } from '@/features/dashboard/OverviewPage'
import { DocumentsPage } from '@/features/documents/DocumentsPage'
import { KnowledgePage } from '@/features/knowledge/KnowledgePage'
import { LineagePage } from '@/features/lineage/LineagePage'
import { ReplayPage } from '@/features/lineage/ReplayPage'
import { ReviewPage } from '@/features/reviews/ReviewPage'
import { ReviewsPage } from '@/features/reviews/ReviewsPage'
import { ScreenplayReviewPage } from '@/features/screenplay/ScreenplayReviewPage'
import { ScreenplayLibraryPage } from '@/features/screenplay/ScreenplayLibraryPage'
import { RunDetailPage } from '@/features/workflows/RunDetailPage'
import { RunsPage } from '@/features/workflows/RunsPage'
import { ExportsPage } from '@/features/exports/ExportsPage'
import { WorkspaceSettingsPage } from '@/features/workspaces/WorkspaceSettingsPage'
import { WorkspacesPage } from '@/features/workspaces/WorkspacesPage'

import { AppLayout } from './AppLayout'
import {
  ProtectedLegacyClaimLineageRedirect,
  ProtectedLegacyReplayRedirect,
  ProtectedLegacyReviewRedirect,
  ProtectedLegacyRunLineageRedirect,
  ProtectedLegacyScreenplayRedirect,
} from './LegacyRedirects'

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />

      <Route
        path="/workspaces"
        element={
          <ProtectedRoute>
            <WorkspacesPage />
          </ProtectedRoute>
        }
      />

      <Route
        path="/workspace/:workspaceId"
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route index element={<OverviewPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="runs" element={<RunsPage />} />
        <Route path="runs/:runId" element={<RunDetailPage />} />
        <Route path="runs/:runId/review" element={<ScreenplayReviewPage />} />
        <Route path="reviews" element={<ReviewsPage />} />
        <Route path="reviews/:reviewId" element={<ReviewPage />} />
        <Route path="knowledge" element={<KnowledgePage />} />
        <Route path="lineage/run/:runId" element={<LineagePage mode="run" />} />
        <Route path="lineage/claim/:claimId" element={<LineagePage mode="claim" />} />
        <Route path="replay/:runId" element={<ReplayPage />} />
        <Route path="screenplays" element={<ScreenplayLibraryPage />} />
        <Route path="exports" element={<ExportsPage />} />
        <Route path="settings" element={<WorkspaceSettingsPage />} />
      </Route>

      {/* Legacy redirects */}
      <Route path="/lineage/run/:runId" element={<ProtectedLegacyRunLineageRedirect />} />
      <Route path="/lineage/claim/:claimId" element={<ProtectedLegacyClaimLineageRedirect />} />
      <Route path="/replay/run/:runId" element={<ProtectedLegacyReplayRedirect />} />
      <Route path="/workspace/:workspaceId/review/:reviewId" element={<ProtectedLegacyReviewRedirect />} />
      <Route path="/workspace/:workspaceId/screenplay/:runId" element={<ProtectedLegacyScreenplayRedirect />} />

      <Route path="/" element={<Navigate to="/workspaces" replace />} />
    </Routes>
  )
}
