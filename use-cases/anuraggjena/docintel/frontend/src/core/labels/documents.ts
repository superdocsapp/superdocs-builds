const DOCUMENT_ROLE: Record<string, string> = {
  product_spec: 'Product Specification',
  ruling: 'Classification Ruling',
  product_image: 'Product Image',
  other: 'Other',
}

export function formatDocumentRole(role: string): string {
  return DOCUMENT_ROLE[role] ?? role
}
