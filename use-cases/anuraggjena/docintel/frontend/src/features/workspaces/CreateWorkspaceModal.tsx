import { FolderPlus } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'

import {
  CreateWorkspaceForm,
  type WorkflowTypeValue,
} from './CreateWorkspaceForm'

interface CreateWorkspaceModalProps {
  open: boolean
  onClose: () => void
  onCreate: (name: string, workflowType: WorkflowTypeValue) => void
  isSubmitting?: boolean
}

export function CreateWorkspaceModal({
  open,
  onClose,
  onCreate,
  isSubmitting = false,
}: CreateWorkspaceModalProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !isSubmitting) onClose()
      }}
    >
      <DialogContent className="sm:max-w-xl p-6 sm:p-7 bg-white border border-slate-200 rounded-2xl shadow-xl">
        <div className="flex items-start gap-4 mb-4">
          <div className="w-11 h-11 rounded-xl bg-blue-50 text-blue-600 border border-blue-100 flex items-center justify-center shrink-0 mt-0.5">
            <FolderPlus className="w-5 h-5 stroke-[2]" />
          </div>

          <DialogHeader className="p-0 text-left space-y-1">
            <DialogTitle className="text-xl font-bold text-slate-900 tracking-tight">
              Create new workspace
            </DialogTitle>
            <DialogDescription className="text-sm text-slate-600 leading-relaxed">
              Choose a project name and workflow type for your document intelligence workspace.
            </DialogDescription>
          </DialogHeader>
        </div>

        <CreateWorkspaceForm
          key={open ? 'open' : 'closed'}
          onSubmit={onCreate}
          onCancel={onClose}
          isSubmitting={isSubmitting}
        />
      </DialogContent>
    </Dialog>
  )
}

