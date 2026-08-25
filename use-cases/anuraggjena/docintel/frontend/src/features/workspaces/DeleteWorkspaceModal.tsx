import { AlertTriangle, Loader2 } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from '@/shared/components/ui/dialog'
import { Button } from '@/shared/components/ui/button'

interface DeleteWorkspaceModalProps {
  open: boolean
  workspaceName?: string
  isDeleting: boolean
  error?: string | null
  onClose: () => void
  onConfirm: () => void
}

export function DeleteWorkspaceModal({
  open,
  workspaceName = 'this workspace',
  isDeleting,
  error,
  onClose,
  onConfirm,
}: DeleteWorkspaceModalProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!nextOpen && !isDeleting) {
          onClose()
        }
      }}
    >
      <DialogContent className="sm:max-w-md p-6 bg-white border border-slate-200 rounded-xl shadow-lg">
        <div className="flex items-start gap-4">
          <div className="w-11 h-11 rounded-full bg-red-50 text-red-600 border border-red-100 flex items-center justify-center shrink-0 mt-0.5">
            <AlertTriangle className="w-5 h-5 stroke-[2]" />
          </div>

          <div className="flex-1 space-y-2">
            <DialogHeader className="p-0 text-left space-y-1">
              <DialogTitle className="text-lg font-bold text-slate-900 tracking-tight">
                Delete workspace?
              </DialogTitle>
              <DialogDescription className="text-sm text-slate-600 leading-relaxed">
                Are you sure you want to delete{' '}
                <span className="font-semibold text-slate-900">{workspaceName}</span>?
                This action cannot be undone and all associated workflow data will be removed.
              </DialogDescription>
            </DialogHeader>

            {error && (
              <div className="p-3 text-xs text-red-600 bg-red-50 border border-red-100 rounded-lg">
                {error}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-end gap-3 mt-6 pt-2">
          <Button
            type="button"
            variant="outline"
            onClick={onClose}
            disabled={isDeleting}
            className="px-4 py-2 text-sm font-medium text-slate-700 bg-white border-slate-200 hover:bg-slate-50 hover:text-slate-900 rounded-lg h-9 transition-colors"
          >
            Cancel
          </Button>

          <button
            type="button"
            onClick={onConfirm}
            disabled={isDeleting}
            className="px-4 py-2 text-sm font-semibold text-white bg-red-600 hover:bg-red-700 active:bg-red-800 disabled:opacity-60 disabled:cursor-not-allowed rounded-lg h-9 shadow-sm transition-all duration-150 flex items-center gap-2"
          >
            {isDeleting ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                <span>Deleting...</span>
              </>
            ) : (
              'Delete Workspace'
            )}
          </button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
