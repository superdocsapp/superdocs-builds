/* global Office, Word */

const BACKEND_URL = "http://127.0.0.1:5000";

let initialized = false;

// ============================================================
// STATE
// ============================================================

let approvalInProgress = false;
let rejectionInProgress = false;

let currentSessionId = null;
let currentJobId = null;
let currentDocumentHtml = "";

let currentPendingChanges = [];

/*
 * IDs of the batch that was most recently approved/rejected.
 *
 * SuperDocs may continue returning this same batch while the
 * workflow is transitioning. We ignore it until a genuinely
 * new batch appears.
 */
let lastResolvedChangeIds = [];

let pollingTimer = null;
let pollingInProgress = false;
let pollingAttempts = 0;

const POLL_INTERVAL = 5000;
const MAX_POLL_ATTEMPTS = 120;


// ============================================================
// OFFICE INITIALIZATION
// ============================================================

Office.onReady(function (info) {

    console.log("================================");
    console.log("INSURECRAFT TASKPANE LOADED");
    console.log("Office host:", info.host);
    console.log("================================");

    if (info.host !== Office.HostType.Word) {

        setStatus("Open in Word");

        logActivity(
            "Please open InsureCraft inside Microsoft Word."
        );

        return;
    }

    if (initialized) {
        return;
    }

    if (document.readyState === "loading") {

        document.addEventListener(
            "DOMContentLoaded",
            initializeTaskpane,
            { once: true }
        );

    } else {

        initializeTaskpane();
    }
});


// ============================================================
// INITIALIZATION
// ============================================================

function initializeTaskpane() {

    if (initialized) {
        return;
    }

    initialized = true;

    const buildButton =
        document.getElementById("buildPolicyButton");

    const reviewButton =
        document.getElementById("reviewButton");

    const endorsementButton =
        document.getElementById("endorsementButton");

    const approveButton =
        document.getElementById("approveButton");

    const rejectButton =
        document.getElementById("rejectButton");

    const insertButton =
        document.getElementById("insertButton");

    const exportButton =
        document.getElementById("exportButton");


    if (buildButton) {
        buildButton.onclick = buildPolicy;
    }

    if (reviewButton) {
        reviewButton.onclick = reviewPolicy;
    }

    if (endorsementButton) {
        endorsementButton.onclick = draftEndorsement;
    }

    if (approveButton) {
        approveButton.onclick = approveChanges;
    }

    if (rejectButton) {
        rejectButton.onclick = rejectChanges;
    }

    if (insertButton) {
        insertButton.onclick = insertDocument;
    }

    if (exportButton) {
        exportButton.onclick = exportDocument;
    }


    setStatus("Ready");

    logActivity("InsureCraft ready.");
}


// ============================================================
// UI HELPERS
// ============================================================

function setStatus(message) {

    document
        .querySelectorAll("#statusBadge")
        .forEach(function (badge) {

            badge.textContent = message;
        });
}


function logActivity(message) {

    const activity =
        document.getElementById("activity");

    if (!activity) {
        console.log("Activity:", message);
        return;
    }

    const time =
        new Date().toLocaleTimeString();

    const entry =
        document.createElement("div");

    entry.textContent =
        `[${time}] ${message}`;

    activity.appendChild(entry);

    activity.scrollTop =
        activity.scrollHeight;
}


