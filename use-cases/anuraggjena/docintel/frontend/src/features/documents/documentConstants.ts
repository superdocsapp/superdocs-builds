import type { DocumentRole } from '@/core/api/documentApi'

export const MAX_FILE_SIZE = 50 * 1024 * 1024 // 50MB

export const ROLE_OPTIONS: Array<{
  value: DocumentRole
  label: string
  accept: string
  hint: string
}> = [
  {
    value: 'product_spec',
    label: 'Product Specification',
    accept: '.pdf,.doc,.docx,.txt',
    hint: 'PDF, Word, or plain text specification sheets',
  },
  {
    value: 'ruling',
    label: 'Classification Ruling',
    accept: '.pdf,.doc,.docx,.txt',
    hint: 'Prior ruling or decision documents',
  },
  {
    value: 'product_image',
    label: 'Product Image',
    accept: '.jpg,.jpeg,.png,.gif,.webp,image/jpeg,image/png,image/gif,image/webp',
    hint: 'JPEG, PNG, GIF, or WebP product photos',
  },
  {
    value: 'other',
    label: 'Other Document',
    accept: '.pdf,.doc,.docx,.txt',
    hint: 'Supporting reference documents',
  },
]
