import { useState } from "react";

type JsonViewProps = {
  value: unknown;
  expandAll?: boolean;
};

export function JsonView({ value, expandAll = false }: JsonViewProps) {
  return (
    <div className="json-view">
      <Node value={value} depth={0} expandAll={expandAll} />
    </div>
  );
}

function Node({ value, depth, expandAll }: { value: unknown; depth: number; expandAll: boolean }) {
  if (value === null) return <span className="json-null">null</span>;
  if (typeof value === "string") return <StringNode text={value} />;
  if (typeof value === "number" || typeof value === "boolean") {
    return <span className={typeof value === "number" ? "json-number" : "json-bool"}>{String(value)}</span>;
  }
  if (Array.isArray(value)) {
    return <Collection open={expandAll || depth < 2} label={`[${value.length}]`} entries={value.map((item, index) => [String(index), item])} depth={depth} expandAll={expandAll} brackets={["[", "]"]} />;
  }
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    return <Collection open={expandAll || depth < 2} label={`{${entries.length}}`} entries={entries} depth={depth} expandAll={expandAll} brackets={["{", "}"]} />;
  }
  return <span>{String(value)}</span>;
}

function Collection({
  open,
  label,
  entries,
  depth,
  expandAll,
  brackets,
}: {
  open: boolean;
  label: string;
  entries: Array<[string, unknown]>;
  depth: number;
  expandAll: boolean;
  brackets: [string, string];
}) {
  if (entries.length === 0) return <span>{brackets[0] + brackets[1]}</span>;
  return (
    <details className="json-block" open={open}>
      <summary>
        {brackets[0]} <span className="json-count">{label}</span>
      </summary>
      <ul>
        {entries.map(([key, child]) => (
          <li key={key}>
            <span className="json-key">{key}</span>
            <Node value={child} depth={depth + 1} expandAll={expandAll} />
          </li>
        ))}
      </ul>
      <span>{brackets[1]}</span>
    </details>
  );
}

function StringNode({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false);
  const limit = 400;
  if (text.length <= limit) return <span className="json-string">{JSON.stringify(text)}</span>;
  return (
    <span className="json-string">
      {JSON.stringify(expanded ? text : `${text.slice(0, limit)}…`)}
      <button type="button" className="text-button" onClick={() => setExpanded((value) => !value)}>
        {expanded ? "Collapse" : `Show all ${text.length.toLocaleString()} characters`}
      </button>
    </span>
  );
}
