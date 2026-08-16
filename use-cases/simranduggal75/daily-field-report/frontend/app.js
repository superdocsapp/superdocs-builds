(() => {
  "use strict";

  const form = document.getElementById("intake-form");
  const projectInput = document.getElementById("project");
  const notesInput = document.getElementById("notes");
  const photosInput = document.getElementById("photos");
  const photoPreview = document.getElementById("photo-preview");
  const submitBtn = document.getElementById("submit-btn");

  const statusSection = document.getElementById("status-section");
  const statusMessage = document.getElementById("status-message");
  const statusElapsed = document.getElementById("status-elapsed");

  const errorSection = document.getElementById("error-section");
  const errorMessage = document.getElementById("error-message");
  const errorDismiss = document.getElementById("error-dismiss");

  const reportSection = document.getElementById("report-section");
  const reportMeta = document.getElementById("report-meta");
  const reportBody = document.getElementById("report-body");

  const captionsSection = document.getElementById("captions-section");
  const captionsBody = document.getElementById("captions-body");

  const changesSection = document.getElementById("changes-section");
  const changesBody = document.getElementById("changes-body");
  const changesEmptyHint = document.getElementById("changes-empty-hint");
  const approveBtn = document.getElementById("approve-btn");

  const exportSection = document.getElementById("export-section");
  const exportStatus = document.getElementById("export-status");
  const downloadLink = document.getElementById("download-link");

  // Selected File objects, kept around only for local thumbnail
  // previews (object URLs) - never re-read for upload after submit.
  let selectedFiles = [];
  let currentReportId = null;
  let currentJobId = null;
  let currentPendingChanges = [];
  let elapsedTimerHandle = null;
  let elapsedSeconds = 0;

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value === null || value === undefined ? "" : String(value);
    return div.innerHTML;
  }

  function tryParseJson(value) {
    if (typeof value !== "string") {
      return value;
    }
    try {
      return JSON.parse(value);
    } catch (err) {
      return value;
    }
  }

  function prettify(value) {
    if (value === null || value === undefined || value === "") {
      return "-";
    }
    if (typeof value === "object") {
      return JSON.stringify(value, null, 2);
    }
    return String(value);
  }

  function humanizeCategory(category) {
    if (!category) return "Not categorized";
    return category
      .split("_")
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
  }

  function showError(message) {
    errorMessage.textContent = message;
    errorSection.classList.remove("hidden");
    errorSection.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function clearError() {
    errorSection.classList.add("hidden");
    errorMessage.textContent = "";
  }

  function startStatus(message) {
    statusMessage.textContent = message;
    statusSection.classList.remove("hidden");
    elapsedSeconds = 0;
    statusElapsed.textContent = "0s elapsed";
    if (elapsedTimerHandle) clearInterval(elapsedTimerHandle);
    elapsedTimerHandle = setInterval(() => {
      elapsedSeconds += 1;
      statusElapsed.textContent = `${elapsedSeconds}s elapsed - still processing, not stuck`;
    }, 1000);
  }

  function stopStatus() {
    statusSection.classList.add("hidden");
    if (elapsedTimerHandle) {
      clearInterval(elapsedTimerHandle);
      elapsedTimerHandle = null;
    }
  }

  function resetResultSections() {
    reportSection.classList.add("hidden");
    captionsSection.classList.add("hidden");
    changesSection.classList.add("hidden");
    exportSection.classList.add("hidden");
    reportBody.innerHTML = "";
    reportMeta.innerHTML = "";
    captionsBody.innerHTML = "";
    changesBody.innerHTML = "";
    approveBtn.classList.add("hidden");
    approveBtn.disabled = false;
    downloadLink.classList.add("hidden");
  }

  photosInput.addEventListener("change", () => {
    selectedFiles = Array.from(photosInput.files || []);
    photoPreview.innerHTML = "";
    selectedFiles.forEach((file) => {
      const img = document.createElement("img");
      img.src = URL.createObjectURL(file);
      img.alt = file.name;
      photoPreview.appendChild(img);
    });
  });

  function renderReport(report) {
    const metaParts = [];
    if (report.project) metaParts.push(`<strong>Project:</strong> ${escapeHtml(report.project)}`);
    if (report.report_date) metaParts.push(`<strong>Date:</strong> ${escapeHtml(report.report_date)}`);
    if (report.total_headcount !== null && report.total_headcount !== undefined) {
      metaParts.push(`<strong>Total headcount:</strong> ${escapeHtml(report.total_headcount)}`);
    }
    reportMeta.innerHTML = metaParts.length
      ? `<p>${metaParts.join(" &nbsp;|&nbsp; ")}</p>`
      : `<p class="hint">No project/date/headcount extracted from the notes.</p>`;

    let html = "";

    if (report.manpower && report.manpower.length) {
      html += `<div class="field-block"><h3>Manpower</h3><table>
        <tr><th>Trade</th><th>Headcount</th><th>Notes</th></tr>
        ${report.manpower
          .map(
            (m) =>
              `<tr><td>${escapeHtml(m.trade)}</td><td>${escapeHtml(m.headcount ?? "-")}</td><td>${escapeHtml(m.notes ?? "-")}</td></tr>`
          )
          .join("")}
      </table></div>`;
    }

    if (report.equipment && report.equipment.length) {
      html += `<div class="field-block"><h3>Equipment</h3><table>
        <tr><th>Equipment</th><th>Status</th><th>Notes</th></tr>
        ${report.equipment
          .map(
            (e) =>
              `<tr><td>${escapeHtml(e.equipment)}</td><td>${escapeHtml(e.status ?? "-")}</td><td>${escapeHtml(e.notes ?? "-")}</td></tr>`
          )
          .join("")}
      </table></div>`;
    }

    if (report.work_by_area && report.work_by_area.length) {
      html += `<div class="field-block"><h3>Work by area</h3><table>
        <tr><th>Area</th><th>Work performed</th><th>Status</th></tr>
        ${report.work_by_area
          .map(
            (w) =>
              `<tr><td>${escapeHtml(w.area)}</td><td>${escapeHtml(w.work_performed)}</td><td>${escapeHtml(w.status ?? "-")}</td></tr>`
          )
          .join("")}
      </table></div>`;
    }

    if (report.weather) {
      html += `<div class="field-block"><h3>Weather</h3><p>${escapeHtml(report.weather)}</p></div>`;
    }

    if (report.delays && report.delays.length) {
      html += `<div class="field-block"><h3>Delays</h3><table>
        <tr><th>Description</th><th>Duration</th><th>Cause</th></tr>
        ${report.delays
          .map(
            (d) =>
              `<tr><td>${escapeHtml(d.description)}</td><td>${
                d.duration_hours !== null && d.duration_hours !== undefined
                  ? escapeHtml(d.duration_hours) + "h"
                  : "-"
              }</td><td>${escapeHtml(humanizeCategory(d.cause_category))}</td></tr>`
          )
          .join("")}
      </table></div>`;
    }

    if (report.safety_observations && report.safety_observations.length) {
      html += `<div class="field-block"><h3>Safety observations</h3><ul>
        ${report.safety_observations.map((s) => `<li>${escapeHtml(s)}</li>`).join("")}
      </ul></div>`;
    }

    if (!html) {
      html = `<p class="hint">No structured data was extracted (e.g. a photos-only report).</p>`;
    }

    reportBody.innerHTML = html;
    reportSection.classList.remove("hidden");
  }

  function renderCaptions(captions, files) {
    if (!captions || !captions.length) {
      captionsSection.classList.add("hidden");
      return;
    }

    captionsBody.innerHTML = captions
      .map((caption, index) => {
        const file = files[index];
        const objectUrl = file ? URL.createObjectURL(file) : null;
        const irrelevant = caption
          .toLowerCase()
          .includes("does not depict a construction");
        const badge = irrelevant
          ? `<span class="badge badge-irrelevant">Not construction-related</span>`
          : `<span class="badge badge-relevant">Relevant</span>`;

        return `<div class="caption-item">
          ${objectUrl ? `<img src="${objectUrl}" alt="Site photo ${index + 1}" />` : ""}
          <div class="caption-text">${badge}<div>${escapeHtml(caption)}</div></div>
        </div>`;
      })
      .join("");

    captionsSection.classList.remove("hidden");
  }

  function renderChanges(pendingChanges, jobStatus) {
    currentPendingChanges = pendingChanges || [];

    if (jobStatus !== "awaiting_approval") {
      changesEmptyHint.textContent = `SuperDocs job status: ${jobStatus || "unknown"}. No approval step available.`;
      changesBody.innerHTML = "";
      approveBtn.classList.add("hidden");
      changesSection.classList.remove("hidden");
      return;
    }

    if (!currentPendingChanges.length) {
      changesEmptyHint.textContent = "SuperDocs proposed no changes for this report.";
      changesBody.innerHTML = "";
      approveBtn.classList.add("hidden");
      changesSection.classList.remove("hidden");
      return;
    }

    changesEmptyHint.textContent = "";

    changesBody.innerHTML = currentPendingChanges
      .map((change) => {
        const changeId = change.change_id ?? "(no change_id)";
        const otherFields = Object.entries(change)
          .filter(([key]) => key !== "change_id")
          .map(([key, value]) => {
            // Proposed-change content can arrive as a JSON-encoded
            // string that needs a second parse before it reads as
            // real fields instead of one opaque blob.
            const parsed = tryParseJson(value);
            return `<div><strong>${escapeHtml(key)}:</strong><pre>${escapeHtml(prettify(parsed))}</pre></div>`;
          })
          .join("");

        return `<div class="change-item">
          <div class="change-id">change_id: ${escapeHtml(changeId)}</div>
          ${otherFields}
        </div>`;
      })
      .join("");

    approveBtn.classList.remove("hidden");
    changesSection.classList.remove("hidden");
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearError();
    resetResultSections();

    const notes = notesInput.value.trim();
    if (!notes && selectedFiles.length === 0) {
      showError("Provide field notes, at least one photo, or both.");
      return;
    }

    const formData = new FormData();
    if (notes) formData.append("notes", notes);
    if (projectInput.value.trim()) formData.append("project", projectInput.value.trim());
    selectedFiles.forEach((file) => formData.append("photos", file));

    submitBtn.disabled = true;
    startStatus("Generating structured report and running SuperDocs AI edit...");

    try {
      const response = await fetch("/api/v1/reports", {
        method: "POST",
        body: formData,
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || `Request failed (${response.status})`);
      }

      currentReportId = data.report_id;
      currentJobId = data.superdocs && data.superdocs.job_id;
      const jobStatus = data.superdocs && data.superdocs.status;
      const pendingChanges =
        (data.superdocs &&
          data.superdocs.job &&
          data.superdocs.job.metadata &&
          data.superdocs.job.metadata.pending_changes) ||
        [];

      renderReport(data.report);
      renderCaptions(data.photo_captions, selectedFiles);
      renderChanges(pendingChanges, jobStatus);
    } catch (err) {
      showError(err.message || "Unable to generate the report.");
    } finally {
      stopStatus();
      submitBtn.disabled = false;
    }
  });

  approveBtn.addEventListener("click", async () => {
    if (!currentReportId || !currentJobId) {
      showError("Missing report/job information - regenerate the report first.");
      return;
    }

    clearError();
    approveBtn.disabled = true;
    startStatus("Approving changes and exporting the PDF...");

    try {
      const response = await fetch(`/api/v1/reports/${currentReportId}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          job_id: currentJobId,
          changes: currentPendingChanges,
        }),
      });

      const data = await response.json();

      if (!response.ok) {
        throw new Error(data.detail || `Approval failed (${response.status})`);
      }

      exportStatus.textContent = `Export status: ${data.export && data.export.status}. File: ${
        (data.export && data.export.filename) || "unknown"
      }`;
      downloadLink.href = `/api/v1/reports/${currentReportId}/download`;
      downloadLink.classList.remove("hidden");
      exportSection.classList.remove("hidden");
    } catch (err) {
      showError(err.message || "Unable to approve and export the report.");
    } finally {
      stopStatus();
      approveBtn.disabled = false;
    }
  });

  errorDismiss.addEventListener("click", clearError);
})();
