const BACKEND_URL = window.location.origin;

let proposals = [];


// ---------------------------------------------------------
// APP STARTUP
// ---------------------------------------------------------

function startApp() {

    loadProposals();

    const exportButton =
        document.getElementById("exportButton");

    if (exportButton) {

        exportButton.addEventListener(
            "click",
            exportDocument
        );
    }

    const refreshButton =
        document.getElementById("refreshButton");

    if (refreshButton) {

        refreshButton.addEventListener(
            "click",
            loadProposals
        );
    }
}


// ---------------------------------------------------------
// MICROSOFT WORD / BROWSER MODE
// ---------------------------------------------------------

if (typeof Office !== "undefined") {

    Office.onReady(() => {
        startApp();
    });

} else {

    document.addEventListener(
        "DOMContentLoaded",
        startApp
    );
}


// ---------------------------------------------------------
// LOAD PROPOSALS
// ---------------------------------------------------------

async function loadProposals() {

    setStatus("Loading proposals...");

    try {

        const response =
            await fetch(
                `${BACKEND_URL}/review`
            );

        if (!response.ok) {

            throw new Error(
                `Backend returned ${response.status}`
            );
        }

        const data =
            await response.json();

        proposals =
            data.proposals || [];

        renderProposals();

        if (proposals.length === 0) {

            setStatus(
                "No proposed changes requiring review."
            );

        } else {

            setStatus(
                `${proposals.length} proposed change(s) found.`
            );
        }

    } catch (error) {

        console.error(
            "Load proposals error:",
            error
        );

        setStatus(
            "Could not connect to SuperDocs backend."
        );
    }
}


// ---------------------------------------------------------
// RENDER PROPOSALS
// ---------------------------------------------------------

function renderProposals() {

    const container =
        document.getElementById("proposals");

    if (!container) {
        return;
    }

    container.innerHTML = "";

    if (proposals.length === 0) {

        container.innerHTML = `
            <div class="empty">
                No proposed changes requiring review.
            </div>
        `;

        return;
    }

    proposals.forEach(proposal => {

        const card =
            document.createElement("div");

        card.className =
            "proposal";

        const status =
            proposal.status || "pending";

        const alreadyDecided =
            status === "approved" ||
            status === "rejected";

        card.innerHTML = `

            <div class="proposal-header">

                <strong>
                    ${escapeHtml(
                        proposal.clause
                    )}
                </strong>

                <span
                    class="status status-${escapeHtml(status)}"
                    id="status-${proposal.id}"
                >
                    ${escapeHtml(status)}
                </span>

            </div>


            <div class="before">

                <strong>
                    Before
                </strong>

                <p>
                    ${escapeHtml(
                        proposal.before
                    )}
                </p>

            </div>


            <div class="after">

                <strong>
                    After
                </strong>

                <p>
                    ${escapeHtml(
                        proposal.after
                    )}
                </p>

            </div>


            <div class="reason">

                <strong>
                    Reason
                </strong>

                <p>
                    ${escapeHtml(
                        proposal.reason ||
                        "Playbook recommendation"
                    )}
                </p>

            </div>


            <div class="actions">

                <button
                    onclick="approveProposal(${proposal.id})"
                    ${alreadyDecided ? "disabled" : ""}
                >
                    Approve
                </button>


                <button
                    onclick="rejectProposal(${proposal.id})"
                    ${alreadyDecided ? "disabled" : ""}
                >
                    Reject
                </button>

            </div>
        `;

        container.appendChild(card);
    });
}


// ---------------------------------------------------------
// APPROVE
// ---------------------------------------------------------

async function approveProposal(id) {

    await decideProposal(
        id,
        "approved"
    );
}


// ---------------------------------------------------------
// REJECT
// ---------------------------------------------------------

async function rejectProposal(id) {

    await decideProposal(
        id,
        "rejected"
    );
}


// ---------------------------------------------------------
// DECISION
// ---------------------------------------------------------

async function decideProposal(
    id,
    decision
) {

    try {

        const response =
            await fetch(
                `${BACKEND_URL}/decision`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body: JSON.stringify({
                        proposal_id: id,
                        decision: decision
                    })
                }
            );

        if (!response.ok) {

            let errorMessage =
                "Decision failed.";

            try {

                const error =
                    await response.json();

                errorMessage =
                    error.detail ||
                    errorMessage;

            } catch (_) {
                // Ignore JSON parsing errors.
            }

            throw new Error(
                errorMessage
            );
        }

        const data =
            await response.json();


        const index =
            proposals.findIndex(
                proposal =>
                    proposal.id === id
            );


        if (index !== -1) {

            proposals[index] =
                data.proposal;
        }


        renderProposals();


        setStatus(
            `Proposal ${decision}.`
        );

    } catch (error) {

        console.error(
            "Decision error:",
            error
        );

        setStatus(
            error.message ||
            "Could not save decision."
        );
    }
}


// ---------------------------------------------------------
// EXPORT
// ---------------------------------------------------------

async function exportDocument() {

    setStatus(
        "Preparing redlined document..."
    );

    try {

        const response =
            await fetch(
                `${BACKEND_URL}/export`,
                {
                    method: "POST"
                }
            );


        if (!response.ok) {

            let errorMessage =
                "Export failed.";

            try {

                const error =
                    await response.json();

                errorMessage =
                    error.detail ||
                    errorMessage;

            } catch (_) {
                // Ignore JSON parsing errors.
            }

            throw new Error(
                errorMessage
            );
        }


        const blob =
            await response.blob();


        const url =
            window.URL.createObjectURL(
                blob
            );


        const link =
            document.createElement("a");


        link.href =
            url;


        link.download =
            "redlined_contract.docx";


        document.body.appendChild(
            link
        );


        link.click();


        link.remove();


        window.URL.revokeObjectURL(
            url
        );


        setStatus(
            "Redlined contract exported successfully."
        );

    } catch (error) {

        console.error(
            "Export error:",
            error
        );

        setStatus(
            error.message ||
            "Export failed."
        );
    }
}


// ---------------------------------------------------------
// STATUS MESSAGE
// ---------------------------------------------------------

function setStatus(message) {

    const status =
        document.getElementById("status");

    if (status) {

        status.textContent =
            message;
    }
}


// ---------------------------------------------------------
// HTML ESCAPING
// ---------------------------------------------------------

function escapeHtml(value) {

    const div =
        document.createElement("div");

    div.textContent =
        value || "";

    return div.innerHTML;
}