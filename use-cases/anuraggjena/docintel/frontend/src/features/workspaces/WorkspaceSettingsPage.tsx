import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams } from 'react-router-dom'
import {
  Layers,
  ShieldCheck,
  AlertTriangle,
  GitBranch,
  Copy,
  Check,
  Calendar,
  Save,
  Trash2,
} from 'lucide-react'

import { workspaceApi } from '@/core/api/client'
import { qualityGateApi } from '@/core/api/qualityGateApi'
import { useAuth } from '@/core/auth/AuthContext'
import { formatWorkflowSlug } from '@/core/labels'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { ErrorState } from '@/shared/components/ErrorState'
import { Skeleton } from '@/shared/components/ui/skeleton'
import { formatDate } from '@/shared/utils/formatDate'
import { cn } from '@/lib/utils'

export function WorkspaceSettingsPage() {
  const { workspaceId } = useParams<{ workspaceId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { accessToken, user } = useAuth()

  const [name, setName] = useState('')
  const [copiedId, setCopiedId] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [qgEnabled, setQgEnabled] = useState(false)
  const [qgBlockOnFailure, setQgBlockOnFailure] = useState(false)

  const canManageQualityGate = user?.role === 'reviewer' || user?.role === 'admin'

  const workspaceQuery = useQuery({
    queryKey: ['workspace', workspaceId],
    queryFn: () => workspaceApi.get(workspaceId!),
    enabled: !!workspaceId && !!accessToken,
  })

  const qualityGateQuery = useQuery({
    queryKey: ['qg-config', workspaceId],
    queryFn: () => qualityGateApi.getConfig(workspaceId!),
    enabled: !!workspaceId && !!accessToken && canManageQualityGate,
  })

  useEffect(() => {
    if (workspaceQuery.data) {
      setName(workspaceQuery.data.name)
    }
  }, [workspaceQuery.data])

  useEffect(() => {
    if (qualityGateQuery.data) {
      setQgEnabled(qualityGateQuery.data.enabled)
      setQgBlockOnFailure(qualityGateQuery.data.block_on_failure)
    } else if (qualityGateQuery.isSuccess && !qualityGateQuery.data) {
      setQgEnabled(false)
      setQgBlockOnFailure(false)
    }
  }, [qualityGateQuery.data, qualityGateQuery.isSuccess])

  const updateWorkspaceMutation = useMutation({
    mutationFn: (nextName: string) => workspaceApi.update(workspaceId!, { name: nextName }),
    onSuccess: (workspace) => {
      queryClient.invalidateQueries({ queryKey: ['workspace', workspaceId] })
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      setName(workspace.name)
    },
  })

  const deleteWorkspaceMutation = useMutation({
    mutationFn: () => workspaceApi.delete(workspaceId!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['workspaces'] })
      setDeleteOpen(false)
      navigate('/workspaces')
    },
  })

  const updateQualityGateMutation = useMutation({
    mutationFn: () =>
      qualityGateApi.upsertConfig(workspaceId!, {
        enabled: qgEnabled,
        block_on_failure: qgBlockOnFailure,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['qg-config', workspaceId] })
    },
  })

  if (!workspaceId) {
    return null
  }

  if (workspaceQuery.isLoading) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">
            Workspace Settings
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Manage workspace configuration, quality gates, and project metadata.
          </p>
        </div>
        <div className="space-y-4">
          <Skeleton className="h-64 w-full rounded-2xl" />
          <Skeleton className="h-48 w-full rounded-2xl" />
        </div>
      </div>
    )
  }

  if (workspaceQuery.error) {
    return (
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">
            Workspace Settings
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 mt-1">
            Manage workspace configuration, quality gates, and project metadata.
          </p>
        </div>
        <ErrorState
          title="Could not load workspace"
          description="Something went wrong while fetching workspace settings."
          onRetry={() => workspaceQuery.refetch()}
          error={workspaceQuery.error}
        />
      </div>
    )
  }

  const workspace = workspaceQuery.data!
  const trimmedName = name.trim()
  const nameUnchanged = trimmedName === workspace.name
  const nameInvalid = trimmedName.length === 0

  const qgConfig = qualityGateQuery.data
  const qgUnchanged =
    qgConfig !== null &&
    qgConfig !== undefined &&
    qgEnabled === qgConfig.enabled &&
    qgBlockOnFailure === qgConfig.block_on_failure
  const qgDefaultsUnchanged =
    (qgConfig === null || qgConfig === undefined) && !qgEnabled && !qgBlockOnFailure

  const handleSaveName = (event: React.FormEvent) => {
    event.preventDefault()
    if (!nameInvalid && !nameUnchanged) {
      updateWorkspaceMutation.mutate(trimmedName)
    }
  }

  const handleSaveQualityGate = () => {
    if (!qgUnchanged && !qgDefaultsUnchanged) {
      updateQualityGateMutation.mutate()
    }
  }

  const handleCopyId = () => {
    navigator.clipboard.writeText(workspaceId)
    setCopiedId(true)
    setTimeout(() => setCopiedId(false), 2000)
  }

  return (
    <div className="space-y-6 max-w-4xl">
      {/* 1. Header */}
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold text-slate-900 tracking-tight">
          Workspace Settings
        </h1>
        <p className="text-xs sm:text-sm text-slate-500 mt-1">
          Manage workspace configuration, quality gates, and project metadata.
        </p>
      </div>

      {/* 2. General Details Card */}
      <div className="bg-white border border-slate-200/90 rounded-2xl p-6 sm:p-7 shadow-xs space-y-6">
        <div className="flex items-center gap-3 pb-4 border-b border-slate-100">
          <div className="w-10 h-10 rounded-xl bg-blue-50 text-blue-600 border border-blue-100 flex items-center justify-center">
            <Layers className="w-5 h-5 stroke-[2]" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-slate-900">General Information</h2>
            <p className="text-xs text-slate-500">
              Workspace identifier, workflow architecture, and display properties.
            </p>
          </div>
        </div>

        <form onSubmit={handleSaveName} className="space-y-4">
          <div className="space-y-1.5">
            <label htmlFor="workspace-name" className="text-xs font-semibold text-slate-700">
              Workspace Name
            </label>
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-2.5">
              <input
                id="workspace-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Workspace name"
                disabled={updateWorkspaceMutation.isPending}
                className="flex-1 h-10 px-3.5 bg-white border border-slate-200 rounded-xl text-xs sm:text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none focus:ring-1 focus:ring-blue-600 focus:border-blue-600 shadow-xs"
              />
              <button
                type="submit"
                disabled={nameInvalid || nameUnchanged || updateWorkspaceMutation.isPending}
                className="inline-flex items-center justify-center gap-1.5 px-4 py-2 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-xs font-semibold rounded-xl shadow-xs transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Save className="w-3.5 h-3.5" />
                <span>{updateWorkspaceMutation.isPending ? 'Saving…' : 'Save name'}</span>
              </button>
            </div>
          </div>
        </form>

        {/* Metadata Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2">
          {/* Workflow Type */}
          <div className="p-4 bg-slate-50 border border-slate-200/70 rounded-xl space-y-1.5">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Workflow Type
            </span>
            <div className="flex items-center gap-1.5 text-xs font-bold text-slate-800">
              <GitBranch className="w-3.5 h-3.5 text-blue-600" />
              <span>{formatWorkflowSlug(workspace.workflow_type ?? 'unknown')}</span>
            </div>
          </div>

          {/* Workspace ID */}
          <div className="p-4 bg-slate-50 border border-slate-200/70 rounded-xl space-y-1.5">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Workspace ID
            </span>
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-mono text-slate-700 truncate">
                {workspaceId.slice(0, 10)}…{workspaceId.slice(-4)}
              </span>
              <button
                type="button"
                onClick={handleCopyId}
                title="Copy Workspace ID"
                className="p-1 hover:bg-slate-200/70 rounded-md text-slate-500 hover:text-slate-800 transition-colors cursor-pointer"
              >
                {copiedId ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
              </button>
            </div>
          </div>

          {/* Created At */}
          <div className="p-4 bg-slate-50 border border-slate-200/70 rounded-xl space-y-1.5">
            <span className="text-[11px] font-semibold text-slate-400 uppercase tracking-wider">
              Created Date
            </span>
            <div className="flex items-center gap-1.5 text-xs font-medium text-slate-700">
              <Calendar className="w-3.5 h-3.5 text-slate-400" />
              <span>{workspace.created_at ? formatDate(workspace.created_at) : '—'}</span>
            </div>
          </div>
        </div>
      </div>

      {/* 3. Quality Gate Card */}
      {canManageQualityGate && (
        <div className="bg-white border border-slate-200/90 rounded-2xl p-6 sm:p-7 shadow-xs space-y-6">
          <div className="flex items-center gap-3 pb-4 border-b border-slate-100">
            <div className="w-10 h-10 rounded-xl bg-purple-50 text-purple-600 border border-purple-100 flex items-center justify-center">
              <ShieldCheck className="w-5 h-5 stroke-[2]" />
            </div>
            <div>
              <h2 className="text-sm font-bold text-slate-900">Quality Gate Configuration</h2>
              <p className="text-xs text-slate-500">
                Automated validation checks and rule enforcement for completed workflow runs.
              </p>
            </div>
          </div>

          {qualityGateQuery.isLoading ? (
            <Skeleton className="h-28 w-full rounded-xl" />
          ) : (
            <div className="space-y-4">
              {/* Row 1: Enable Quality Gate */}
              <div className="flex items-center justify-between p-4 bg-slate-50 border border-slate-200/70 rounded-xl gap-4">
                <div className="space-y-0.5">
                  <span className="text-xs font-bold text-slate-900">Enable Quality Gate</span>
                  <p className="text-xs text-slate-500">
                    Run automated rule and threshold checks when workflows complete.
                  </p>
                </div>
                <label className="relative inline-flex items-center cursor-pointer shrink-0">
                  <input
                    type="checkbox"
                    checked={qgEnabled}
                    onChange={(e) => setQgEnabled(e.target.checked)}
                    disabled={updateQualityGateMutation.isPending}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                </label>
              </div>

              {/* Row 2: Block on Failure */}
              <div
                className={cn(
                  'flex items-center justify-between p-4 border rounded-xl gap-4 transition-opacity',
                  qgEnabled
                    ? 'bg-slate-50 border-slate-200/70'
                    : 'bg-slate-50/50 border-slate-200/40 opacity-50'
                )}
              >
                <div className="space-y-0.5">
                  <span className="text-xs font-bold text-slate-900">
                    Block Workflow on Failure
                  </span>
                  <p className="text-xs text-slate-500">
                    Prevent workflow run completion if quality gate checks fail.
                  </p>
                </div>
                <label className="relative inline-flex items-center cursor-pointer shrink-0">
                  <input
                    type="checkbox"
                    checked={qgBlockOnFailure}
                    onChange={(e) => setQgBlockOnFailure(e.target.checked)}
                    disabled={updateQualityGateMutation.isPending || !qgEnabled}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-slate-200 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                </label>
              </div>

              <div className="pt-2">
                <button
                  type="button"
                  onClick={handleSaveQualityGate}
                  disabled={
                    qgUnchanged ||
                    qgDefaultsUnchanged ||
                    updateQualityGateMutation.isPending
                  }
                  className="inline-flex items-center gap-1.5 px-4 py-2 bg-slate-900 hover:bg-slate-800 text-white text-xs font-semibold rounded-xl shadow-xs transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Save className="w-3.5 h-3.5" />
                  <span>
                    {updateQualityGateMutation.isPending ? 'Saving…' : 'Save quality gate'}
                  </span>
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 4. Danger Zone Card */}
      <div className="bg-red-50/20 border border-red-200/80 rounded-2xl p-6 sm:p-7 shadow-xs space-y-4">
        <div className="flex items-center gap-3 pb-3 border-b border-red-100">
          <div className="w-10 h-10 rounded-xl bg-red-100 text-red-600 flex items-center justify-center">
            <AlertTriangle className="w-5 h-5 stroke-[2]" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-red-900">Danger Zone</h2>
            <p className="text-xs text-red-700">
              Irreversible workspace deletion and permanent data purging.
            </p>
          </div>
        </div>

        <p className="text-xs text-slate-600 leading-relaxed">
          Deleting this workspace permanently removes all associated documents, workflow runs,
          classifications, memos, and knowledge entries. This action cannot be reversed.
        </p>

        <div>
          <button
            type="button"
            onClick={() => setDeleteOpen(true)}
            disabled={deleteWorkspaceMutation.isPending}
            className="inline-flex items-center gap-1.5 px-4 py-2.5 bg-red-600 hover:bg-red-700 active:bg-red-800 text-white text-xs font-semibold rounded-xl shadow-xs transition-colors cursor-pointer disabled:opacity-50"
          >
            <Trash2 className="w-3.5 h-3.5" />
            <span>Delete workspace</span>
          </button>
        </div>
      </div>

      {/* Delete Confirmation Dialog */}
      <ConfirmDialog
        open={deleteOpen}
        title="Delete workspace"
        description={`Are you sure you want to delete "${workspace.name}"? All documents, runs, and knowledge base items within this workspace will be permanently lost.`}
        confirmLabel="Delete"
        destructive
        onConfirm={() => deleteWorkspaceMutation.mutate()}
        onCancel={() => setDeleteOpen(false)}
      />
    </div>
  )
}

