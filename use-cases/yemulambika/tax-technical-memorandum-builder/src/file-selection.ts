export const SYNTHETIC_DOCUMENT_ORDER = [
  "synthetic-client-facts.txt",
  "synthetic-authority-1.txt",
  "synthetic-authority-2.txt",
  "synthetic-tax-memo.html",
] as const;

const expectedNames = new Set<string>(SYNTHETIC_DOCUMENT_ORDER);

export function validateDocumentFiles<T extends { name: string }>(
  files: readonly T[],
) {
  const counts = new Map<string, number>();
  for (const file of files)
    counts.set(file.name, (counts.get(file.name) ?? 0) + 1);

  const missing = SYNTHETIC_DOCUMENT_ORDER.filter((name) => !counts.has(name));
  const duplicate = [...counts.entries()]
    .filter(([name, count]) => expectedNames.has(name) && count > 1)
    .map(([name]) => name)
    .sort();
  const unexpected = [...counts.keys()]
    .filter((name) => !expectedNames.has(name))
    .sort();
  const problems = [
    missing.length ? `Missing: ${missing.join(", ")}` : "",
    duplicate.length ? `Duplicate: ${duplicate.join(", ")}` : "",
    unexpected.length ? `Unexpected: ${unexpected.join(", ")}` : "",
  ].filter(Boolean);

  if (files.length !== SYNTHETIC_DOCUMENT_ORDER.length || problems.length)
    return {
      ok: false as const,
      files: [] as T[],
      message: problems.join("; ") || "Select exactly the four supplied files.",
    };

  const byName = new Map(files.map((file) => [file.name, file]));
  return {
    ok: true as const,
    files: SYNTHETIC_DOCUMENT_ORDER.map((name) => byName.get(name)!),
    message: "",
  };
}
