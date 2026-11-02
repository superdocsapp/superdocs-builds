import type { FieldError, JsonSchema } from "../shared/types.js";
import { blankDraft, describeSchema, type Draft, type FormField, type FormNode } from "../shared/schema.js";

type SchemaFormProps = {
  schema: JsonSchema;
  draft: Draft;
  onChange: (draft: Draft) => void;
  errors: FieldError[];
};

export function SchemaForm({ schema, draft, onChange, errors }: SchemaFormProps) {
  const node = describeSchema(schema);
  const rootErrors = errors.filter((error) => error.path === "/");
  return (
    <div className="schema-form">
      {rootErrors.map((error) => (
        <p key={error.message} className="field-error" role="alert">
          {error.message}
        </p>
      ))}
      {node.kind === "object" && node.fields.length === 0 ? (
        <p className="muted">This tool takes no arguments.</p>
      ) : (
        <FieldEditor node={node} draft={draft} path="" errors={errors} onChange={onChange} label="arguments" required />
      )}
    </div>
  );
}

function errorsAt(errors: FieldError[], path: string): FieldError[] {
  return errors.filter((error) => error.path === path);
}

function FieldEditor({
  node,
  draft,
  path,
  errors,
  onChange,
  label,
  required,
}: {
  node: FormNode;
  draft: Draft;
  path: string;
  errors: FieldError[];
  onChange: (draft: Draft) => void;
  label: string;
  required: boolean;
}) {
  const id = path || "arguments";
  const ownErrors = path ? errorsAt(errors, path) : [];
  if (node.kind === "object" && draft.kind === "object") {
    return (
      <fieldset className="object-fields">
        {path ? <legend>{label}</legend> : null}
        {node.description ? <p className="field-help">{node.description}</p> : null}
        {ownErrors.map((error) => (
          <p key={error.message} className="field-error" role="alert">
            {error.message}
          </p>
        ))}
        {node.fields.map((field) => (
          <PropertyEditor
            key={field.name}
            field={field}
            draft={draft.values[field.name] ?? blankDraft(field.node, field.required)}
            path={`${path}/${field.name}`}
            errors={errors}
            onChange={(child) => onChange({ kind: "object", values: { ...draft.values, [field.name]: child } })}
          />
        ))}
      </fieldset>
    );
  }
  if (node.kind === "array" && draft.kind === "array") {
    return (
      <div className="array-field">
        <div className="array-head">
          <span className="field-name">{label}</span>
          <button
            type="button"
            onClick={() => onChange({ kind: "array", items: [...draft.items, blankDraft(node.items, true)] })}
          >
            Add item
          </button>
        </div>
        {node.description ? <p className="field-help">{node.description}</p> : null}
        {ownErrors.map((error) => (
          <p key={error.message} className="field-error" role="alert">
            {error.message}
          </p>
        ))}
        {draft.items.length === 0 ? <p className="muted">No items.</p> : null}
        {draft.items.map((item, index) => (
          <div key={`${path}/${index}`} className="array-item">
            <div className="array-head">
              <span className="field-name">Item {index + 1}</span>
              <button
                type="button"
                onClick={() =>
                  onChange({ kind: "array", items: draft.items.filter((_, itemIndex) => itemIndex !== index) })
                }
              >
                Remove
              </button>
            </div>
            <FieldEditor
              node={node.items}
              draft={item}
              path={`${path}/${index}`}
              errors={errors}
              label={`Item ${index + 1}`}
              required
              onChange={(child) =>
                onChange({
                  kind: "array",
                  items: draft.items.map((current, itemIndex) => (itemIndex === index ? child : current)),
                })
              }
            />
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="scalar-field">
      <label htmlFor={id}>
        {label}
        {required ? (
          <span aria-hidden="true">
            {" "}
            *
          </span>
        ) : null}
      </label>
      {node.description ? (
        <p id={`${id}-help`} className="field-help">
          {node.description}
        </p>
      ) : null}
      <ScalarControl
        id={id}
        node={node}
        draft={draft}
        required={required}
        describedBy={node.description ? `${id}-help` : undefined}
        onChange={onChange}
      />
      {"nullable" in node && node.nullable && draft.kind !== "object" && draft.kind !== "array" ? (
        <label className="null-toggle">
          <input
            type="checkbox"
            checked={draft.useNull}
            onChange={(event) => onChange({ ...draft, useNull: event.target.checked })}
          />
          Send null
        </label>
      ) : null}
      {ownErrors.map((error) => (
        <p key={error.message} className="field-error" role="alert">
          {error.message}
        </p>
      ))}
    </div>
  );
}

function PropertyEditor({
  field,
  draft,
  path,
  errors,
  onChange,
}: {
  field: FormField;
  draft: Draft;
  path: string;
  errors: FieldError[];
  onChange: (draft: Draft) => void;
}) {
  return (
    <FieldEditor
      node={field.node}
      draft={draft}
      path={path}
      errors={errors}
      onChange={onChange}
      label={field.name}
      required={field.required}
    />
  );
}

function ScalarControl({
  id,
  node,
  draft,
  required,
  describedBy,
  onChange,
}: {
  id: string;
  node: FormNode;
  draft: Draft;
  required: boolean;
  describedBy?: string;
  onChange: (draft: Draft) => void;
}) {
  if (node.kind === "string" && draft.kind === "string") {
    if (node.enumValues && node.enumValues.length > 0) {
      return (
        <select
          id={id}
          aria-describedby={describedBy}
          value={draft.value}
          disabled={draft.useNull}
          onChange={(event) => onChange({ ...draft, value: event.target.value })}
        >
          <option value="">Select…</option>
          {node.enumValues.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </select>
      );
    }
    const long = (node.maxLength ?? 0) > 240 || (node.description ?? "").length > 180;
    if (long) {
      return (
        <textarea
          id={id}
          aria-describedby={describedBy}
          value={draft.value}
          disabled={draft.useNull}
          rows={4}
          maxLength={node.maxLength}
          onChange={(event) => onChange({ ...draft, value: event.target.value })}
        />
      );
    }
    return (
      <input
        id={id}
        aria-describedby={describedBy}
        value={draft.value}
        disabled={draft.useNull}
        minLength={node.minLength}
        maxLength={node.maxLength}
        onChange={(event) => onChange({ ...draft, value: event.target.value })}
      />
    );
  }
  if (node.kind === "number" && draft.kind === "number") {
    if (node.enumValues && node.enumValues.length > 0) {
      return (
        <select
          id={id}
          aria-describedby={describedBy}
          value={draft.value}
          disabled={draft.useNull}
          onChange={(event) => onChange({ ...draft, value: event.target.value })}
        >
          <option value="">Select…</option>
          {node.enumValues.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </select>
      );
    }
    return (
      <input
        id={id}
        inputMode="decimal"
        aria-describedby={describedBy}
        value={draft.value}
        disabled={draft.useNull}
        onChange={(event) => onChange({ ...draft, value: event.target.value })}
      />
    );
  }
  if (node.kind === "boolean" && draft.kind === "boolean") {
    if (!required) {
      const selected = draft.value === true ? "true" : draft.value === false ? "false" : "unset";
      return (
        <select
          id={id}
          aria-describedby={describedBy}
          value={selected}
          disabled={draft.useNull}
          onChange={(event) => {
            const next = event.target.value;
            onChange({ ...draft, value: next === "true" ? true : next === "false" ? false : "unset" });
          }}
        >
          <option value="unset">Not set</option>
          <option value="true">True</option>
          <option value="false">False</option>
        </select>
      );
    }
    return (
      <input
        id={id}
        type="checkbox"
        aria-describedby={describedBy}
        checked={draft.value === true}
        disabled={draft.useNull}
        onChange={(event) => onChange({ ...draft, value: event.target.checked })}
      />
    );
  }
  if (node.kind === "json" && draft.kind === "json") {
    return (
      <textarea
        id={id}
        aria-describedby={describedBy}
        value={draft.text}
        disabled={draft.useNull}
        rows={6}
        spellCheck={false}
        placeholder="JSON value"
        onChange={(event) => onChange({ ...draft, text: event.target.value })}
      />
    );
  }
  return <p className="field-error">This field cannot be edited in its current state.</p>;
}