function escapeHtml(value) {

    if (
        value === null ||
        value === undefined
    ) {
        return "";
    }

    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


function showReviewSection() {

    const section =
        document.getElementById("reviewSection");

    if (section) {
        section.classList.remove("hidden");
    }
}


function showApprovalControls() {

    const controls =
        document.getElementById("approvalControls");

    if (controls) {
        controls.classList.remove("hidden");
    }
}


function hideApprovalControls() {

    const controls =
        document.getElementById("approvalControls");

    if (controls) {
        controls.classList.add("hidden");
    }
}


function showInsertButton() {

    const button =
        document.getElementById("insertButton");

    if (button) {
        button.classList.remove("hidden");
    }
}


function showExportButton() {

    const button =
        document.getElementById("exportButton");

    if (button) {
        button.classList.remove("hidden");
    }
}


function setButtonsDisabled(disabled) {

    document
        .querySelectorAll("button")
        .forEach(function (button) {

            button.disabled = disabled;
        });
}


function setApprovalButtonsDisabled(disabled) {

    const approveButton =
        document.getElementById("approveButton");

    const rejectButton =
        document.getElementById("rejectButton");

    if (approveButton) {
        approveButton.disabled = disabled;
    }

    if (rejectButton) {
        rejectButton.disabled = disabled;
    }
}


function showMessage(
    message,
    type = "info"
) {

    const reviewMessage =
        document.getElementById("reviewMessage");

    if (reviewMessage) {

        reviewMessage.textContent = message;

        reviewMessage.className =
            `message ${type}`;
    }

    logActivity(message);
}


// ============================================================
// WORD HELPERS
// ============================================================

async function getWordDocumentHtml() {

    return Word.run(async function (context) {

        const body =
            context.document.body;

        const htmlResult =
            body.getHtml();

        await context.sync();

        const html =
            htmlResult.value;

        if (!html) {

            throw new Error(
                "Could not read HTML from the Word document."
            );
        }

        return html;
    });
}


async function insertHtmlIntoWord(html) {

    if (
        !html ||
        !html.trim()
    ) {

        throw new Error(
            "No document HTML was provided."
        );
    }

    await Word.run(async function (context) {

        const body =
            context.document.body;

        body.insertHtml(
            html,
            Word.InsertLocation.replace
        );

        await context.sync();
    });
}


// ============================================================
// HTTP
// ============================================================

async function parseBackendResponse(response) {

    const text =
        await response.text();

    let data;

    try {

        data =
            text
                ? JSON.parse(text)
                : {};

    } catch {

        data = {
            raw: text
        };
    }


    if (!response.ok) {

        let message =
            `Backend error ${response.status}`;

        if (data && data.detail) {

            if (Array.isArray(data.detail)) {

                message +=
                    ": " +
                    data.detail
                        .map(function (item) {
                            return (
                                item.msg ||
                                JSON.stringify(item)
                            );
                        })
                        .join(", ");

            } else {

                message +=
                    `: ${data.detail}`;
            }

        } else if (data && data.raw) {

            message +=
                `: ${data.raw}`;
        }

        throw new Error(message);
    }

    return data;
}


// ============================================================
// POLICY VALIDATION
// ============================================================

function validatePolicy(payload) {

    const fields = [

        ["Named Insured", payload.named_insured],

        ["Policy Number", payload.policy_number],

        ["Territory", payload.territory],

        ["Liability Limit", payload.liability_limit],

        ["Deductible", payload.deductible]
    ];


    for (const [name, value] of fields) {

        if (
            !value ||
            !String(value).trim()
        ) {

            throw new Error(
                `${name} is required.`
            );
        }
    }
}


// ============================================================
// BUILD POLICY
// ============================================================

async function buildPolicy() {

    try {

        stopPolling();

        setButtonsDisabled(true);

        setStatus("Building...");

        logActivity(
            "Building insurance policy..."
        );


        const coverageForms =
            Array.from(
                document.querySelectorAll(
                    'input[name="coverage"]:checked'
                )
            ).map(function (checkbox) {

                return checkbox.value;
            });


        const endorsements =
            Array.from(
                document.querySelectorAll(
                    'input[name="endorsement"]:checked'
                )
            ).map(function (checkbox) {

                return checkbox.value;
            });


        const payload = {

            named_insured:
                document
                    .getElementById("namedInsured")
                    .value
                    .trim(),

            policy_number:
                document
                    .getElementById("policyNumber")
                    .value
                    .trim(),

            territory:
                document
                    .getElementById("territory")
                    .value
                    .trim(),

            effective_date:
                document
                    .getElementById("effectiveDate")
                    .value,

            expiry_date:
                document
                    .getElementById("expiryDate")
                    .value,

            liability_limit:
                document
                    .getElementById("liabilityLimit")
                    .value
                    .trim(),

            deductible:
                document
                    .getElementById("deductible")
                    .value
                    .trim(),

            coverage_forms:
                coverageForms,

            endorsements:
                endorsements
        };


        validatePolicy(payload);


        const response =
            await fetch(
                `${BACKEND_URL}/policy/build`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify(payload)
                }
            );


        const result =
            await parseBackendResponse(response);


        if (!result.document_html) {

            throw new Error(
                "Backend did not return document_html."
            );
        }


        currentDocumentHtml =
            result.document_html;


        await insertHtmlIntoWord(
            currentDocumentHtml
        );


        setStatus("Policy built");

        showMessage(
            "Insurance policy built successfully and inserted into Word.",
            "success"
        );


    } catch (error) {

        console.error(
            "Policy build failed:",
            error
        );

        setStatus("Error");

        showMessage(
            `Policy build failed: ${error.message}`,
            "error"
        );

    } finally {

        setButtonsDisabled(false);
    }
}


