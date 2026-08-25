const API_URL = "http://localhost:5000";

/**
 * Upload a document through our backend -> SuperDocs API
 */
export async function uploadDocument(file, sessionId) {
  const formData = new FormData();

  formData.append("document", file);
  formData.append("session_id", sessionId);

  const response = await fetch(`${API_URL}/api/superdocs/upload`, {
    method: "POST",
    body: formData,
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(
      data.message || "Failed to upload document to SuperDocs"
    );
  }

  return data;
}

/**
 * Ask SuperDocs to generate/update the impact report.
 */
export async function generateReport({
  sessionId,
  documentHtml = "",
  message,
}) {
  const response = await fetch(`${API_URL}/api/superdocs/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      session_id: sessionId,
      document_html: documentHtml,
      message,
      approval_mode: "ask_every_time",
    }),
  });

  const data = await response.json();

  if (!response.ok) {
    throw new Error(
      data.message || "Failed to generate report"
    );
  }

  return data;
}

/**
 * Get status of an async SuperDocs job.
 */
export async function getJobStatus(jobId) {
  const response = await fetch(
    `${API_URL}/api/superdocs/job/${jobId}`
  );

  const data = await response.json();

  if (!response.ok) {
    throw new Error(
      data.message || "Failed to get job status"
    );
  }

  return data;
}

/**
 * Approve proposed SuperDocs changes.
 */
export async function approveChanges({
  sessionId,
  jobId,
  changes = [],
}) {
  const response = await fetch(
    `${API_URL}/api/superdocs/approve`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        session_id: sessionId,
        job_id: jobId,
        approved: true,
        changes,
      }),
    }
  );

  const data = await response.json();

  if (!response.ok) {
    throw new Error(
      data.message || "Failed to approve changes"
    );
  }

  return data;
}

/**
 * Export the final SuperDocs document.
 */
export async function exportDocument({
  sessionId,
  format = "pdf",
}) {
  const response = await fetch(
    `${API_URL}/api/superdocs/export`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        session_id: sessionId,
        format,
      }),
    }
  );

  if (!response.ok) {
    let message = "Failed to export document";

    try {
      const data = await response.json();
      message = data.message || message;
    } catch {
      // Ignore JSON parsing failure.
    }

    throw new Error(message);
  }

  return response.blob();
}