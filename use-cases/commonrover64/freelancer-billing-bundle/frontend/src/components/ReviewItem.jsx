import DiffText from "./DiffText.jsx";
import { stripHtml } from "../utils/htmlDiff.js";

function ReviewItem({ change, decision, onApprove, onReject, disabled }) {
    return (
        <div
            className="card"
            style={{
                marginBottom: "1rem",
                borderColor:
                    decision === undefined ? "var(--ink)" : "var(--teal)",
            }}
        >
            {change.isSuspectedBluff && (
                <p style={{ color: "var(--coral)", fontWeight: 700 }}>
                    Warning, this looks like a placeholder, not a real value.
                </p>
            )}
            <div>
                <strong>Before:</strong>{" "}
                <DiffText text={stripHtml(change.old_html)} />
            </div>
            <div>
                <strong>After:</strong>{" "}
                <DiffText text={stripHtml(change.new_html)} />
            </div>
            <div
                style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}
            >
                <button
                    className="btn btn-teal"
                    style={
                        decision === true
                            ? { borderColor: "var(--ink)", borderWidth: "4px" }
                            : {}
                    }
                    onClick={onApprove}
                    disabled={disabled}
                >
                    Approve
                </button>
                <button
                    className="btn"
                    style={
                        decision === false
                            ? {
                                  borderColor: "var(--coral)",
                                  borderWidth: "4px",
                              }
                            : {}
                    }
                    onClick={onReject}
                    disabled={disabled}
                >
                    Reject
                </button>
                {decision === undefined && (
                    <span style={{ color: "var(--coral)", fontWeight: 700 }}>
                        Needs a decision
                    </span>
                )}
            </div>
        </div>
    );
}

export default ReviewItem;
