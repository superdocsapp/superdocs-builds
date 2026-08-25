import { useState } from 'react'
import type { Claim } from '@/core/api/reviewApi'
import { ConfirmDialog } from '@/shared/components/ConfirmDialog'
import { StatusBadge } from '@/shared/components/StatusBadge'
import { TechnicalDetails } from '@/shared/components/TechnicalDetails'
import { Button } from '@/shared/components/ui/button'
import { EditChangeDialog } from './EditChangeDialog'
import { stripHtml } from './superdocsClaim'
import type { SuperDocsChangePayload } from './superdocsClaim'

export interface ChangeInspectorProps {
  claim: Claim
  parsed: SuperDocsChangePayload | null
  onApprove: () => void
  onReject: () => void
  onSaveEdit: (claimId: string, content: string, editedBy?: string) => void | Promise<void>
  user?: { name?: string | null; email?: string | null } | null
  canDecide: boolean
  isApproving: boolean
  isRejecting: boolean
  isSavingEdit?: boolean
  editError?: string | null
  actionError?: string | null
}

function ReadOnlyBlock({ label, value }: { label: string; value?: string }) {
  if (!value) return null

  return (
    <div className="space-y-1">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="whitespace-pre-wrap text-sm text-foreground">{value}</p>
    </div>
  )
}

export function ChangeInspector({
  claim,
  parsed,
  onApprove,
  onReject,
  onSaveEdit,
  user,
  canDecide,
  isApproving,
  isRejecting,
  isSavingEdit = false,
  editError,
  actionError,
}: ChangeInspectorProps) {
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false)
  const [editDialogOpen, setEditDialogOpen] = useState(false)

  const section = parsed?.description ?? claim.source_stage ?? 'Document change'
  const original = parsed?.current_html
    ? stripHtml(parsed.current_html)
    : claim.original_content ?? undefined
  const proposed = parsed?.proposed_html
    ? stripHtml(parsed.proposed_html)
    : claim.content
  const reason = parsed?.description

  const isDecided = ['approved', 'rejected', 'applied', 'rejected_applied'].includes(claim.status)
  const canApprove = canDecide && claim.status !== 'approved' && claim.status !== 'applied'
  const canReject = canDecide && claim.status !== 'rejected' && claim.status !== 'rejected_applied'

  const technicalJson = JSON.stringify(
    {
      id: claim.id,
      claim_type: claim.claim_type,
      content: claim.content,
    },
    null,
    2
  )

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-4 overflow-y-auto p-4">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-sm font-semibold">Change details</h2>
          <StatusBadge status={claim.status} type="claim" />
        </div>

        <ReadOnlyBlock label="Section" value={section} />
        <ReadOnlyBlock label="Original" value={original} />
        <ReadOnlyBlock label="Proposed" value={proposed} />
        {reason && reason !== section && <ReadOnlyBlock label="Reason" value={reason} />}

        {actionError && <p className="text-sm text-destructive">{actionError}</p>}

        <TechnicalDetails copyText={technicalJson} label="View technical details">
          {technicalJson}
        </TechnicalDetails>
      </div>

      <div className="space-y-2 border-t p-4">
        <Button
          type="button"
          className="w-full"
          onClick={onApprove}
          disabled={!canApprove || isApproving || isRejecting}
        >
          {isApproving ? 'Approving…' : 'Approve change'}
        </Button>
        <Button
          type="button"
          variant="outline"
          className="w-full"
          onClick={() => setRejectDialogOpen(true)}
          disabled={!canReject || isApproving || isRejecting}
        >
          {isRejecting ? 'Rejecting…' : 'Reject change'}
        </Button>
        <Button
          type="button"
          variant="ghost"
          className="w-full"
          onClick={() => setEditDialogOpen(true)}
          disabled={!canDecide || isDecided || isSavingEdit}
        >
          Edit change
        </Button>
      </div>

      <EditChangeDialog
        open={editDialogOpen}
        onOpenChange={setEditDialogOpen}
        claim={claim}
        parsed={parsed}
        user={user}
        onSave={async (claimId, content, editedBy) => {
          try {
            await onSaveEdit(claimId, content, editedBy)
            setEditDialogOpen(false)
          } catch {
            // Parent mutation surfaces save errors.
          }
        }}
        isSaving={isSavingEdit}
        saveError={editError}
      />

      <ConfirmDialog
        open={rejectDialogOpen}
        title="Reject this change?"
        description="The workflow will record this change as rejected. You can still review other pending changes."
        confirmLabel="Reject change"
        destructive
        onConfirm={() => {
          setRejectDialogOpen(false)
          onReject()
        }}
        onCancel={() => setRejectDialogOpen(false)}
      />
    </div>
  )
}
