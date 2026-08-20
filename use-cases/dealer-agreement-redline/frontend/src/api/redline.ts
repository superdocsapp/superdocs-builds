import axios from "axios";

import type {
    AnalyzeResponse,
    ApplyReviewResponse,
    FindingDecisionRequest,
    FindingDecisionResponse,
    RedlineReview,
} from "../types/redline";

const api = axios.create({
    baseURL: "http://localhost:8000",
    headers: {
        "Content-Type": "application/json",
    },
});

export async function analyzeRedline(): Promise<AnalyzeResponse> {
    const response = await api.post<AnalyzeResponse>("/redline/analyze");

    return response.data;
}

export async function getRedlineReview(
    reviewId: string,
): Promise<RedlineReview> {
    const response = await api.get<RedlineReview>(
        `/redline/reviews/${reviewId}`,
    );

    return response.data;
}

export async function decideFinding(
    reviewId: string,
    findingId: string,
    decision: "approve" | "reject",
): Promise<FindingDecisionResponse> {
    const payload: FindingDecisionRequest = {
        decision,
    };

    const response = await api.post<FindingDecisionResponse>(
        `/redline/reviews/${reviewId}/findings/${findingId}/decision`,
        payload,
    );

    return response.data;
}

export async function applyReview(
    reviewId: string,
): Promise<ApplyReviewResponse> {
    const response = await api.post<ApplyReviewResponse>(
        `/redline/reviews/${reviewId}/apply`,
    );

    return response.data;
}

export async function exportReview(reviewId: string): Promise<Blob> {
    const response = await api.get(`/redline/reviews/${reviewId}/export`, {
        responseType: "blob",
    });

    return response.data;
}
