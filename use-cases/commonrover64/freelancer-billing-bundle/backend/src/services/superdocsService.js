import dotenv from "dotenv";

dotenv.config();

const BASE_URL = "https://api.superdocs.app";
const API_KEY = process.env.SUPERDOCS_API_KEY;

// shared fetch wrapper, adds auth header and throws on non-2xx so callers dont have to check res.ok everywhere

async function superdocsFetch(path, options = {}) {
    const res = await fetch(`${BASE_URL}${path}`, {
        ...options,
        headers: {
            Authorization: `Bearer ${API_KEY}`,
            "Content-Type": "application/json",
            ...options.headers,
        },
    });

    if (!res.ok) {
        const body = await res.text();
        throw new Error(`SuperDocs API error ${res.status}: ${body}`);
    }

    return res.json();
}

//  uploads a starting html doc into a session. this is the "upload" call
export async function uploadDocument({ sessionId, filename, htmlContent }) {
    const fileBase64 = Buffer.from(htmlContent, "utf-8").toString("base64");

    return superdocsFetch("/v1/documents/upload-base64", {
        method: "POST",
        body: JSON.stringify({
            filename,
            file_base64: fileBase64,
            session_id: sessionId,
        }),
    });
}

//  sends an edit instruction with review required. this is the "chat" call, returns a job_id to poll
export async function requestEdit({ sessionId, message }) {
    const result = await superdocsFetch("/v1/chat/async", {
        method: "POST",
        body: JSON.stringify({
            message,
            session_id: sessionId,
            approval_mode: "ask_every_time",
        }),
    });

    return result.job_id;
}

// Polls a job until it's awaiting_approval, completed, or failed.
// Retries with a short delay, since edits can take time per the task doc's own warning.
export async function pollJobUntilReady({
    jobId,
    maxAttempts = 60,
    delayMs = 3000,
}) {
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
        const job = await superdocsFetch(`/v1/jobs/${jobId}`);

        if (
            job.status === "awaiting_approval" ||
            job.status === "completed" ||
            job.status === "failed"
        ) {
            return job;
        }

        await new Promise((resolve) => setTimeout(resolve, delayMs));
    }

    throw new Error(
        `Job ${jobId} did not resolve after ${maxAttempts} attempts`,
    );
}

// approves or decline a batch of pending changes, this is the "approve" call
export async function approveChanges({ sessionId, jobId, approved, changes }) {
    return superdocsFetch(`/v1/chat/${sessionId}/approve`, {
        method: "POST",
        body: JSON.stringify({
            job_id: jobId,
            approved,
            changes,
        }),
    });
}

// exports the session's current document, this is the "export" call
// unlike the other calls, this can return raw file bytes (docx/pdf) instead of JSON
// so we check content-type first instead of always calling res.json()
export async function exportDocument({ sessionId, format = "docx" }) {
    const res = await fetch(`${BASE_URL}/v1/documents/export`, {
        method: "POST",
        headers: {
            Authorization: `Bearer ${API_KEY}`,
            "Content-Type": "application/json",
        },
        body: JSON.stringify({ session_id: sessionId, format }),
    });

    if (!res.ok) {
        const body = await res.text();
        throw new Error(`SuperDocs export error ${res.status}: ${body}`);
    }

    const contentType = res.headers.get("content-type") || "";

    if (contentType.includes("application/json")) {
        return res.json();
    }

    // raw file bytes, wrap in a buffer plus metadata for the route to save or stream
    const buffer = Buffer.from(await res.arrayBuffer());
    const contentDisposition = res.headers.get("content-disposition") || "";

    return {
        isBinary: true,
        buffer,
        contentType,
        contentDisposition,
    };
}
