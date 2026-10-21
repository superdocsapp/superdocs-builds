import { useState, useMemo } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { workspaceApi } from '@/core/api/client'
import { documentApi } from '@/core/api/documentApi'
import { runsApi } from '@/core/api/workflowApi'
import { screenplayApi, type FormattingItem } from '@/core/api/screenplayApi'
import { useAuth } from '@/core/auth/AuthContext'
import { useRunLiveUpdates } from '@/features/workflows/useRunLiveUpdates'
import { ErrorState } from '@/shared/components/ErrorState'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { AlertCircle, Loader2, RefreshCw } from 'lucide-react'

import { ScreenplayHeader } from './ScreenplayHeader'
import { ScreenplayStatusStrip } from './ScreenplayStatusStrip'
import { ScreenplayScenesCard } from './ScreenplayScenesCard'
import { ScreenplayCharactersCard } from './ScreenplayCharactersCard'
import { ScreenplayCenterView } from './ScreenplayCenterView'
import { ScreenplayAnalysisCard } from './ScreenplayAnalysisCard'
import { ScreenplayIssuesCard } from './ScreenplayIssuesCard'
import { ScreenplayRecentChangesCard } from './ScreenplayRecentChangesCard'
import { ScreenplayUploadHero } from './ScreenplayUploadHero'
import {
  extractScenes,
  extractCharacters,
  calculateAnalysisMetrics,
  extractPotentialIssues,
} from './screenplayUtils'
import type { ScreenplayScene, ScreenplayCharacter } from './types'

interface ScreenplayWorkspacePageProps {
  customRunId?: string
}

function ScreenplayWorkspaceSkeleton() {
  return (
    <div className="space-y-4 max-w-7xl mx-auto pb-10">
      <div className="flex justify-between items-center">
        <Skeleton className="h-8 w-64 rounded-lg" />
        <Skeleton className="h-9 w-32 rounded-lg" />
      </div>
      <Skeleton className="h-20 w-full rounded-xl" />
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        <div className="lg:col-span-3 space-y-4">
          <Skeleton className="h-72 rounded-xl" />
          <Skeleton className="h-56 rounded-xl" />
        </div>
        <div className="lg:col-span-6">
          <Skeleton className="h-[640px] rounded-xl" />
        </div>
        <div className="lg:col-span-3 space-y-4">
          <Skeleton className="h-44 rounded-xl" />
          <Skeleton className="h-44 rounded-xl" />
          <Skeleton className="h-64 rounded-xl" />
        </div>
      </div>
    </div>
  )
}

