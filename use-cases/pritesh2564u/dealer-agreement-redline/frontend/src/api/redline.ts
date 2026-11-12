import type {
    AnalyzeResponse,
    ApplyResponse,
    DecisionResponse,
    RedlineReview,
} from "../types/redline";

const API_BASE_URL = "http://localhost:8000";

async function handleResponse<T>(response: Response): Promise<T> {
    if (!response.ok) {
        let message = `Request failed with status ${response.status}`;

        try {
            const data = await response.json();

            if (data.detail) {
                message = data.detail;
            }
        } catch {
            // Keep default error message.
        }

        throw new Error(message);
    }

    return response.json() as Promise<T>;
}

export async function analyzeRedline(
    dealerFile: File,
    masterFile: File,
    playbookFile: File,
): Promise<AnalyzeResponse> {
    const formData = new FormData();

    formData.append("dealer_file", dealerFile);

    formData.append("master_file", masterFile);

    formData.append("playbook_file", playbookFile);

    const response = await fetch(`${API_BASE_URL}/redline/analyze`, {
        method: "POST",
        body: formData,
    });

    return handleResponse<AnalyzeResponse>(response);
}

export async function getRedlineReview(
    reviewId: string,
): Promise<RedlineReview> {
    const response = await fetch(`${API_BASE_URL}/redline/reviews/${reviewId}`);

    return handleResponse<RedlineReview>(response);
}

export async function decideFinding(
    reviewId: string,
    findingId: string,
    decision: "approve" | "reject",
): Promise<DecisionResponse> {
    const response = await fetch(
        `${API_BASE_URL}/redline/reviews/${reviewId}/findings/${findingId}/decision`,
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
            },
            body: JSON.stringify({
                decision,
            }),
        },
    );

    return handleResponse<DecisionResponse>(response);
}

export async function applyReview(reviewId: string): Promise<ApplyResponse> {
    const response = await fetch(
        `${API_BASE_URL}/redline/reviews/${reviewId}/apply`,
        {
            method: "POST",
        },
    );

    return handleResponse<ApplyResponse>(response);
}

export async function exportReview(reviewId: string): Promise<Blob> {
    const response = await fetch(
        `${API_BASE_URL}/redline/reviews/${reviewId}/export`,
        {
            method: "POST",
        },
    );

    if (!response.ok) {
        let message = "Failed to export the document.";

        try {
            const data = await response.json();

            if (data.detail) {
                message = data.detail;
            }
        } catch {
            // Response was not JSON.
        }

        throw new Error(message);
    }

    return response.blob();
}
