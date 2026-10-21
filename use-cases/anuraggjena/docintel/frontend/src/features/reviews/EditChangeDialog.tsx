import { useEffect, useMemo, useState } from 'react'
import type { Claim } from '@/core/api/reviewApi'
import { TechnicalDetails } from '@/shared/components/TechnicalDetails'
import { Button } from '@/shared/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/shared/components/ui/dialog'
import { Label } from '@/shared/components/ui/label'
import { stripHtml, type SuperDocsChangePayload } from './superdocsClaim'

type EditableSuperDocsPayload = SuperDocsChangePayload & {
  reviewer_note?: string
}

export interface EditChangeDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  claim: Claim
  parsed: SuperDocsChangePayload | null
  user?: { name?: string | null; email?: string | null } | null
  onSave: (claimId: string, content: string, editedBy?: string) => void
  isSaving?: boolean
  saveError?: string | null
}

const textareaClassName =
  'flex min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50'

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-2">
      <Label>{label}</Label>
      <p className="whitespace-pre-wrap rounded-md border border-input bg-muted/30 px-3 py-2 text-sm text-foreground">
        {value || '—'}
      </p>
    </div>
  )
}

export function EditChangeDialog({
  open,
  onOpenChange,
  claim,
  parsed,
  user,
  onSave,
  isSaving = false,
  saveError,
}: EditChangeDialogProps) {
  const section =
    parsed?.description ?? claim.source_stage ?? 'Document change'

  const [suggested, setSuggested] = useState('')
  const [reason, setReason] = useState('')
  const [reviewerNote, setReviewerNote] = useState('')

  useEffect(() => {
    if (!open) return

    const payload = parsed as EditableSuperDocsPayload | null
    setSuggested(payload?.proposed_html ? stripHtml(payload.proposed_html) : '')
    setReason(payload?.description ?? '')
    setReviewerNote(payload?.reviewer_note ?? '')
  }, [open, claim.id, parsed])

  const original = parsed?.current_html ? stripHtml(parsed.current_html) : ''

  const technicalJson = useMemo(
    () =>
      JSON.stringify(
        {
          claim_type: claim.claim_type,
          claim_id: claim.id,
          content: claim.content,
        },
        null,
        2
      ),
    [claim.claim_type, claim.content, claim.id]
  )

  const handleSave = () => {
    const base = (parsed ?? {}) as EditableSuperDocsPayload
    const payload: EditableSuperDocsPayload = {
      ...base,
      proposed_html: `<p>${suggested}</p>`,
      description: reason,
    }

    const trimmedNote = reviewerNote.trim()
    if (trimmedNote) {
      payload.reviewer_note = trimmedNote
    } else {
      delete payload.reviewer_note
    }

    onSave(claim.id, JSON.stringify(payload), user?.name || user?.email || undefined)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Edit change</DialogTitle>
          <DialogDescription>
            Update the suggested text and reason before approving this change.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-2">
          <ReadOnlyField label="Section" value={section} />
          <ReadOnlyField label="Original text" value={original} />

          <div className="space-y-2">
            <Label htmlFor="edit-change-suggested">Suggested text</Label>
            <textarea
              id="edit-change-suggested"
              value={suggested}
              onChange={(event) => setSuggested(event.target.value)}
              rows={4}
              className={textareaClassName}
              placeholder="Enter the suggested replacement text"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="edit-change-reason">Reason for change</Label>
            <textarea
              id="edit-change-reason"
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              rows={3}
              className={textareaClassName}
              placeholder="Why is this change being proposed?"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="edit-change-reviewer-note">Reviewer note (optional)</Label>
            <textarea
              id="edit-change-reviewer-note"
              value={reviewerNote}
              onChange={(event) => setReviewerNote(event.target.value)}
              rows={2}
              className={textareaClassName}
              placeholder="Add an optional note for other reviewers"
            />
          </div>

          {saveError && <p className="text-sm text-destructive">{saveError}</p>}

          <TechnicalDetails copyText={technicalJson} label="Technical details">
            {technicalJson}
          </TechnicalDetails>
        </div>

        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={isSaving}
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleSave}
            disabled={isSaving || !suggested.trim()}
          >
            {isSaving ? 'Saving…' : 'Save changes'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
