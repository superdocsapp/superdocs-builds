const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function request(path, options = {}) {
  let response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: { 'Content-Type': 'application/json' },
      ...options,
    })
  } catch {
    throw new ApiError('Could not reach the backend server. Is it running?', 0)
  }

  const text = await response.text()
  let body = null
  if (text) {
    try {
      body = JSON.parse(text)
    } catch {
      body = null
    }
  }

  if (!response.ok) {
    const message = body?.detail || `Request failed with status ${response.status}.`
    throw new ApiError(typeof message === 'string' ? message : JSON.stringify(message), response.status)
  }

  return body
}

export function getTemplates() {
  return request('/api/templates')
}

export function getTemplate(templateId) {
  return request(`/api/templates/${templateId}`)
}

export function extractInput({ templateId, inputType, content }) {
  return request('/api/extract', {
    method: 'POST',
    body: JSON.stringify({ template_id: templateId, input_type: inputType, content }),
  })
}

export function validateRecord({ templateId, normalizedData }) {
  return request('/api/validate', {
    method: 'POST',
    body: JSON.stringify({ template_id: templateId, normalized_data: normalizedData }),
  })
}

export function createDocumentRun({ templateId, normalizedData, sourceType, rawData }) {
  return request('/api/document-runs', {
    method: 'POST',
    body: JSON.stringify({
      template_id: templateId,
      normalized_data: normalizedData,
      source_type: sourceType,
      raw_data: rawData,
    }),
  })
}

export function getDocumentRun(runId) {
  return request(`/api/document-runs/${runId}`)
}

export function reviewDocumentRun(runId, { appliedChanges, resolvedGaps, status }) {
  return request(`/api/document-runs/${runId}/review`, {
    method: 'POST',
    body: JSON.stringify({
      applied_changes: appliedChanges,
      resolved_gaps: resolvedGaps,
      status,
    }),
  })
}
