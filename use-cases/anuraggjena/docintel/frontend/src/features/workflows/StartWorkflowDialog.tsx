import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Play,
  Loader2,
  FileText,
  Image as ImageIcon,
  Upload,
  Check,
  AlertCircle,
} from 'lucide-react'

import type { Document } from '@/core/api/documentApi'
import { runsApi } from '@/core/api/workflowApi'
import { useAuth } from '@/core/auth/AuthContext'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/shared/components/ui/select'
import { WORKFLOW_TYPES, type WorkflowTypeValue } from '@/features/workspaces/CreateWorkspaceForm'
import { cn } from '@/lib/utils'

export interface StartWorkflowDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  workspaceId: string
  documents: Document[]
  workspaceWorkflowType?: string | null
}

function formatDocRoleBadge(role?: string, filename?: string): string {
  if (role === 'product_image' || (!role && filename?.match(/\.(png|jpg|jpeg|webp)$/i))) {
    return 'Product Image'
  }
  if (role === 'classification_ruling' || role === 'ruling') {
    return 'Classification Ruling'
  }
  if (role === 'product_spec' || role === 'product_specification' || role === 'product') {
    return 'Product Specification'
  }
  if (role) {
    return role
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ')
  }
  return 'Document'
}

function isImageFile(filename: string, role?: string): boolean {
  if (role === 'product_image') return true
  return /\.(png|jpg|jpeg|webp|gif|svg)$/i.test(filename)
}

