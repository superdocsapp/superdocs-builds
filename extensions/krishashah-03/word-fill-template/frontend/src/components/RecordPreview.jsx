import { formatFieldValue, humanizeLabel } from '../format.js'

export default function RecordPreview({ fields, normalizedData }) {
  const fieldKeys = Object.keys(fields)
  if (fieldKeys.length === 0) return null

  return (
    <section className="panel">
      <h2>Extracted Information</h2>
      <dl className="record-list">
        {fieldKeys.map((fieldKey) => {
          const display = formatFieldValue(fieldKey, fields[fieldKey]?.type, normalizedData[fieldKey])
          return (
            <div className="record-row" key={fieldKey}>
              <dt>{humanizeLabel(fieldKey)}</dt>
              <dd className={display === null ? 'record-value record-value--empty' : 'record-value'}>
                {display === null ? 'Not provided' : display}
              </dd>
            </div>
          )
        })}
      </dl>
    </section>
  )
}