// ============================================================
// REVIEW POLICY
// ============================================================

async function reviewPolicy() {

    try {

        stopPolling();

        resetReviewState();

        setButtonsDisabled(true);

        hideApprovalControls();

        setStatus("Reading document...");


        const instructionElement =
            document.getElementById(
                "reviewInstruction"
            );


        if (!instructionElement) {

            throw new Error(
                "Review instruction field was not found."
            );
        }


        const instruction =
            instructionElement.value.trim();


        if (!instruction) {

            throw new Error(
                "Please enter a review instruction."
            );
        }


        currentDocumentHtml =
            await getWordDocumentHtml();


        setStatus(
            "Sending to SuperDocs..."
        );


        logActivity(
            "Sending current Word document to SuperDocs..."
        );


        const response =
            await fetch(
                `${BACKEND_URL}/policy/review`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({

                            document_html:
                                currentDocumentHtml,

                            instruction:
                                instruction
                        })
                }
            );


        const result =
            await parseBackendResponse(response);


        console.log(
            "SUPERDOCS REVIEW RESPONSE:",
            result
        );


        currentSessionId =
            result.session_id;

        currentJobId =
            result.job_id;


        if (!currentSessionId) {

            throw new Error(
                "SuperDocs did not return a session ID."
            );
        }


        if (!currentJobId) {

            throw new Error(
                "SuperDocs did not return a job ID."
            );
        }


        showReviewSection();

        hideApprovalControls();

        showMessage(
            "SuperDocs is reviewing the policy..."
        );

        setStatus("Processing...");


        logActivity(
            `SuperDocs job started: ${currentJobId}`
        );


        await pollJob();


    } catch (error) {

        console.error(
            "Review failed:",
            error
        );

        setStatus("Review error");

        showMessage(
            `Review failed: ${error.message}`,
            "error"
        );

    } finally {

        setButtonsDisabled(false);
    }
}


// ============================================================
// RESET REVIEW STATE
// ============================================================

function resetReviewState() {

    approvalInProgress = false;

    rejectionInProgress = false;

    currentSessionId = null;

    currentJobId = null;

    currentPendingChanges = [];

    lastResolvedChangeIds = [];

    pollingAttempts = 0;
}


// ============================================================
// JOB HELPERS
// ============================================================

function findLatestJob(data) {

    if (!data) {
        return null;
    }


    if (
        Array.isArray(data.jobs) &&
        data.jobs.length > 0
    ) {

        if (currentJobId) {

            const matchingJob =
                data.jobs.find(function (job) {

                    return (
                        job &&
                        job.job_id === currentJobId
                    );
                });


            if (matchingJob) {
                return matchingJob;
            }
        }


        return data.jobs[
            data.jobs.length - 1
        ];
    }


    if (data.job) {
        return data.job;
    }


    if (data.job_id) {
        return data;
    }


    return null;
}


function getJobStatus(job) {

    if (!job) {
        return "unknown";
    }


    const statuses = [

        job.status,

        job.job_status,

        job.state,

        job.job_state,

        job.metadata &&
            job.metadata.status,

        job.result &&
            job.result.status
    ];


    for (const value of statuses) {

        if (
            value !== undefined &&
            value !== null &&
            String(value).trim()
        ) {

            return String(value)
                .trim()
                .toLowerCase();
        }
    }


    return "unknown";
}


function getJobProgress(job) {

    if (!job) {
        return 0;
    }


    const progressValues = [

        job.progress,

        job.percentage,

        job.percent_complete,

        job.metadata &&
            job.metadata.progress
    ];


    for (const value of progressValues) {

        if (
            value !== undefined &&
            value !== null &&
            !Number.isNaN(Number(value))
        ) {

            return Number(value);
        }
    }


    return 0;
}


// ============================================================
// PENDING CHANGE HELPERS
// ============================================================

function getPendingChanges(job) {

    return (

        (
            job.metadata &&
            job.metadata.pending_changes
        ) ||

        (
            job.result &&
            job.result.document_changes &&
            job.result.document_changes.pending_changes
        ) ||

        (
            job.document_changes &&
            job.document_changes.pending_changes
        ) ||

        []
    );
}


