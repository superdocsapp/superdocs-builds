const API_BASE = import.meta.env.VITE_API_BASE;

async function apiFetch(path, options = {}) {
    const res = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...options.headers,
        },
    });

    if (!res.ok) {
        const body = await res.text();
        throw new Error(`API error ${res.status}: ${body}`);
    }

    return res.json();
}

export function listClients() {
    return apiFetch("/clients");
}

export function listEngagementsForClient(clientId) {
    return apiFetch(`/engagements/client/${clientId}`);
}

export function generateDocument(type, engagementId) {
    return apiFetch(`/documents/generate/${type}/${engagementId}`, {
        method: "POST",
    });
}

export async function reviewDocument({
    sessionId,
    jobId,
    decisions,
    expectedValues,
}) {
    const res = await fetch(`${API_BASE}/documents/review`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId, jobId, decisions, expectedValues }),
    });

    if (!res.ok) {
        const body = await res.text();
        throw new Error(`API error ${res.status}: ${body}`);
    }

    const contentType = res.headers.get("content-type") || "";

    if (contentType.includes("application/json")) {
        return { isBinary: false, data: await res.json() };
    }

    const blob = await res.blob();
    return { isBinary: true, blob };
}
