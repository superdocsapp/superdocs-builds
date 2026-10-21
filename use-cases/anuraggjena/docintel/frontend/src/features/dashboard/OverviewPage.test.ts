import { describe, expect, it } from 'vitest'

function formatDocRoleBadge(role?: string, filename?: string): string {
  if (role === 'product_image' || (!role && filename?.match(/\.(png|jpg|jpeg|webp)$/i))) {
    return 'Product Image'
  }
  if (role === 'classification_ruling' || role === 'ruling') {
    return 'Classification Ruling'
  }
  if (role === 'product_spec' || role === 'product_specification' || role === 'product') {
    return 'Product Specification'
  }
  if (role) {
    return role
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ')
  }
  return 'Document'
}

function isImageFile(filename: string, role?: string): boolean {
  if (role === 'product_image') return true
  return /\.(png|jpg|jpeg|webp|gif|svg)$/i.test(filename)
}

describe('OverviewPage helper functions', () => {
  it('formats document role badges accurately', () => {
    expect(formatDocRoleBadge('product_image', 'sample.png')).toBe('Product Image')
    expect(formatDocRoleBadge(undefined, 'camera.jpg')).toBe('Product Image')
    expect(formatDocRoleBadge('classification_ruling', 'NY_N324001.pdf')).toBe('Classification Ruling')
    expect(formatDocRoleBadge('ruling', 'ruling.pdf')).toBe('Classification Ruling')
    expect(formatDocRoleBadge('product_spec', 'spec.pdf')).toBe('Product Specification')
    expect(formatDocRoleBadge('custom_role')).toBe('Custom Role')
  })

  it('identifies image files vs document files', () => {
    expect(isImageFile('photo.png')).toBe(true)
    expect(isImageFile('photo.webp')).toBe(true)
    expect(isImageFile('doc.pdf')).toBe(false)
    expect(isImageFile('doc.pdf', 'product_image')).toBe(true)
  })
})