function getChangeIds(changes) {

    if (!Array.isArray(changes)) {
        return [];
    }


    return changes
        .map(function (change) {

            return (
                change.change_id ||
                change.id ||
                null
            );
        })
        .filter(Boolean);
}


function sameIdSet(idsA, idsB) {

    if (
        !Array.isArray(idsA) ||
        !Array.isArray(idsB)
    ) {
        return false;
    }


    if (
        idsA.length === 0 ||
        idsB.length === 0
    ) {
        return false;
    }


    if (
        idsA.length !== idsB.length
    ) {
        return false;
    }


    const a =
        [...idsA].sort();

    const b =
        [...idsB].sort();


    return a.every(
        function (id, index) {
            return id === b[index];
        }
    );
}


function isPreviouslyResolvedBatch(changes) {

    const ids =
        getChangeIds(changes);


    return sameIdSet(
        ids,
        lastResolvedChangeIds
    );
}


// ============================================================
// POLL INITIAL JOB
// ============================================================

async function pollJob() {

    stopPolling();

    pollingAttempts = 0;

    return new Promise(function (resolve, reject) {

        async function checkJob() {

            if (pollingInProgress) {
                return;
            }


            pollingInProgress = true;

            pollingAttempts++;


            try {

                if (!currentSessionId) {

                    throw new Error(
                        "No SuperDocs session ID available."
                    );
                }


                const url =
                    `${BACKEND_URL}/jobs/${encodeURIComponent(
                        currentSessionId
                    )}`;


                console.log(
                    `[Polling ${pollingAttempts}/${MAX_POLL_ATTEMPTS}] GET ${url}`
                );


                const response =
                    await fetch(url);


                const data =
                    await parseBackendResponse(response);


                const job =
                    findLatestJob(data);


                if (!job) {

                    setStatus(
                        "Waiting for job..."
                    );

                    return;
                }


                if (job.job_id) {

                    currentJobId =
                        job.job_id;
                }


                const status =
                    getJobStatus(job);

                const progress =
                    getJobProgress(job);


                console.log(
                    "JOB STATUS:",
                    status
                );

                console.log(
                    "JOB PROGRESS:",
                    progress
                );


                // --------------------------------------------------------
                // PROCESSING
                // --------------------------------------------------------

                if (
                    status === "pending" ||
                    status === "queued" ||
                    status === "processing" ||
                    status === "running" ||
                    status === "in_progress" ||
                    status === "started"
                ) {

                    setStatus(
                        `SuperDocs processing (${progress}%)`
                    );

                    return;
                }


                // --------------------------------------------------------
                // APPROVAL
                // --------------------------------------------------------

                if (
                    status === "awaiting_approval" ||
                    status === "waiting_for_approval" ||
                    status === "pending_approval"
                ) {

                    const pendingChanges =
                        getPendingChanges(job);


                    if (
                        pendingChanges.length === 0
                    ) {

                        setStatus(
                            "Awaiting SuperDocs..."
                        );

                        return;
                    }


                    /*
                     * If this is an old batch that we already approved
                     * or rejected, do NOT display it again.
                     */
                    if (
                        isPreviouslyResolvedBatch(
                            pendingChanges
                        )
                    ) {

                        console.log(
                            "Old resolved batch detected. Continuing to poll."
                        );

                        setStatus(
                            "SuperDocs processing next stage..."
                        );

                        showMessage(
                            "Approval was accepted. SuperDocs is processing the next stage.",
                            "success"
                        );

                        return;
                    }


                    /*
                     * This is a genuinely new approval batch.
                     */
                    currentPendingChanges =
                        pendingChanges;


                    approvalInProgress = false;

                    rejectionInProgress = false;


                    stopPolling();


                    handlePendingChanges(job);


                    resolve(job);

                    return;
                }


                // --------------------------------------------------------
                // COMPLETED
                // --------------------------------------------------------

                if (
                    status === "completed" ||
                    status === "complete" ||
                    status === "success" ||
                    status === "succeeded"
                ) {

                    stopPolling();

                    handleCompletedJob(job);

                    resolve(job);

                    return;
                }


                // --------------------------------------------------------
                // FAILED
                // --------------------------------------------------------

                if (
                    status === "failed" ||
                    status === "error" ||
                    status === "cancelled" ||
                    status === "canceled"
                ) {

                    stopPolling();

                    reject(
                        new Error(
                            job.error ||
                            job.error_message ||
                            (
                                job.result &&
                                job.result.error
                            ) ||
                            "SuperDocs job failed."
                        )
                    );

                    return;
                }


                if (
                    pollingAttempts >=
                    MAX_POLL_ATTEMPTS
                ) {

                    stopPolling();

                    reject(
                        new Error(
                            "SuperDocs did not finish within 10 minutes."
                        )
                    );
                }


            } catch (error) {

                console.error(
                    "Polling error:",
                    error
                );

                stopPolling();

                reject(error);

            } finally {

                pollingInProgress = false;
            }
        }


        checkJob();


        pollingTimer =
            setInterval(
                checkJob,
                POLL_INTERVAL
            );
    });
}


