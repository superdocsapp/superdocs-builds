import { DocumentUploadModal } from './DocumentUploadModal'

export interface DocumentUploadSheetProps {
  workspaceId: string
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function DocumentUploadSheet(props: DocumentUploadSheetProps) {
  return <DocumentUploadModal {...props} />
}

