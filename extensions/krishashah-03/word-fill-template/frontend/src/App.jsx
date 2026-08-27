import { useEffect, useMemo, useState } from 'react'

import GapList from './components/GapList.jsx'
import InputPanel from './components/InputPanel.jsx'
import LoadingState from './components/LoadingState.jsx'
import RecordPreview from './components/RecordPreview.jsx'
import ReviewPanel from './components/ReviewPanel.jsx'
import {
  ApiError,
  createDocumentRun,
  extractInput,
  getTemplates,
  reviewDocumentRun,
  validateRecord,
} from './services/api.js'
import { applyChanges } from './services/wordApi.js'

const INPUT_TYPES = [
  { value: 'text', label: 'Natural Language' },
  { value: 'json', label: 'JSON' },
  { value: 'csv', label: 'CSV' },
]

function errorMessage(err, fallback) {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return fallback
}

export default function App() {
  const [templates, setTemplates] = useState([])
  const [templateId, setTemplateId] = useState(null)
  const [templatesError, setTemplatesError] = useState(null)

  const [inputType, setInputType] = useState('text')
  const [inputContent, setInputContent] = useState('')

  const [isExtracting, setIsExtracting] = useState(false)
  const [isApplying, setIsApplying] = useState(false)
  const [error, setError] = useState(null)

  const [result, setResult] = useState(null)
  const [documentRunId, setDocumentRunId] = useState(null)
  const [applySummary, setApplySummary] = useState(null)

  useEffect(() => {
    let cancelled = false

    getTemplates()
      .then((data) => {
        if (cancelled) return
        setTemplates(data)
        if (data.length > 0) setTemplateId(data[0].id)
      })
      .catch((err) => {
        if (cancelled) return
        setTemplatesError(errorMessage(err, 'Could not load templates.'))
      })

    return () => {
      cancelled = true
    }
  }, [])

  const selectedTemplate = useMemo(
    () => templates.find((template) => template.id === templateId) || null,
    [templates, templateId],
  )

  async function handleExtract() {
    if (!templateId) return
    setError(null)
    setIsExtracting(true)
    setApplySummary(null)

    try {
      const extraction = await extractInput({ templateId, inputType, content: inputContent })
      setResult(extraction)

      const run = await createDocumentRun({
        templateId,
        normalizedData: extraction.normalized_data,
        sourceType: extraction.source_type,
        rawData: extraction.raw_data,
      })
      setDocumentRunId(run.id)
    } catch (err) {
      setResult(null)
      setDocumentRunId(null)
      setError(errorMessage(err, 'Something went wrong while extracting information.'))
    } finally {
      setIsExtracting(false)
    }
  }

  async function handleRevalidate(correctedValues) {
    if (!templateId || !result) return
    setError(null)

    const mergedData = { ...result.normalized_data, ...correctedValues }

    try {
      const revalidated = await validateRecord({ templateId, normalizedData: mergedData })
      setResult(revalidated)
    } catch (err) {
      setError(errorMessage(err, 'Could not revalidate the corrected values.'))
    }
  }

  async function handleApply() {
    if (!result) return
    setError(null)
    setIsApplying(true)

    try {
      const { applied, skipped, conditionResults } = await applyChanges(
        result.proposed_changes,
        result.conditions,
      )
      setApplySummary({ applied, skipped, conditionResults })

      if (documentRunId) {
        await reviewDocumentRun(documentRunId, {
          appliedChanges: applied,
          resolvedGaps: {},
          status: skipped.length > 0 ? 'reviewing' : 'completed',
        })
      }
    } catch (err) {
      setError(errorMessage(err, 'Could not apply changes to the Word document.'))
    } finally {
      setIsApplying(false)
    }
  }

  return (
    <div className="app">
      <header className="app-header">
        <h1>AI Document Filler</h1>
      </header>

      <section className="panel">
        <h2>Template</h2>
        {templatesError && <p className="error-text">{templatesError}</p>}
        {selectedTemplate ? (
          <p className="template-name">{selectedTemplate.name}</p>
        ) : (
          !templatesError && <p className="muted-text">Loading templates…</p>
        )}
      </section>

      <InputPanel
        inputTypes={INPUT_TYPES}
        inputType={inputType}
        onInputTypeChange={setInputType}
        inputContent={inputContent}
        onInputContentChange={setInputContent}
        onExtract={handleExtract}
        disabled={!templateId || isExtracting}
      />

      {isExtracting && <LoadingState message="Extracting information…" />}

      {error && <p className="error-text">{error}</p>}

      {result && !isExtracting && (
        <>
          <RecordPreview fields={selectedTemplate?.fields || {}} normalizedData={result.normalized_data} />

          <GapList gaps={result.gaps} onRevalidate={handleRevalidate} />

          <ReviewPanel
            proposedChanges={result.proposed_changes}
            conditions={result.conditions}
            onApply={handleApply}
            isApplying={isApplying}
          />

          {applySummary && (
            <section className="panel">
              <h2>Apply Result</h2>
              <p className="success-text">{applySummary.applied.length} field(s) applied to the document.</p>
              {applySummary.skipped.length > 0 && (
                <p className="warning-text">
                  Skipped (missing or unresolved): {applySummary.skipped.join(', ')}
                </p>
              )}
            </section>
          )}
        </>
      )}
    </div>
  )
}
