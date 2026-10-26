import {
    uploadDocument,
    requestEdit,
    pollJobUntilReady,
    approveChanges,
    exportDocument,
} from "./superdocsService.js";
import { isBluffedChange } from "./bluffDetector.js";
import { validateCompletion } from "./completionValidator.js";

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

    const pendingChanges =
        job.status === "awaiting_approval" ? job.metadata.pending_changes : [];

    const flaggedChanges = pendingChanges.map((change) => ({
        ...change,
        isSuspectedBluff: isBluffedChange(change),
    }));

    return {
        jobId,
        sessionId,
        status: job.status,
        pendingChanges: flaggedChanges,
    };
}

// expectedValues: array of strings/numbers that must appear in the final
// exported document. Caller passes these from the real data used to build
// the instruction, so we verify against ground truth, not the AI's own claim.
export async function resumeAfterReview({
    sessionId,
    jobId,
    decisions,
    expectedValues = [],
    exportFormat = "docx",
}) {
    await approveChanges({
        sessionId,
        jobId,
        approved: true,
        changes: decisions,
    });

    const job = await pollJobUntilReady({ jobId });

    if (job.status === "failed") {
        throw new Error(`SuperDocs job failed after review: ${job.error}`);
    }

    if (job.status === "awaiting_approval") {
        const nextChanges = job.metadata.pending_changes;
        const anyBluffed = nextChanges.some(isBluffedChange);

        if (anyBluffed) {
            return {
                status: "failed_needs_manual_retry",
                reason: "SuperDocs proposed a placeholder or degraded value after a review round. Session may have lost context. Start a fresh generation instead of continuing this session.",
                pendingChanges: nextChanges,
            };
        }

        return {
            status: "awaiting_approval",
            pendingChanges: nextChanges.map((change) => ({
                ...change,
                isSuspectedBluff: false,
            })),
        };
    }

    // Job says completed. Verify before trusting it.
    const exportResult = await exportDocument({
        sessionId,
        format: exportFormat,
    });

    if (exportResult.isBinary && expectedValues.length > 0) {
        const validation = await validateCompletion(
            exportResult.buffer,
            expectedValues,
        );

        if (!validation.isComplete) {
            return {
                status: "completed_but_incomplete",
                reason: `Job reported completed, but the exported document is missing: ${validation.missing.join(", ")}`,
                exportResult,
            };
        }
    }

    return {
        status: "completed",
        exportResult,
    };
}