// ============================================================
// STOP POLLING
// ============================================================

function stopPolling() {

    if (pollingTimer) {

        clearInterval(
            pollingTimer
        );

        pollingTimer = null;
    }

    pollingInProgress = false;
}


// ============================================================
// HANDLE PENDING CHANGES
// ============================================================

function handlePendingChanges(job) {

    currentPendingChanges =
        getPendingChanges(job);


    console.log(
        "Pending changes:",
        currentPendingChanges
    );


    const container =
        document.getElementById(
            "changesContainer"
        );


    if (!container) {
        return;
    }


    container.innerHTML = "";


    if (
        currentPendingChanges.length === 0
    ) {

        container.innerHTML =
            "<p>No pending changes were returned.</p>";

        hideApprovalControls();

        setStatus(
            "Awaiting approval"
        );

        return;
    }


    currentPendingChanges.forEach(
        function (change, index) {

            const card =
                document.createElement("div");


            card.className =
                "change-card";


            card.innerHTML = `

                <h3>
                    Proposed Change ${index + 1}
                </h3>

                <p>
                    <strong>Operation:</strong>
                    ${escapeHtml(
                        change.operation || "edit"
                    )}
                </p>

                ${
                    (
                        change.change_id ||
                        change.id
                    )
                        ? `
                        <p>
                            <strong>Change ID:</strong>
                            ${escapeHtml(
                                change.change_id ||
                                change.id
                            )}
                        </p>
                        `
                        : ""
                }

                <h4>Current wording</h4>

                <pre>${escapeHtml(
                    change.old_html ||
                    change.old_text ||
                    ""
                )}</pre>

                <h4>Proposed wording</h4>

                <pre>${escapeHtml(
                    change.new_html ||
                    change.new_text ||
                    ""
                )}</pre>

                <h4>AI Explanation</h4>

                <p>
                    ${escapeHtml(
                        change.ai_explanation ||
                        change.explanation ||
                        ""
                    )}
                </p>
            `;


            container.appendChild(card);
        }
    );


    showApprovalControls();

    setApprovalButtonsDisabled(false);

    setStatus("Awaiting approval");


    showMessage(
        "SuperDocs has prepared changes for your review.",
        "success"
    );


    logActivity(
        `${currentPendingChanges.length} proposed change(s) require approval.`
    );
}


// ============================================================
// APPROVE
// ============================================================

