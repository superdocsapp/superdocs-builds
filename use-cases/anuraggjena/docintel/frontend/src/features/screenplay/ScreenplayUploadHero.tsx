import { useState, useRef } from 'react'
import { Upload, FileText, Loader2, Sparkles, Film, AlertCircle } from 'lucide-react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { documentApi } from '@/core/api/documentApi'
import { runsApi } from '@/core/api/workflowApi'
import { useAuth } from '@/core/auth/AuthContext'
import { cn } from '@/lib/utils'

interface ScreenplayUploadHeroProps {
  workspaceId: string
  onWorkflowStarted?: (runId: string) => void
}

export function ScreenplayUploadHero({
  workspaceId,
  onWorkflowStarted,
}: ScreenplayUploadHeroProps) {
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  // Upload & Start Run Mutation
  const uploadAndStartMutation = useMutation({
    mutationFn: async (file: File) => {
      // 1. Upload document
      const doc = await documentApi.upload(workspaceId, file, 'product_spec')
      // 2. Start Screenplay workflow run
      const run = await runsApi.create(workspaceId, {
        workflow_slug: 'screenplay',
        document_id: doc.id,
        created_by: user?.email,
      })
      return run
    },
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: ['runs', workspaceId] })
      void queryClient.invalidateQueries({ queryKey: ['documents', workspaceId] })
      onWorkflowStarted?.(run.id)
    },
    onError: (err: Error) => {
      console.error('Upload & start workflow failed:', err)
      setErrorMessage(err.message || 'Failed to process screenplay. Please try again.')
    },
  })

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      setSelectedFile(file)
      setErrorMessage(null)
    }
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files?.[0]
    if (file) {
      setSelectedFile(file)
      setErrorMessage(null)
    }
  }

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setIsDragging(true)
  }

  const handleDragLeave = () => {
    setIsDragging(false)
  }

  const handleStartProcessing = () => {
    if (selectedFile) {
      uploadAndStartMutation.mutate(selectedFile)
    }
  }

  const isProcessing = uploadAndStartMutation.isPending

  return (
    <div className="max-w-3xl mx-auto py-10 px-4">
      <div className="bg-white border border-slate-200/90 rounded-2xl p-8 sm:p-12 shadow-sm text-center space-y-6">
        {/* Icon */}
        <div className="w-16 h-16 rounded-2xl bg-blue-50 text-blue-600 border border-blue-100 flex items-center justify-center mx-auto shadow-xs">
          <Film className="w-8 h-8 stroke-[1.75]" />
        </div>

        {/* Title & Description */}
        <div className="space-y-2 max-w-lg mx-auto">
          <h2 className="text-2xl font-bold text-slate-900 tracking-tight">
            Screenplay Workspace
          </h2>
          <p className="text-xs sm:text-sm text-slate-600 leading-relaxed">
            Upload your screenplay draft in <span className="font-semibold text-slate-800">.txt, .pdf, or .docx</span>.
            DocIntel will automatically detect scene headings, action, characters, dialogue, parentheticals, and format them into industry standards.
          </p>
        </div>

        {/* Error Alert */}
        {errorMessage && (
          <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-700 flex items-center gap-2 max-w-lg mx-auto text-left">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{errorMessage}</span>
          </div>
        )}

        {/* Drop Zone */}
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={() => fileInputRef.current?.click()}
          className={cn(
            'border-2 border-dashed rounded-xl p-8 max-w-lg mx-auto transition-all cursor-pointer flex flex-col items-center justify-center gap-3',
            isDragging
              ? 'border-blue-500 bg-blue-50/50 scale-[1.01]'
              : selectedFile
              ? 'border-emerald-400 bg-emerald-50/30'
              : 'border-slate-300 bg-slate-50/50 hover:bg-slate-50 hover:border-slate-400'
          )}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,.pdf,.docx,.doc"
            onChange={handleFileChange}
            className="hidden"
          />

          {selectedFile ? (
            <div className="flex items-center gap-3 text-left">
              <div className="w-10 h-10 rounded-lg bg-emerald-100 text-emerald-700 flex items-center justify-center shrink-0">
                <FileText className="w-5 h-5" />
              </div>
              <div>
                <p className="text-xs font-bold text-slate-900 truncate max-w-xs">
                  {selectedFile.name}
                </p>
                <p className="text-[11px] text-slate-500">
                  {(selectedFile.size / 1024).toFixed(1)} KB • Ready to format
                </p>
              </div>
            </div>
          ) : (
            <>
              <div className="w-10 h-10 rounded-xl bg-white border border-slate-200 text-slate-500 flex items-center justify-center shadow-xs">
                <Upload className="w-5 h-5 stroke-[2]" />
              </div>
              <div className="space-y-0.5">
                <p className="text-xs font-bold text-slate-800">
                  Click to browse or drag and drop your screenplay
                </p>
                <p className="text-[11px] text-slate-500">
                  Supported formats: .txt, .pdf, .docx (Max 50MB)
                </p>
              </div>
            </>
          )}
        </div>

        {/* Action Button */}
        <div>
          <button
            type="button"
            onClick={handleStartProcessing}
            disabled={!selectedFile || isProcessing}
            className={cn(
              'inline-flex items-center gap-2 px-6 py-3 bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white text-xs sm:text-sm font-semibold rounded-xl shadow-sm transition-all cursor-pointer',
              (!selectedFile || isProcessing) && 'opacity-50 cursor-not-allowed'
            )}
          >
            {isProcessing ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Parsing & formatting screenplay…</span>
              </>
            ) : (
              <>
                <Sparkles className="w-4 h-4 stroke-[2]" />
                <span>Start Screenplay Formatting</span>
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
