import React, { useCallback, useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Upload,
  FileText,
  Scale,
  Image as ImageIcon,
  FileCode,
  Check,
  X,
  Loader2,
  AlertCircle,
} from 'lucide-react'

import { documentApi, type DocumentRole } from '@/core/api/documentApi'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { cn } from '@/lib/utils'
import { MAX_FILE_SIZE } from './documentConstants'

interface DocumentUploadModalProps {
  workspaceId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

const DOCUMENT_ROLES: Array<{
  value: DocumentRole
  label: string
  description: string
  accept: string
  Icon: React.ComponentType<{ className?: string }>
  iconColor: string
}> = [
  {
    value: 'product_spec',
    label: 'Product Specification',
    description: 'PDF, Word, or plain text specs',
    accept: '.pdf,.doc,.docx,.txt',
    Icon: FileText,
    iconColor: 'text-blue-600 bg-blue-50 border-blue-100',
  },
  {
    value: 'ruling',
    label: 'Classification Ruling',
    description: 'Prior ruling or legal decision files',
    accept: '.pdf,.doc,.docx,.txt',
    Icon: Scale,
    iconColor: 'text-purple-600 bg-purple-50 border-purple-100',
  },
  {
    value: 'product_image',
    label: 'Product Image',
    description: 'PNG, JPG, JPEG, GIF, or WebP',
    accept: '.jpg,.jpeg,.png,.gif,.webp,image/jpeg,image/png,image/gif,image/webp',
    Icon: ImageIcon,
    iconColor: 'text-emerald-600 bg-emerald-50 border-emerald-100',
  },
  {
    value: 'other',
    label: 'Other Document',
    description: 'Supporting reference materials',
    accept: '.pdf,.doc,.docx,.txt',
    Icon: FileCode,
    iconColor: 'text-slate-600 bg-slate-50 border-slate-200',
  },
]

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`
}

export function DocumentUploadModal({
  workspaceId,
  open,
  onOpenChange,
}: DocumentUploadModalProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [selectedRole, setSelectedRole] = useState<DocumentRole>('product_spec')
  const [validationError, setValidationError] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const queryClient = useQueryClient()

  const currentRole = DOCUMENT_ROLES.find((r) => r.value === selectedRole) ?? DOCUMENT_ROLES[0]

  const uploadMutation = useMutation({
    mutationFn: (file: File) => documentApi.upload(workspaceId, file, selectedRole),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents', workspaceId] })
      setSelectedFile(null)
      setValidationError(null)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
      onOpenChange(false)
    },
  })

  const validateAndSetFile = useCallback((file: File) => {
    if (file.size > MAX_FILE_SIZE) {
      setValidationError(`File size exceeds ${MAX_FILE_SIZE / 1024 / 1024}MB limit`)
      setSelectedFile(null)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
      }
      return
    }
    setValidationError(null)
    setSelectedFile(file)
  }, [])

  const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (file) {
      validateAndSetFile(file)
    }
  }

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDragging(false)
    const file = event.dataTransfer.files?.[0]
    if (file) {
      validateAndSetFile(file)
    }
  }

  const handleDragOver = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setIsDragging(false)
  }

  const handleRoleChange = (role: DocumentRole) => {
    setSelectedRole(role)
    setSelectedFile(null)
    setValidationError(null)
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleClose = () => {
    if (uploadMutation.isPending) return
    setSelectedFile(null)
    setValidationError(null)
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (!next ? handleClose() : onOpenChange(next))}>
      <DialogContent className="sm:max-w-xl p-6 sm:p-7 bg-white border border-slate-200 rounded-2xl shadow-xl">
        {/* Header with Icon */}
        <div className="flex items-start gap-4 mb-3">
          <div className="w-11 h-11 rounded-xl bg-blue-50 text-blue-600 border border-blue-100 flex items-center justify-center shrink-0 mt-0.5">
            <Upload className="w-5 h-5 stroke-[2]" />
          </div>

          <DialogHeader className="p-0 text-left space-y-1">
            <DialogTitle className="text-xl font-bold text-slate-900 tracking-tight">
              Upload Document
            </DialogTitle>
            <DialogDescription className="text-sm text-slate-600 leading-relaxed">
              Upload specification sheets, rulings, or product photos to this workspace.
            </DialogDescription>
          </DialogHeader>
        </div>

        <div className="space-y-5 py-2">
          {/* Document Type Selection */}
          <div className="space-y-2">
            <label className="block text-xs font-semibold text-slate-800 tracking-wide">
              Document Type
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
              {DOCUMENT_ROLES.map((role) => {
                const isSelected = selectedRole === role.value
                const RoleIcon = role.Icon
                return (
                  <button
                    key={role.value}
                    type="button"
                    onClick={() => handleRoleChange(role.value)}
                    disabled={uploadMutation.isPending}
                    className={cn(
                      'relative text-left p-3 rounded-xl border transition-all duration-150 flex items-start gap-3 cursor-pointer',
                      isSelected
                        ? 'border-blue-600 bg-blue-50/50 ring-1 ring-blue-600/30'
                        : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/50'
                    )}
                  >
                    <div
                      className={cn(
                        'w-8 h-8 rounded-lg border flex items-center justify-center shrink-0 mt-0.5',
                        role.iconColor
                      )}
                    >
                      <RoleIcon className="w-4 h-4" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between">
                        <p className="text-xs font-bold text-slate-900 leading-tight">
                          {role.label}
                        </p>
                        {isSelected && (
                          <span className="w-4 h-4 rounded-full bg-blue-600 text-white flex items-center justify-center shrink-0">
                            <Check className="w-2.5 h-2.5 stroke-[3]" />
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-slate-500 mt-0.5 leading-tight line-clamp-1">
                        {role.description}
                      </p>
                    </div>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Drag & Drop Zone */}
          <div className="space-y-2">
            <label className="block text-xs font-semibold text-slate-800 tracking-wide">
              File Selection
            </label>

            {!selectedFile ? (
              <div
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onClick={() => fileInputRef.current?.click()}
                className={cn(
                  'border-2 border-dashed rounded-2xl p-6 text-center cursor-pointer transition-all duration-150 flex flex-col items-center justify-center',
                  isDragging
                    ? 'border-blue-500 bg-blue-50/60'
                    : 'border-slate-200 hover:border-slate-300 bg-slate-50/50 hover:bg-slate-50'
                )}
              >
                <div className="w-10 h-10 rounded-xl bg-white border border-slate-200/80 shadow-xs flex items-center justify-center mb-2.5 text-slate-500">
                  <Upload className="w-5 h-5 stroke-[1.75]" />
                </div>
                <p className="text-xs font-semibold text-slate-800">
                  Click to browse <span className="font-normal text-slate-500">or drag and drop file here</span>
                </p>
                <p className="text-[11px] text-slate-400 mt-1">
                  Supports {currentRole.accept.replace(/\./g, ' ').toUpperCase()} (Max 50MB)
                </p>

                <input
                  ref={fileInputRef}
                  type="file"
                  accept={currentRole.accept}
                  onChange={handleFileChange}
                  className="hidden"
                  disabled={uploadMutation.isPending}
                />
              </div>
            ) : (
              <div className="flex items-center justify-between p-3.5 bg-slate-50 border border-slate-200 rounded-xl">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-9 h-9 rounded-lg bg-blue-50 text-blue-600 border border-blue-100 flex items-center justify-center shrink-0">
                    <FileText className="w-4 h-4 stroke-[2]" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-xs font-bold text-slate-900 truncate">
                      {selectedFile.name}
                    </p>
                    <p className="text-[11px] text-slate-500 mt-0.5">
                      {formatBytes(selectedFile.size)} • {currentRole.label}
                    </p>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    setSelectedFile(null)
                    if (fileInputRef.current) fileInputRef.current.value = ''
                  }}
                  disabled={uploadMutation.isPending}
                  className="w-7 h-7 rounded-lg hover:bg-slate-200 text-slate-400 hover:text-slate-700 flex items-center justify-center transition-colors cursor-pointer"
                  title="Remove file"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            )}
          </div>

          {/* Validation Error Alert */}
          {validationError && (
            <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-xs text-red-700 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>{validationError}</span>
            </div>
          )}

          {/* Mutation Error Alert */}
          {uploadMutation.isError && (
            <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-xs text-red-700 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 shrink-0" />
              <span>Upload failed. Please check the file format and try again.</span>
            </div>
          )}
        </div>

        <DialogFooter className="gap-2 sm:gap-3 pt-2">
          <button
            type="button"
            onClick={handleClose}
            disabled={uploadMutation.isPending}
            className="px-4 py-2.5 border border-slate-200 hover:border-slate-300 hover:bg-slate-50 text-slate-700 text-xs font-semibold rounded-lg transition-colors cursor-pointer"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => selectedFile && uploadMutation.mutate(selectedFile)}
            disabled={!selectedFile || uploadMutation.isPending}
            className={cn(
              'inline-flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-xs font-semibold rounded-lg shadow-sm transition-all cursor-pointer',
              (!selectedFile || uploadMutation.isPending) && 'opacity-60 cursor-not-allowed'
            )}
          >
            {uploadMutation.isPending ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Uploading…</span>
              </>
            ) : (
              <>
                <Upload className="w-3.5 h-3.5 stroke-[2]" />
                <span>Upload document</span>
              </>
            )}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