async function approveChanges() {

    if (approvalInProgress) {
        return;
    }


    if (!currentSessionId) {

        showMessage(
            "No active SuperDocs session.",
            "error"
        );

        return;
    }


    if (!currentJobId) {

        showMessage(
            "No active SuperDocs job.",
            "error"
        );

        return;
    }


    if (
        !currentPendingChanges ||
        currentPendingChanges.length === 0
    ) {

        showMessage(
            "There are no pending changes to approve.",
            "error"
        );

        return;
    }


    approvalInProgress = true;

    setApprovalButtonsDisabled(true);


    try {

        setStatus("Approving...");

        logActivity(
            "Sending approval to SuperDocs..."
        );


        /*
         * Save IDs BEFORE clearing the pending changes.
         */
        const resolvedIds =
            getChangeIds(
                currentPendingChanges
            );


        lastResolvedChangeIds =
            [...resolvedIds];


        console.log(
            "APPROVING CHANGE IDS:",
            lastResolvedChangeIds
        );


        /*
         * Keep the FastAPI request compatible with your
         * current backend.
         */
        const changes =
            currentPendingChanges.map(
                function (change) {

                    return {

                        change_id:
                            change.change_id ||
                            change.id ||
                            null,

                        approved: true,

                        feedback: ""
                    };
                }
            );


        const approvalPayload = {

            session_id:
                currentSessionId,

            job_id:
                currentJobId,

            approved: true,

            changes: changes
        };


        console.log(
            "APPROVAL REQUEST:",
            approvalPayload
        );


        const response =
            await fetch(
                `${BACKEND_URL}/approve`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify(
                            approvalPayload
                        )
                }
            );


        const result =
            await parseBackendResponse(response);


        console.log(
            "APPROVAL RESPONSE:",
            result
        );


        /*
         * CRITICAL:
         *
         * Clear the current batch immediately.
         *
         * Otherwise the polling code will compare the
         * SuperDocs response against the old array and
         * incorrectly treat it as a currently pending batch.
         */
        currentPendingChanges = [];


        hideApprovalControls();


        showMessage(
            result.message ||
            "Approval accepted. SuperDocs is processing the next stage.",
            "success"
        );


        setStatus(
            "Waiting for final document..."
        );


        logActivity(
            "Approval accepted. Waiting for SuperDocs..."
        );


        /*
         * Start a fresh polling cycle.
         */
        await waitForFinalResult();


    } catch (error) {

        console.error(
            "Approval failed:",
            error
        );


        approvalInProgress = false;


        /*
         * Restore approval controls if the API request itself failed.
         */
        setApprovalButtonsDisabled(false);

        showApprovalControls();


        setStatus("Approval error");


        showMessage(
            `Approval failed: ${error.message}`,
            "error"
        );
    }
}


// ============================================================
// REJECT
// ============================================================

async function rejectChanges() {

    if (rejectionInProgress) {
        return;
    }


    if (approvalInProgress) {
        return;
    }


    if (!currentSessionId) {

        showMessage(
            "No active SuperDocs session.",
            "error"
        );

        return;
    }


    if (!currentJobId) {

        showMessage(
            "No active SuperDocs job.",
            "error"
        );

        return;
    }


    if (
        !currentPendingChanges ||
        currentPendingChanges.length === 0
    ) {

        showMessage(
            "There are no pending changes to reject.",
            "error"
        );

        return;
    }


    rejectionInProgress = true;

    setApprovalButtonsDisabled(true);


    try {

        setStatus("Rejecting...");

        logActivity(
            "Rejecting proposed changes..."
        );


        /*
         * Save IDs before clearing the current batch.
         */
        lastResolvedChangeIds =
            getChangeIds(
                currentPendingChanges
            );


        console.log(
            "REJECTED CHANGE IDS:",
            lastResolvedChangeIds
        );


        const changes =
            currentPendingChanges.map(
                function (change) {

                    return {

                        change_id:
                            change.change_id ||
                            change.id ||
                            null,

                        approved: false,

                        feedback: ""
                    };
                }
            );


        const response =
            await fetch(
                `${BACKEND_URL}/approve`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({

                            session_id:
                                currentSessionId,

                            job_id:
                                currentJobId,

                            approved: false,

                            changes: changes
                        })
                }
            );


        const result =
            await parseBackendResponse(response);


        console.log(
            "REJECTION RESPONSE:",
            result
        );


        /*
         * Clear the old batch.
         */
        currentPendingChanges = [];


        hideApprovalControls();


        showMessage(
            result.message ||
            "Changes rejected. SuperDocs is processing the next stage.",
            "success"
        );


        setStatus(
            "Waiting for SuperDocs..."
        );


        await waitForFinalResult();


    } catch (error) {

        console.error(
            "Rejection failed:",
            error
        );


        showApprovalControls();

        setApprovalButtonsDisabled(false);


        setStatus("Rejection error");


        showMessage(
            `Rejection failed: ${error.message}`,
            "error"
        );


    } finally {

        rejectionInProgress = false;
    }
}


// ============================================================
// FINAL POLLING AFTER APPROVAL / REJECTION
// ============================================================

