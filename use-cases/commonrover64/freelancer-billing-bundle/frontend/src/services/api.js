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