export function ScreenplayWorkspacePage({ customRunId }: ScreenplayWorkspacePageProps) {
  const { workspaceId, runId: routeRunId } = useParams<{ workspaceId: string; runId?: string }>()
  const effectiveRunId = customRunId || routeRunId
  const { accessToken } = useAuth()
  const navigate = useNavigate()
  const [isRetrying, setIsRetrying] = useState(false)

  // 1. Workspace query
  const workspaceQuery = useQuery({
    queryKey: ['workspace', workspaceId],
    queryFn: () => workspaceApi.get(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
  })

  // 2. Runs query
  const runsQuery = useQuery({
    queryKey: ['runs', workspaceId],
    queryFn: () => runsApi.list(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
    refetchInterval: (query) => {
      const data = query.state.data ?? []
      const hasActive = data.some((r) => ['queued', 'running', 'waiting'].includes(r.status || ''))
      return hasActive ? 2000 : false
    },
  })

  // 3. Documents query
  const documentsQuery = useQuery({
    queryKey: ['documents', workspaceId],
    queryFn: () => documentApi.list(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
  })

  const runs = runsQuery.data ?? []
  const activeRun = useMemo(() => {
    if (effectiveRunId) {
      return runs.find((r) => r.id === effectiveRunId) || null
    }
    // Default to the most recent run
    return runs.length > 0
      ? [...runs].sort(
          (a, b) =>
            new Date(b.created_at || b.started_at || 0).getTime() -
            new Date(a.created_at || a.started_at || 0).getTime()
        )[0]
      : null
  }, [runs, effectiveRunId])

  const targetRunId = activeRun?.id

  // 4. Run details query
  const runDetailQuery = useQuery({
    queryKey: ['run', workspaceId, targetRunId],
    queryFn: () => runsApi.get(workspaceId!, targetRunId!),
    enabled: !!workspaceId && !!targetRunId && !!accessToken,
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status && ['queued', 'running', 'waiting'].includes(status) ? 2000 : false
    },
  })

  // 5. Stages query
  const stagesQuery = useQuery({
    queryKey: ['run-stages', targetRunId],
    queryFn: () => runsApi.getStages(workspaceId!, targetRunId!),
    enabled: !!workspaceId && !!targetRunId && !!accessToken,
    refetchInterval: () => {
      const runStatus = runDetailQuery.data?.status || activeRun?.status
      return runStatus && ['queued', 'running', 'waiting'].includes(runStatus) ? 2000 : false
    },
  })

  // 6. Formatting Items query
  const itemsQuery = useQuery({
    queryKey: ['screenplay-items', targetRunId],
    queryFn: () => screenplayApi.listItems(targetRunId!),
    enabled: !!targetRunId && !!accessToken,
    refetchInterval: () => {
      const runStatus = runDetailQuery.data?.status || activeRun?.status
      return runStatus && ['queued', 'running', 'waiting'].includes(runStatus) ? 2000 : false
    },
  })

  // 7. Preview query (for raw source text if available)
  const previewQuery = useQuery({
    queryKey: ['screenplay-preview', targetRunId],
    queryFn: () => screenplayApi.preview(targetRunId!),
    enabled: !!targetRunId && !!accessToken,
  })

  // Hook up live updates
  useRunLiveUpdates(workspaceId, targetRunId, activeRun?.status)

  const items = itemsQuery.data ?? []
  const stages = stagesQuery.data ?? []
  const documents = documentsQuery.data ?? []
  const workspace = workspaceQuery.data

  // Screenplay UI state
  const [selectedSceneNumber, setSelectedSceneNumber] = useState<number>(1)
  const [selectedItemIndex, setSelectedItemIndex] = useState<number | undefined>(undefined)
  const [selectedCharacterName, setSelectedCharacterName] = useState<string | undefined>(undefined)

  // Derived data
  const scenes = useMemo(() => extractScenes(items), [items])
  const characters = useMemo(() => extractCharacters(items), [items])
  const metrics = useMemo(() => calculateAnalysisMetrics(items), [items])
  const issues = useMemo(() => extractPotentialIssues(items), [items])

  // Screenplay title
  const primaryDoc = documents[0]
  const screenplayTitle = primaryDoc
    ? primaryDoc.filename.replace(/\.[^/.]+$/, '').replace(/_/g, ' ')
    : workspace?.name || 'Screenplay Script'

  const pendingCount = items.filter((it) => it.status === 'pending').length

  const handleSelectScene = (scene: ScreenplayScene) => {
    setSelectedSceneNumber(scene.sceneNumber)
    setSelectedItemIndex(scene.elementIndex)
  }

  const handleSelectCharacter = (char: ScreenplayCharacter) => {
    if (selectedCharacterName === char.name) {
      setSelectedCharacterName(undefined)
    } else {
      setSelectedCharacterName(char.name)
    }
  }

  const handleSelectItem = (item: FormattingItem) => {
    setSelectedItemIndex(item.element_index)
    if (item.scene_number) {
      setSelectedSceneNumber(item.scene_number)
    }
  }

  const handleReviewChanges = () => {
    if (targetRunId && workspaceId) {
      navigate(`/workspace/${workspaceId}/runs/${targetRunId}/review`)
    }
  }

  const handleRetry = async () => {
    if (!workspaceId || !primaryDoc?.id) return
    try {
      setIsRetrying(true)
      await runsApi.create(workspaceId, {
        workflow_slug: 'screenplay',
        document_id: primaryDoc.id,
      })
      await runsQuery.refetch()
    } catch (err) {
      console.error('Failed to retry run:', err)
    } finally {
      setIsRetrying(false)
    }
  }

  const isLoading =
    workspaceQuery.isLoading ||
    runsQuery.isLoading ||
    (targetRunId && (itemsQuery.isLoading || runDetailQuery.isLoading))

  const error = workspaceQuery.error || runsQuery.error || itemsQuery.error

  if (isLoading) {
    return <ScreenplayWorkspaceSkeleton />
  }

  if (error) {
    return (
      <ErrorState
        title="Could not load Screenplay workspace"
        description="We couldn't fetch screenplay formatting data. Please try again."
        onRetry={() => {
          void workspaceQuery.refetch()
          void runsQuery.refetch()
          void itemsQuery.refetch()
        }}
        error={error}
      />
    )
  }

  // If no runs or documents exist, render the upload hero
  if (!activeRun && documents.length === 0) {
    return (
      <ScreenplayUploadHero
        workspaceId={workspaceId!}
        onWorkflowStarted={() => {
          void runsQuery.refetch()
        }}
      />
    )
  }

  return (
    <div className="space-y-4 max-w-[1400px] mx-auto pb-8">
      {/* 1. Header with Title, Status & Export DOCX */}
      <ScreenplayHeader
        title={screenplayTitle}
        statusBadge="Draft"
        pagesCount={metrics.pagesCount}
        lastSavedText="Last saved just now"
        workspaceId={workspaceId!}
        runId={targetRunId}
        runStatus={runDetailQuery.data?.status || activeRun?.status}
        pendingReviewCount={pendingCount}
        onReviewClick={handleReviewChanges}
      />

      {/* 2. Horizontal Stage Status Strip */}
      <ScreenplayStatusStrip
        runStatus={runDetailQuery.data?.status || activeRun?.status}
        stages={stages}
        documentCreatedAt={primaryDoc?.created_at || activeRun?.created_at}
      />

      {/* 3. Failed Run Error Banner */}
      {(runDetailQuery.data?.status === 'failed' || activeRun?.status === 'failed') && (
        <div className="bg-rose-50 border border-rose-200 rounded-xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-rose-800 shadow-xs">
          <div className="flex items-center gap-3">
            <AlertCircle className="w-5 h-5 text-rose-600 shrink-0" />
            <div>
              <p className="text-sm font-semibold">Screenplay processing failed</p>
              <p className="text-xs text-rose-600 mt-0.5">
                An error occurred during workflow execution. You can retry the run.
              </p>
            </div>
          </div>
          {primaryDoc && (
            <button
              type="button"
              onClick={handleRetry}
              disabled={isRetrying}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 disabled:opacity-50 rounded-lg transition-colors shrink-0 cursor-pointer self-start sm:self-auto"
            >
              {isRetrying ? (
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <RefreshCw className="w-3.5 h-3.5" />
              )}
              <span>Retry Run</span>
            </button>
          )}
        </div>
      )}

      {/* 3. 3-Column Screenplay Workspace Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-4 items-stretch lg:h-[calc(100vh-10rem)] lg:min-h-[720px] lg:max-h-[calc(100vh-10rem)] min-h-0">
        {/* Left Column: Scenes & Characters (3 cols on lg) */}
        <div className="lg:col-span-3 flex flex-col gap-3 min-h-0 h-full overflow-y-auto pr-1">
          <ScreenplayScenesCard
            scenes={scenes}
            selectedSceneNumber={selectedSceneNumber}
            onSelectScene={handleSelectScene}
          />

          <ScreenplayCharactersCard
            characters={characters}
            selectedCharacterName={selectedCharacterName}
            onSelectCharacter={handleSelectCharacter}
          />
        </div>

        {/* Center Column: Formatted Screenplay Reader / Editor (6 cols on lg) */}
        <div className="lg:col-span-6 min-h-0 h-full flex flex-col overflow-hidden">
          <ScreenplayCenterView
            items={items}
            scenes={scenes}
            activeSceneNumber={selectedSceneNumber}
            totalPages={metrics.pagesCount}
            totalWords={metrics.wordsCount}
            selectedItemIndex={selectedItemIndex}
            selectedCharacterName={selectedCharacterName}
            onSelectItem={handleSelectItem}
            rawSourceText={previewQuery.data?.original_text}
          />
        </div>

        {/* Right Column: Formatting Analysis, Issues & Recent Changes (3 cols on lg) */}
        <div className="lg:col-span-3 flex flex-col gap-3 min-h-0 h-full overflow-y-auto pr-1">
          <ScreenplayAnalysisCard metrics={metrics} />

          <ScreenplayIssuesCard issues={issues} />

          <ScreenplayRecentChangesCard
            items={items}
            selectedItemIndex={selectedItemIndex}
            onSelectItem={handleSelectItem}
            onReviewChanges={handleReviewChanges}
          />
        </div>
      </div>
    </div>
  )
}