export function StartWorkflowDialog({
  open,
  onOpenChange,
  workspaceId,
  documents,
  workspaceWorkflowType,
}: StartWorkflowDialogProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const { user } = useAuth()

  const workflowOptions = useMemo(() => {
    if (
      workspaceWorkflowType &&
      WORKFLOW_TYPES.some((option) => option.value === workspaceWorkflowType)
    ) {
      return WORKFLOW_TYPES.filter((option) => option.value === workspaceWorkflowType)
    }
    return WORKFLOW_TYPES
  }, [workspaceWorkflowType])

  const [workflowSlug, setWorkflowSlug] = useState<WorkflowTypeValue>(
    workflowOptions[0]?.value ?? WORKFLOW_TYPES[0].value
  )
  const [documentId, setDocumentId] = useState<string>('')

  useEffect(() => {
    if (!open) return
    const initialSlug = workflowOptions[0]?.value ?? WORKFLOW_TYPES[0].value
    setWorkflowSlug(initialSlug)
    if (documents.length > 0) {
      setDocumentId(documents[0].id)
    } else {
      setDocumentId('')
    }
  }, [open, workflowOptions, documents])

  const createMutation = useMutation({
    mutationFn: () =>
      runsApi.create(workspaceId, {
        workflow_slug: workflowSlug,
        document_id: documentId,
        created_by: user?.email,
      }),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: ['runs', workspaceId] })
      onOpenChange(false)
      navigate(`/workspace/${workspaceId}/runs/${run.id}`)
    },
  })

  const hasDocuments = documents.length > 0
  const canSubmit = Boolean(documentId) && !createMutation.isPending && hasDocuments
  const selectedDoc = documents.find((d) => d.id === documentId)

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl p-6 sm:p-7 bg-white border border-slate-200 rounded-2xl shadow-xl">
        {/* Header with Icon */}
        <div className="flex items-start gap-4 mb-3">
          <div className="w-11 h-11 rounded-xl bg-blue-50 text-blue-600 border border-blue-100 flex items-center justify-center shrink-0 mt-0.5">
            <Play className="w-5 h-5 fill-current stroke-[1.5]" />
          </div>

          <DialogHeader className="p-0 text-left space-y-1">
            <DialogTitle className="text-xl font-bold text-slate-900 tracking-tight">
              Start Workflow
            </DialogTitle>
            <DialogDescription className="text-sm text-slate-600 leading-relaxed">
              Configure and run an automated intelligence pipeline on your workspace documents.
            </DialogDescription>
          </DialogHeader>
        </div>

        <div className="space-y-5 py-2">
          {/* Workflow Type Selection */}
          <div className="space-y-2">
            <label className="block text-xs font-semibold text-slate-800 tracking-wide">
              Workflow Type
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {workflowOptions.map((option) => {
                const isSelected = workflowSlug === option.value
                const OptionIcon = option.Icon
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setWorkflowSlug(option.value)}
                    className={cn(
                      'relative text-left p-3.5 rounded-xl border transition-all duration-150 flex items-start gap-3 cursor-pointer',
                      isSelected
                        ? 'border-blue-600 bg-blue-50/50 ring-1 ring-blue-600/30'
                        : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/50'
                    )}
                  >
                    <div
                      className={cn(
                        'w-9 h-9 rounded-lg border flex items-center justify-center shrink-0 mt-0.5',
                        option.iconColor
                      )}
                    >
                      <OptionIcon className="w-4 h-4 stroke-[2]" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between">
                        <p className="text-xs font-bold text-slate-900 leading-tight">
                          {option.label}
                        </p>
                        {isSelected && (
                          <span className="w-4 h-4 rounded-full bg-blue-600 text-white flex items-center justify-center shrink-0">
                            <Check className="w-2.5 h-2.5 stroke-[3]" />
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-slate-500 mt-1 leading-snug line-clamp-2">
                        {option.description}
                      </p>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Target Document Selection */}
          <div className="space-y-2">
            <label
              htmlFor="workflow-document"
              className="block text-xs font-semibold text-slate-800 tracking-wide"
            >
              Target Document
            </label>

            {!hasDocuments ? (
              <div className="rounded-xl border border-dashed border-slate-300 bg-slate-50 p-5 text-center">
                <div className="w-9 h-9 rounded-lg bg-amber-50 text-amber-600 border border-amber-200 flex items-center justify-center mx-auto mb-2">
                  <AlertCircle className="w-4 h-4" />
                </div>
                <p className="text-xs font-semibold text-slate-800">
                  No documents found in this workspace
                </p>
                <p className="text-[11px] text-slate-500 mt-0.5 mb-3">
                  Upload product specification or image files to run workflows.
                </p>
                <Link
                  to={`/workspace/${workspaceId}/documents`}
                  onClick={() => onOpenChange(false)}
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded-lg shadow-sm transition-colors"
                >
                  <Upload className="w-3.5 h-3.5" />
                  <span>Upload documents</span>
                </Link>
              </div>
            ) : (
              <Select value={documentId} onValueChange={setDocumentId}>
                <SelectTrigger
                  id="workflow-document"
                  className="w-full h-12 bg-white border border-slate-200 rounded-xl px-3.5 text-xs text-slate-800 focus:border-blue-600 focus:ring-1 focus:ring-blue-600 cursor-pointer"
                >
                  <SelectValue placeholder="Select a document" />
                </SelectTrigger>
                <SelectContent className="max-h-64 bg-white border border-slate-200 rounded-xl shadow-lg p-1">
                  {documents.map((doc) => {
                    const isImg = isImageFile(doc.filename, doc.document_role)
                    return (
                      <SelectItem
                        key={doc.id}
                        value={doc.id}
                        className="rounded-lg py-2.5 px-3 text-xs cursor-pointer focus:bg-blue-50 focus:text-blue-900"
                      >
                        <div className="flex items-center gap-2.5">
                          <div
                            className={cn(
                              'w-6 h-6 rounded-md border flex items-center justify-center shrink-0',
                              isImg
                                ? 'bg-emerald-50 text-emerald-600 border-emerald-100'
                                : 'bg-red-50 text-red-600 border-red-100'
                            )}
                          >
                            {isImg ? (
                              <ImageIcon className="w-3.5 h-3.5 stroke-[2]" />
                            ) : (
                              <FileText className="w-3.5 h-3.5 stroke-[2]" />
                            )}
                          </div>
                          <span className="font-semibold text-slate-800 truncate max-w-[240px]">
                            {doc.filename}
                          </span>
                          <span className="text-[10px] font-medium text-slate-500 bg-slate-100 px-2 py-0.5 rounded-md border border-slate-200/60 ml-auto">
                            {formatDocRoleBadge(doc.document_role, doc.filename)}
                          </span>
                        </div>
                      </SelectItem>
                    )
                  })}
                </SelectContent>
              </Select>
            )}

            {selectedDoc && hasDocuments && (
              <div className="flex items-center gap-2 px-3 py-2 bg-slate-50 border border-slate-100 rounded-lg text-[11px] text-slate-500">
                <span className="font-semibold text-slate-700">Selected:</span>
                <span className="truncate">{selectedDoc.filename}</span>
                <span className="text-slate-400">•</span>
                <span>{formatDocRoleBadge(selectedDoc.document_role, selectedDoc.filename)}</span>
              </div>
            )}
          </div>

          {createMutation.isError && (
            <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-xs text-red-700 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>Failed to start workflow. Please check your document and try again.</span>
            </div>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-3 pt-2">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={createMutation.isPending}
            className="px-4 py-2.5 border border-slate-200 hover:border-slate-300 hover:bg-slate-50 text-slate-700 text-xs font-semibold rounded-lg transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => createMutation.mutate()}
            disabled={!canSubmit}
            className={cn(
              'inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-xs font-semibold rounded-lg shadow-sm transition-all cursor-pointer',
              (!canSubmit || createMutation.isPending) && 'opacity-60 cursor-not-allowed'
            )}
          >
            {createMutation.isPending ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Starting workflow…</span>
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5 fill-current stroke-[1.5]" />
                <span>Start workflow</span>
              </>
            )}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

