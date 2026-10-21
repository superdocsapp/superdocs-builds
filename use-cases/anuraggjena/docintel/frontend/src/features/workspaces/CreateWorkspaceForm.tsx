import React, { useState } from 'react'
import { FileText, Film, Loader2, Check } from 'lucide-react'
import { cn } from '@/lib/utils'
import { Button } from '@/shared/components/ui/button'

export const WORKFLOW_TYPES = [
  {
    value: 'tariff_classification',
    label: 'Tariff Classification',
    description: 'Extract product facts and generate classification memos',
    Icon: FileText,
    iconColor: 'text-blue-600 bg-blue-50 border-blue-100',
  },
  {
    value: 'screenplay',
    label: 'Screenplay Formatting',
    description: 'Review and approve screenplay formatting changes',
    Icon: Film,
    iconColor: 'text-purple-600 bg-purple-50 border-purple-100',
  },
] as const

export type WorkflowTypeValue = (typeof WORKFLOW_TYPES)[number]['value']

interface CreateWorkspaceFormProps {
  onSubmit: (name: string, workflowType: WorkflowTypeValue) => void
  onCancel?: () => void
  isSubmitting?: boolean
  submitLabel?: string
}

export function CreateWorkspaceForm({
  onSubmit,
  onCancel,
  isSubmitting = false,
  submitLabel = 'Create Workspace',
}: CreateWorkspaceFormProps) {
  const [name, setName] = useState('')
  const [workflowType, setWorkflowType] = useState<WorkflowTypeValue>(
    WORKFLOW_TYPES[0].value
  )

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault()
    const trimmedName = name.trim()
    if (!trimmedName || !workflowType) return
    onSubmit(trimmedName, workflowType)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5 pt-1">
      {/* Workspace Name */}
      <div className="space-y-1.5">
        <label
          htmlFor="workspace-name"
          className="block text-xs font-semibold text-slate-800 tracking-wide"
        >
          Workspace name
        </label>
        <input
          id="workspace-name"
          type="text"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="e.g. Tariff E2E Test, Screenplay v1"
          required
          disabled={isSubmitting}
          className="w-full h-10 px-3.5 text-sm bg-white border border-slate-200 rounded-lg placeholder:text-slate-400 text-slate-900 focus:outline-none focus:border-blue-600 focus:ring-1 focus:ring-blue-600 transition-colors disabled:opacity-60 disabled:bg-slate-50"
        />
      </div>

      {/* Workflow Type Selection */}
      <div className="space-y-2">
        <label className="block text-xs font-semibold text-slate-800 tracking-wide">
          Workflow type
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          {WORKFLOW_TYPES.map((type) => {
            const selected = workflowType === type.value
            const TypeIcon = type.Icon
            return (
              <button
                key={type.value}
                type="button"
                disabled={isSubmitting}
                onClick={() => setWorkflowType(type.value)}
                className={cn(
                  'relative rounded-xl border p-3.5 text-left transition-all duration-150 flex flex-col justify-between group',
                  selected
                    ? 'border-blue-600 bg-blue-50/40 ring-1 ring-blue-600/50 shadow-sm'
                    : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50/60'
                )}
              >
                <div className="flex items-start justify-between gap-2 w-full mb-2.5">
                  <div
                    className={cn(
                      'w-8 h-8 rounded-lg flex items-center justify-center border shrink-0',
                      type.iconColor
                    )}
                  >
                    <TypeIcon className="w-4 h-4 stroke-[2]" />
                  </div>
                  {selected && (
                    <div className="w-5 h-5 rounded-full bg-blue-600 text-white flex items-center justify-center shrink-0">
                      <Check className="w-3 h-3 stroke-[3]" />
                    </div>
                  )}
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-900 leading-tight">
                    {type.label}
                  </p>
                  <p className="mt-1 text-xs text-slate-500 leading-relaxed line-clamp-2">
                    {type.description}
                  </p>
                </div>
              </button>
            )
          })}
        </div>
      </div>

      {/* Footer Buttons */}
      <div className="flex items-center justify-end gap-3 pt-3 border-t border-slate-100">
        {onCancel && (
          <Button
            type="button"
            variant="outline"
            onClick={onCancel}
            disabled={isSubmitting}
            className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border-slate-200 hover:bg-slate-50 hover:text-slate-900 rounded-lg h-9 transition-colors"
          >
            Cancel
          </Button>
        )}

        <button
          type="submit"
          disabled={isSubmitting || !name.trim()}
          className="px-4 py-2 text-sm font-semibold text-white bg-blue-600 hover:bg-blue-700 active:bg-blue-800 disabled:opacity-60 disabled:cursor-not-allowed rounded-lg h-9 shadow-sm transition-all duration-150 flex items-center gap-2"
        >
          {isSubmitting ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              <span>Creating...</span>
            </>
          ) : (
            submitLabel
          )}
        </button>
      </div>
    </form>
  )
}