async function waitForFinalResult() {

    stopPolling();

    pollingAttempts = 0;

    pollingInProgress = false;


    return new Promise(function (resolve, reject) {

        async function check() {

            if (pollingInProgress) {
                return;
            }


            pollingInProgress = true;

            pollingAttempts++;


            try {

                if (!currentSessionId) {

                    throw new Error(
                        "No active SuperDocs session."
                    );
                }


                const url =
                    `${BACKEND_URL}/jobs/${encodeURIComponent(
                        currentSessionId
                    )}`;


                console.log(
                    `[Final Poll ${pollingAttempts}/${MAX_POLL_ATTEMPTS}] GET ${url}`
                );


                const response =
                    await fetch(url);


                const data =
                    await parseBackendResponse(response);


                console.log(
                    "FINAL JOB RESPONSE:",
                    data
                );


                const job =
                    findLatestJob(data);


                if (!job) {
                    return;
                }


                if (job.job_id) {

                    currentJobId =
                        job.job_id;
                }


                const status =
                    getJobStatus(job);

                const progress =
                    getJobProgress(job);


                console.log(
                    "FINAL JOB STATUS:",
                    status
                );

                console.log(
                    "FINAL JOB PROGRESS:",
                    progress
                );


                // ========================================================
                // STILL PROCESSING
                // ========================================================

                if (
                    status === "pending" ||
                    status === "queued" ||
                    status === "processing" ||
                    status === "running" ||
                    status === "in_progress" ||
                    status === "started"
                ) {

                    setStatus(
                        `SuperDocs processing (${progress}%)`
                    );

                    return;
                }


                // ========================================================
                // APPROVAL REQUIRED
                // ========================================================

                if (
                    status === "awaiting_approval" ||
                    status === "waiting_for_approval" ||
                    status === "pending_approval"
                ) {

                    const pendingChanges =
                        getPendingChanges(job);


                    console.log(
                        "PENDING CHANGES FROM SUPERDOCS:",
                        pendingChanges
                    );


                    /*
                     * SuperDocs can return the same batch for
                     * several polling cycles after approval.
                     *
                     * We MUST ignore it.
                     */
                    if (
                        isPreviouslyResolvedBatch(
                            pendingChanges
                        )
                    ) {

                        console.log(
                            "Same resolved batch still reported. Continuing to poll..."
                        );


                        setStatus(
                            `SuperDocs processing next stage... ${progress}%`
                        );


                        return;
                    }


                    /*
                     * If there are no changes, keep polling.
                     */
                    if (
                        pendingChanges.length === 0
                    ) {

                        console.log(
                            "Awaiting approval status but no changes returned."
                        );

                        setStatus(
                            "Waiting for SuperDocs..."
                        );

                        return;
                    }


                    /*
                     * A NEW batch has appeared.
                     */
                    console.log(
                        "NEW APPROVAL BATCH DETECTED:",
                        pendingChanges
                    );


                    currentPendingChanges =
                        pendingChanges;


                    /*
                     * This is a new approval cycle, so these
                     * changes are no longer the old resolved batch.
                     */
                    lastResolvedChangeIds = [];


                    approvalInProgress = false;

                    rejectionInProgress = false;


                    stopPolling();


                    handlePendingChanges(job);


                    resolve(job);

                    return;
                }


                // ========================================================
                // COMPLETED
                // ========================================================

                if (
                    status === "completed" ||
                    status === "complete" ||
                    status === "success" ||
                    status === "succeeded"
                ) {

                    stopPolling();


                    approvalInProgress = false;

                    rejectionInProgress = false;


                    handleCompletedJob(job);


                    resolve(job);

                    return;
                }


                // ========================================================
                // FAILED
                // ========================================================

                if (
                    status === "failed" ||
                    status === "error" ||
                    status === "cancelled" ||
                    status === "canceled"
                ) {

                    stopPolling();


                    reject(
                        new Error(
                            job.error ||
                            job.error_message ||
                            (
                                job.result &&
                                job.result.error
                            ) ||
                            "SuperDocs job failed."
                        )
                    );

                    return;
                }


                // ========================================================
                // TIMEOUT
                // ========================================================

                if (
                    pollingAttempts >=
                    MAX_POLL_ATTEMPTS
                ) {

                    stopPolling();


                    reject(
                        new Error(
                            "Timed out waiting for final document."
                        )
                    );
                }


            } catch (error) {

                console.error(
                    "Final polling error:",
                    error
                );


                stopPolling();

                reject(error);


            } finally {

                pollingInProgress = false;
            }
        }


        check();


        pollingTimer =
            setInterval(
                check,
                POLL_INTERVAL
            );
    });
}


// ============================================================
// COMPLETED JOB
// ============================================================

