export function humanizeLabel(fieldKey) {
  const leaf = fieldKey.includes('.') ? fieldKey.split('.').pop() : fieldKey
  return leaf
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function formatDate(value) {
  const parsed = new Date(`${value}T00:00:00`)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })
}

function formatNumber(value, fieldKey) {
  const formatted = new Intl.NumberFormat('en-IN').format(value)
  const lowerKey = fieldKey.toLowerCase()
  if (lowerKey.includes('ctc') || lowerKey.includes('salary')) {
    return `₹${formatted}`
  }
  if (lowerKey.includes('notice') || lowerKey.includes('period')) {
    return `${formatted} days`
  }
  return formatted
}

export function formatFieldValue(fieldKey, fieldType, value) {
  if (value === null || value === undefined || value === '') return null
  if (fieldType === 'boolean') return value ? 'Yes' : 'No'
  if (fieldType === 'date') return formatDate(value)
  if (fieldType === 'number') return formatNumber(value, fieldKey)
  return String(value)
}
