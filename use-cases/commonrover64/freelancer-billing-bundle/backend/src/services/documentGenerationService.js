import {
    uploadDocument,
    requestEdit,
    pollJobUntilReady,
    approveChanges,
    exportDocument,
} from "./superdocsService.js";

// step 1: upload the skeleton, ask AI to fill it in, and stop as soon as there are proposed changes. Does NOT approve anything.
// a human reviews job.metadata.pending_changes before calling resumeAfterReview.
export async function startDocumentGeneration({
    sessionId,
    filename,
    skeletonHtml,
    instruction,
}) {
    await uploadDocument({ sessionId, filename, htmlContent: skeletonHtml });

    const jobId = await requestEdit({ sessionId, message: instruction });

    const job = await pollJobUntilReady({ jobId });

    if (job.status === "failed") {
        throw new Error(`SuperDocs job failed: ${job.error}`);
    }

    return {
        jobId,
        sessionId,
        status: job.status,
        pendingChanges:
            job.status === "awaiting_approval"
                ? job.metadata.pending_changes
                : [],
    };
}

// step 2: takes the human's decisions (one approved: true/false per change_id),
// submits them, waits for the job to finish applying, then exports.
export async function resumeAfterReview({
    sessionId,
    jobId,
    decisions,
    exportFormat = "docx",
}) {
    // decisions: array of { change_id, approved }

    await approveChanges({
        sessionId,
        jobId,
        approved: true, // required top-level default; each entry below carries its own real decision
        changes: decisions,
    });

    const job = await pollJobUntilReady({ jobId });

    if (job.status === "failed") {
        throw new Error(`SuperDocs job failed after review: ${job.error}`);
    }

    // if denying a change caused the AI to propose a revision, there will be
    // a new round of pending_changes. Surface that instead of exporting early.
    if (job.status === "awaiting_approval") {
        return {
            status: "awaiting_approval",
            pendingChanges: job.metadata.pending_changes,
        };
    }

    const exportResult = await exportDocument({
        sessionId,
        format: exportFormat,
    });

    return {
        status: "completed",
        exportResult,
    };
}