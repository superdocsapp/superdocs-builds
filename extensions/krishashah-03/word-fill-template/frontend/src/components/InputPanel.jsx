const PLACEHOLDERS = {
  json: '{"name": "Rahul Patel", "designation": "Software Engineer", "ctc": "8 LPA", "notice_period": 30, "location": "Ahmedabad", "remote": true}',
  csv: 'name,designation,joining_date,ctc,notice_period,location,remote\nRahul Patel,Software Engineer,2026-09-01,8 LPA,30,Ahmedabad,Yes',
  text: 'Create salary structure for Rahul Patel. He is joining on 1 September 2026 as a Software Engineer. His CTC is 8 LPA. His notice period is 30 days. He is based in Ahmedabad and works remotely.',
}

export default function InputPanel({
  inputTypes,
  inputType,
  onInputTypeChange,
  inputContent,
  onInputContentChange,
  onExtract,
  disabled,
}) {
  return (
    <section className="panel">
      <h2>Input Type</h2>
      <div className="input-type-toggle" role="tablist">
        {inputTypes.map((type) => (
          <button
            key={type.value}
            type="button"
            role="tab"
            aria-selected={type.value === inputType}
            className={type.value === inputType ? 'toggle-button toggle-button--active' : 'toggle-button'}
            onClick={() => onInputTypeChange(type.value)}
          >
            {type.label}
          </button>
        ))}
      </div>

      <h2>Input</h2>
      <textarea
        className="input-textarea"
        rows={8}
        placeholder={PLACEHOLDERS[inputType]}
        value={inputContent}
        onChange={(event) => onInputContentChange(event.target.value)}
      />

      <button
        type="button"
        className="primary-button"
        onClick={onExtract}
        disabled={disabled || !inputContent.trim()}
      >
        Extract Information
      </button>
    </section>
  )
}
