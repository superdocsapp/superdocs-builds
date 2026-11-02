export function filterTools<T extends { name: string; description?: string }>(
  tools: readonly T[],
  query: string,
): T[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...tools];
  return tools.filter((tool) => {
    const description = tool.description ?? "";
    return tool.name.toLowerCase().includes(needle) || description.toLowerCase().includes(needle);
  });
}