function handleCompletedJob(job) {

    stopPolling();


    const result =
        job.result || {};


    const changes =
        result.document_changes ||
        job.document_changes ||
        {};


    console.log(
        "Completed job result:",
        result
    );


    console.log(
        "Document changes:",
        changes
    );


    if (changes.updated_html) {

        currentDocumentHtml =
            changes.updated_html;
    }


    if (result.updated_html) {

        currentDocumentHtml =
            result.updated_html;
    }


    const message =
        changes.changes_summary ||
        result.response ||
        result.message ||
        "SuperDocs completed successfully.";


    currentPendingChanges = [];

    lastResolvedChangeIds = [];


    approvalInProgress = false;

    rejectionInProgress = false;


    hideApprovalControls();


    if (currentDocumentHtml) {
        showInsertButton();
    }


    showExportButton();


    setStatus("Completed");


    showMessage(
        message,
        "success"
    );


    logActivity(
        "SuperDocs processing completed."
    );
}


// ============================================================
// INSERT DOCUMENT
// ============================================================

async function insertDocument() {

    if (!currentDocumentHtml) {

        showMessage(
            "There is no approved document to insert.",
            "error"
        );

        return;
    }


    try {

        setButtonsDisabled(true);

        setStatus("Inserting...");


        await insertHtmlIntoWord(
            currentDocumentHtml
        );


        setStatus("Inserted");


        showMessage(
            "Approved document inserted into Word.",
            "success"
        );


    } catch (error) {

        console.error(
            "Insert failed:",
            error
        );


        setStatus("Insert error");


        showMessage(
            `Could not insert the document: ${error.message}`,
            "error"
        );


    } finally {

        setButtonsDisabled(false);
    }
}


// ============================================================
// ENDORSEMENT
// ============================================================

async function draftEndorsement() {

    try {

        stopPolling();

        resetReviewState();

        setButtonsDisabled(true);

        setStatus("Reading policy...");


        const endorsementName =
            document
                .getElementById("endorsementName")
                .value
                .trim();


        const amendmentInstruction =
            document
                .getElementById("amendmentInstruction")
                .value
                .trim();


        if (!endorsementName) {

            throw new Error(
                "Endorsement name is required."
            );
        }


        if (!amendmentInstruction) {

            throw new Error(
                "Amendment instruction is required."
            );
        }


        const existingWording =
            await getWordDocumentHtml();


        currentDocumentHtml =
            existingWording;


        logActivity(
            "Sending endorsement request to SuperDocs..."
        );


        const response =
            await fetch(
                `${BACKEND_URL}/endorsement/draft`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({

                            endorsement_name:
                                endorsementName,

                            existing_wording:
                                existingWording,

                            amendment_instruction:
                                amendmentInstruction
                        })
                }
            );


        const result =
            await parseBackendResponse(response);


        console.log(
            "Endorsement response:",
            result
        );


        currentSessionId =
            result.session_id;

        currentJobId =
            result.job_id;


        if (!currentSessionId) {

            throw new Error(
                "SuperDocs did not return a session ID."
            );
        }


        if (!currentJobId) {

            throw new Error(
                "SuperDocs did not return a job ID."
            );
        }


        showReviewSection();

        hideApprovalControls();


        showMessage(
            "SuperDocs is drafting the endorsement..."
        );


        setStatus("Processing...");


        await pollJob();


    } catch (error) {

        console.error(
            "Endorsement failed:",
            error
        );


        setStatus("Error");


        showMessage(
            `Endorsement failed: ${error.message}`,
            "error"
        );


    } finally {

        setButtonsDisabled(false);
    }
}


// ============================================================
// EXPORT
// ============================================================

async function exportDocument() {

    if (!currentSessionId) {

        showMessage(
            "No SuperDocs session available.",
            "error"
        );

        return;
    }


    try {

        setButtonsDisabled(true);

        setStatus("Exporting...");


        const response =
            await fetch(
                `${BACKEND_URL}/export/${encodeURIComponent(
                    currentSessionId
                )}`,
                {
                    method: "POST"
                }
            );


        const result =
            await parseBackendResponse(response);


        console.log(
            "Export result:",
            result
        );


        const url =
            result.url ||
            result.download_url;


        if (!url) {

            throw new Error(
                "Export completed, but no download URL was returned."
            );
        }


        window.open(
            url,
            "_blank"
        );


        setStatus("Exported");


        logActivity(
            "Export request completed."
        );


    } catch (error) {

        console.error(
            "Export failed:",
            error
        );


        setStatus("Export error");


        showMessage(
            `Export failed: ${error.message}`,
            "error"
        );


    } finally {

        setButtonsDisabled(false);
    }
}