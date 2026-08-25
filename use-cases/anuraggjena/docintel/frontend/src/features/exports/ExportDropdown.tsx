import { useState, useRef, useEffect } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Download, FileCode, FileText, Loader2, AlertCircle } from 'lucide-react'
import { exportApi } from '@/core/api/exportApi'
import { cn } from '@/lib/utils'

export type ExportFormat = 'pdf' | 'docx'

export interface ExportDropdownProps {
  workspaceId: string
  runId?: string
  reviewId?: string | null
  workflowSlug?: string | null
  disabled?: boolean
  className?: string
  buttonClassName?: string
  menuAlign?: 'left' | 'right'
  variant?: 'primary' | 'emerald' | 'outline' | 'ghost'
  size?: 'sm' | 'md'
  onExportStart?: () => void
  onExportSuccess?: (format: ExportFormat) => void
  onExportError?: (error: Error) => void
}

export function ExportDropdown({
  workspaceId,
  runId,
  reviewId,
  workflowSlug,
  disabled = false,
  className,
  buttonClassName,
  menuAlign = 'right',
  variant = 'emerald',
  size = 'md',
  onExportStart,
  onExportSuccess,
  onExportError,
}: ExportDropdownProps) {
  const queryClient = useQueryClient()
  const [isOpen, setIsOpen] = useState(false)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [activeFormat, setActiveFormat] = useState<ExportFormat | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Close dropdown on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false)
      }
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
      document.addEventListener('keydown', handleKeyDown)
    }
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [isOpen])

  const exportMutation = useMutation({
    mutationFn: async (format: ExportFormat) => {
      setActiveFormat(format)
      setErrorMsg(null)
      onExportStart?.()

      if (reviewId && workflowSlug !== 'tariff_classification' && workflowSlug !== 'tariff') {
        const record = await exportApi.create({ review_id: reviewId, format })
        await exportApi.download(record.id, record.filename)
        return { format, filename: record.filename }
      } else if (runId) {
        const result = await exportApi.exportRun(
          workspaceId,
          runId,
          workflowSlug ?? undefined,
          format
        )
        await exportApi.download(result.export_id, result.filename)
        return { format, filename: result.filename }
      } else {
        throw new Error('No review ID or run ID provided for export')
      }
    },
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: ['exports', workspaceId] })
      onExportSuccess?.(data.format)
      setIsOpen(false)
      setActiveFormat(null)
    },
    onError: (err: any) => {
      console.error('Export failed:', err)
      const message = err?.response?.data?.detail || err?.message || 'Export failed. Please try again.'
      setErrorMsg(message)
      onExportError?.(err)
      setActiveFormat(null)
    },
  })

  const handleSelectFormat = (format: ExportFormat) => {
    if (exportMutation.isPending || disabled) return
    setIsOpen(false)
    exportMutation.mutate(format)
  }

  const isExporting = exportMutation.isPending

  // Variant styles
  const variantStyles = {
    emerald:
      'bg-emerald-600 hover:bg-emerald-700 active:bg-emerald-800 text-white shadow-xs',
    primary:
      'bg-blue-600 hover:bg-blue-700 active:bg-blue-800 text-white shadow-xs',
    outline:
      'bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 hover:bg-slate-50 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200 shadow-xs',
    ghost:
      'bg-transparent hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-700 dark:text-slate-200',
  }[variant]

  const sizeStyles = {
    sm: 'px-3 py-1.5 text-xs rounded-lg gap-1.5',
    md: 'px-3.5 py-2 text-xs font-semibold rounded-xl gap-2',
  }[size]

  return (
    <div className={cn('relative inline-block text-left', className)} ref={containerRef}>
      {/* Trigger Button */}
      <button
        type="button"
        disabled={disabled || isExporting}
        onClick={() => setIsOpen((prev) => !prev)}
        className={cn(
          'inline-flex items-center justify-center font-medium transition-colors cursor-pointer select-none disabled:opacity-50 disabled:cursor-not-allowed',
          variantStyles,
          sizeStyles,
          buttonClassName
        )}
        aria-haspopup="true"
        aria-expanded={isOpen}
      >
        {isExporting ? (
          <>
            <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
            <span>Exporting {activeFormat?.toUpperCase() || ''}…</span>
          </>
        ) : (
          <>
            <Download className="w-3.5 h-3.5 shrink-0" />
            <span>Export</span>
            <ChevronDown
              className={cn(
                'w-3.5 h-3.5 opacity-70 transition-transform duration-150',
                isOpen && 'transform rotate-180'
              )}
            />
          </>
        )}
      </button>

      {/* Dropdown Menu */}
      {isOpen && !isExporting && (
        <div
          className={cn(
            'absolute z-50 mt-1.5 min-w-[190px] rounded-xl bg-white dark:bg-slate-900 shadow-xl border border-slate-200/80 dark:border-slate-800 py-1.5 text-slate-700 dark:text-slate-200 text-xs animate-in fade-in-0 zoom-in-95 duration-100',
            menuAlign === 'right' ? 'right-0' : 'left-0'
          )}
          role="menu"
          aria-orientation="vertical"
        >
          <div className="px-3 py-1 text-[10px] font-semibold tracking-wider text-slate-400 dark:text-slate-500 uppercase">
            Select Format
          </div>

          <button
            type="button"
            onClick={() => handleSelectFormat('pdf')}
            className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer group"
            role="menuitem"
          >
            <div className="flex items-center gap-2.5">
              <FileText className="w-4 h-4 text-rose-500 shrink-0" />
              <div>
                <div className="font-semibold text-slate-900 dark:text-slate-100">Export as PDF</div>
                <div className="text-[10px] text-slate-500 dark:text-slate-400">Industry standard .pdf</div>
              </div>
            </div>
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-rose-50 dark:bg-rose-950/50 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900">
              PDF
            </span>
          </button>

          <button
            type="button"
            onClick={() => handleSelectFormat('docx')}
            className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors cursor-pointer group"
            role="menuitem"
          >
            <div className="flex items-center gap-2.5">
              <FileCode className="w-4 h-4 text-blue-500 shrink-0" />
              <div>
                <div className="font-semibold text-slate-900 dark:text-slate-100">Export as DOCX</div>
                <div className="text-[10px] text-slate-500 dark:text-slate-400">Editable Word .docx</div>
              </div>
            </div>
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-blue-50 dark:bg-blue-950/50 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-900">
              DOCX
            </span>
          </button>
        </div>
      )}

      {/* Error Feedback Tooltip / Message */}
      {errorMsg && (
        <div className="absolute right-0 top-full mt-2 z-50 flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs shadow-md whitespace-nowrap">
          <AlertCircle className="w-3.5 h-3.5 shrink-0" />
          <span>{errorMsg}</span>
          <button
            type="button"
            onClick={() => setErrorMsg(null)}
            className="ml-2 text-rose-500 hover:text-rose-700 font-bold"
          >
            ×
          </button>
        </div>
      )}
    </div>
  )
}
