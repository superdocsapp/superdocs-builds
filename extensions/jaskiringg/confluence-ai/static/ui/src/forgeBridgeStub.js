export async function invoke(action, payload) {
  const r = await fetch(`/api/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

export async function view() {
  return {
    getContext: async () => ({
      extension: {
        content: { id: localStorage.getItem("pageId") || "demo-page" },
        space: { id: localStorage.getItem("spaceId") || "demo-space" },
      },
    }),
  };
}
