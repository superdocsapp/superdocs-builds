import "./styles.css";
import {
  SigmaSuperDocsClient,
  UnsupportedFileResponseError,
  hasSessionApiKey,
  setSessionApiKey,
} from "./api";
import { BrowserRunStateStore } from "./state";
import type { ApprovalDecision, NormalizedJob } from "./types";
import { describeFailure } from "./normalizers";
import { createChangeCard } from "./view";
import { ReviewWorkflow, type Stage, type WorkflowEvent } from "./workflow";
import { ZohoWriterAdapter } from "./writer";

const app = document.querySelector<HTMLElement>("#app");
if (!app) throw new Error("App root not found.");

app.innerHTML = `
  <header class="hero">
    <div class="hero-text">
      <img class="lockup" src="img/superdocs-lockup.png" alt="SuperDocs" width="132" height="40" />
      <h1>Review selected text</h1>
    </div>
    <span id="connection" class="status-dot">Connecting</span>
  </header>

  <details class="panel credentials">
    <summary>SuperDocs API key <span class="hint-inline">optional</span></summary>
    <!--
      Decoys the browser's own password-manager heuristics away from the real
      field below. Chrome/Safari look for something resembling a login form on
      the page and offer to save it as a credential; giving them an unambiguous,
      never-filled, never-submitted one to latch onto is the standard fix for a
      non-password field otherwise being misclassified as one. Off-screen but not
      display:none, since some heuristics ignore fields that never render.
    -->
    <div class="visually-hidden" aria-hidden="true">
      <input type="text" name="username" autocomplete="username" tabindex="-1" />
      <input type="password" name="password" autocomplete="new-password" tabindex="-1" />
    </div>
    <input id="sd-override-value" name="sd-override-value" type="text" class="masked" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" data-1p-ignore data-lpignore="true" data-bwignore data-form-type="other" placeholder="sk_…" />
    <p class="hint">Leave empty to use the Sigma <code>superdocsapi</code> connection. Supply a key only if that connection cannot authenticate. Kept in memory for this session, never written to browser storage, so it is re-entered after a reload.</p>
  </details>

  <section class="panel">
    <label for="instruction">What should change?</label>
    <textarea id="instruction" rows="4" placeholder="Tighten this passage, preserve its meaning and formatting."></textarea>
    <p class="hint">Only the current Writer selection is sent. Every proposal waits for you.</p>
    <button id="start" class="primary">Review with SuperDocs</button>
  </section>

  <ol id="stages" class="stages" aria-label="Workflow progress">
    <li data-stage="reading">Read</li>
    <li data-stage="uploading">Upload</li>
    <li data-stage="polling">Process</li>
    <li data-stage="review">Review</li>
    <li data-stage="complete">Finish</li>
  </ol>

  <section id="activity" class="activity hidden">
    <div class="activity-line"><span class="spinner"></span><span id="activity-text"></span></div>
    <div id="usage" class="usage"></div>
  </section>

  <section id="error" class="error hidden" role="alert">
    <strong>Could not continue</strong>
    <p id="error-text"></p>
    <button id="retry" class="secondary">Resume existing job</button>
  </section>

  <section id="review" class="hidden">
    <div class="section-heading">
      <div><p class="eyebrow">APPROVAL ROUND <span id="round">1</span></p><h2>Proposed changes</h2></div>
      <span id="decision-count" class="counter">0 proposed</span>
    </div>
    <div id="changes"></div>
    <p class="hint">One decision applies to every proposed change in this round.</p>
    <div class="decision-row">
      <button id="reject-all" class="secondary">Reject all</button>
      <button id="accept-all" class="primary">Accept all</button>
    </div>
  </section>

  <section id="continue-panel" class="panel hidden">
    <p class="eyebrow">CONTINUE PROMPT</p>
    <h2>SuperDocs paused this edit</h2>
    <p class="hint">Continue the same job with a fresh step budget, or stop it and keep the server-side work completed so far.</p>
    <button id="continue-job" class="primary">Continue existing job</button>
    <button id="stop-job" class="secondary">Stop here</button>
  </section>

  <section id="finish" class="panel hidden">
    <p class="eyebrow">REVIEW COMPLETE</p>
    <h2>Approved result ready</h2>
    <p class="hint">Turn on <strong>Track Changes</strong> in Writer before applying, and the edit lands as a native tracked change you can accept or reject with Writer's own review controls.</p>
    <button id="apply" class="primary">Apply to the document</button>
    <p id="apply-note" class="hint">Writes only over the passage you reviewed. If the selection has moved, nothing is written. Undo in Writer reverses it.</p>
    <button id="export" class="secondary">Export approved result</button>
  </section>
`;

const get = <T extends HTMLElement>(id: string): T => {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing #${id}`);
  return element as T;
};

const instruction = get<HTMLTextAreaElement>("instruction");
const apiKeyInput = get<HTMLInputElement>("sd-override-value");
const startButton = get<HTMLButtonElement>("start");
const acceptAllButton = get<HTMLButtonElement>("accept-all");
const rejectAllButton = get<HTMLButtonElement>("reject-all");
const retryButton = get<HTMLButtonElement>("retry");
const continueButton = get<HTMLButtonElement>("continue-job");
const stopButton = get<HTMLButtonElement>("stop-job");
const exportButton = get<HTMLButtonElement>("export");
const applyButton = get<HTMLButtonElement>("apply");
const applyNote = get<HTMLElement>("apply-note");
const activity = get<HTMLElement>("activity");
const activityText = get<HTMLElement>("activity-text");
const usage = get<HTMLElement>("usage");
const errorPanel = get<HTMLElement>("error");
const errorText = get<HTMLElement>("error-text");
const reviewPanel = get<HTMLElement>("review");
const continuePanel = get<HTMLElement>("continue-panel");
const finishPanel = get<HTMLElement>("finish");
const changesElement = get<HTMLElement>("changes");
const decisionCount = get<HTMLElement>("decision-count");

const writer = new ZohoWriterAdapter();
const api = new SigmaSuperDocsClient();
const stateStore = new BrowserRunStateStore();
let workflow: ReviewWorkflow;
let sessionId = "";
let currentJob: NormalizedJob | undefined;
let round = 1;
let currentStage: Stage = "reading";
let errorGeneration = 0;

const setHidden = (element: HTMLElement, hidden: boolean) =>
  element.classList.toggle("hidden", hidden);

const setBusy = (busy: boolean) => {
  startButton.disabled = busy;
  acceptAllButton.disabled = busy;
  rejectAllButton.disabled = busy;
  continueButton.disabled = busy;
  stopButton.disabled = busy;
  exportButton.disabled = busy;
  applyButton.disabled = busy;
};

// Sigma can reject with nothing but {message:"failed"}, so two probes narrow it
// down: one through the named connection, one without any connection at all.
const appendConnectionDiagnosis = async (generation: number) => {
  try {
    await api.checkConnection();
    if (generation !== errorGeneration) return;
    errorText.textContent += hasSessionApiKey()
      ? " An authenticated probe succeeded, so the request payload is the likely cause."
      : " The superdocsapi connection responded, so the request payload is the likely cause.";
    return;
  } catch {
    // Fall through to the transport probe.
  }

  try {
    await api.checkTransport();
    if (generation !== errorGeneration) return;
    errorText.textContent += hasSessionApiKey()
      ? " Sigma reached SuperDocs unauthenticated, but the authenticated request failed." +
        " Check that the key pasted above is a current sk_ key copied whole."
      : " Sigma reached the public SuperDocs health endpoint but every superdocsapi request fails." +
        " That connection cannot authenticate; paste a SuperDocs API key above to bypass it.";
  } catch {
    if (generation !== errorGeneration) return;
    errorText.textContent +=
      " Sigma could not reach the public SuperDocs health endpoint, so it is blocking the call before it leaves Zoho." +
      " Check that api.superdocs.app is listed in whiteListedDomains in the manifest Sigma is actually running.";
  }
};

const showError = (error: unknown) => {
  const generation = ++errorGeneration;
  console.error("[SuperDocs Review] stage failed", error);
  setBusy(false);
  setHidden(activity, true);
  setHidden(errorPanel, false);
  setHidden(retryButton, !workflow.canResume());
  errorText.textContent =
    `${describeFailure(error)}${
      workflow.canResume()
        ? " Resume will poll this same job; it will not upload or start another chat."
        : " No job ID exists to resume. Starting again is a separate new run."
    }`;
  // A decoding failure already proves the call reached SuperDocs, so probing the
  // transport again would only add a contradictory sentence.
  if (currentStage !== "reading" && !(error instanceof UnsupportedFileResponseError)) {
    void appendConnectionDiagnosis(generation);
  }
};

const updateStages = (stage: Stage) => {
  const order: Stage[] = ["reading", "uploading", "polling", "review", "complete"];
  const aliases: Partial<Record<Stage, Stage>> = {
    asking: "polling",
    approving: "review",
    continuing: "polling",
    exporting: "complete",
  };
  const active = aliases[stage] ?? stage;
  const activeIndex = order.indexOf(active);
  document.querySelectorAll<HTMLElement>("#stages li").forEach((item, index) => {
    item.classList.toggle("active", index === activeIndex);
    item.classList.toggle("done", activeIndex > index);
  });
};

const renderUsage = (job?: NormalizedJob) => {
  if (!job?.usage) return;
  const parts = [
    job.usage.operationsCharged === undefined
      ? undefined
      : `${job.usage.operationsCharged} operation${job.usage.operationsCharged === 1 ? "" : "s"}`,
    job.usage.monthlyRemaining === undefined
      ? undefined
      : `${job.usage.monthlyRemaining} remaining`,
  ].filter(Boolean);
  usage.textContent = parts.join(" · ");
};

const onEvent = (event: WorkflowEvent) => {
  currentStage = event.stage;
  updateStages(event.stage);
  activityText.textContent = event.message;
  setHidden(activity, event.stage === "review" || event.stage === "complete");
  renderUsage(event.job);
};

const createWorkflow = () =>
  new ReviewWorkflow(writer, api, onEvent, {}, stateStore);

const showReview = (job: NormalizedJob) => {
  currentJob = job;
  get<HTMLElement>("round").textContent = String(round);
  decisionCount.textContent = `${job.changes.length} proposed`;
  changesElement.replaceChildren(...job.changes.map(createChangeCard));
  setHidden(reviewPanel, false);
  setHidden(continuePanel, true);
  setHidden(finishPanel, true);
  setBusy(false);
};

const showContinue = (job: NormalizedJob) => {
  currentJob = job;
  setHidden(reviewPanel, true);
  setHidden(continuePanel, false);
  setHidden(finishPanel, true);
  setBusy(false);
};

const showFinish = (job: NormalizedJob) => {
  currentJob = job;
  updateStages("complete");
  renderUsage(job);
  setHidden(reviewPanel, true);
  setHidden(continuePanel, true);
  setHidden(finishPanel, false);
  setBusy(false);

  // Only offer apply when both halves of the guard exist: approved content to
  // write, and the reviewed selection to verify against.
  const approved = job.updatedHtml?.trim();
  const applicable = Boolean(approved) && workflow.canApplyToHost();
  applyButton.disabled = !applicable;
  if (!approved) {
    applyNote.textContent =
      "SuperDocs returned no approved document content for this run, so there is nothing to write into Writer. The export below still reflects the session.";
  } else if (!workflow.canApplyToHost()) {
    applyNote.textContent =
      "This run was restored after a reload, so the reviewed selection is no longer held in memory and the write cannot be verified against the document. Export instead, or run a new review.";
  } else {
    applyNote.textContent =
      "Writes only over the passage you reviewed. If the selection has moved, nothing is written. Undo in Writer reverses it.";
  }
};

const run = async () => {
  const prompt = instruction.value.trim();
  if (!prompt) {
    showError(new Error("Enter an editing instruction first."));
    return;
  }
  setBusy(true);
  setHidden(errorPanel, true);
  setHidden(reviewPanel, true);
  setHidden(continuePanel, true);
  setHidden(finishPanel, true);
  setHidden(activity, false);
  round = 1;
  workflow = createWorkflow();
  try {
    const result = await workflow.begin(prompt);
    sessionId = result.sessionId;
    showGate(result.job);
  } catch (error) {
    showError(error);
  }
};

// Held in memory by the api module only; never persisted.
apiKeyInput.addEventListener("input", () => setSessionApiKey(apiKeyInput.value));

startButton.addEventListener("click", run);
retryButton.addEventListener("click", async () => {
  setBusy(true);
  setHidden(errorPanel, true);
  try {
    const job = await workflow.resume();
    sessionId = workflow.getActiveContext().sessionId ?? sessionId;
    showGate(job);
  } catch (error) {
    showError(error);
  }
});

const showGate = (job: NormalizedJob) => {
  if (job.status === "awaiting_approval") {
    if (job.awaitingKind === "continue_prompt") showContinue(job);
    else showReview(job);
  } else {
    showFinish(job);
  }
};

// One decision covers every proposed change in the round: reject discards all
// of them, accept keeps all of them. There is no per-item mix.
const submitRoundDecision = async (approved: boolean) => {
  if (!currentJob?.jobId) return showError(new Error("The active job ID is missing."));
  setBusy(true);
  setHidden(errorPanel, true);
  try {
    const payload: ApprovalDecision[] = currentJob.changes.map((change) => ({
      changeId: change.id,
      approved,
    }));
    const next = await workflow.decideRound(sessionId, currentJob.jobId, payload);
    if (next.status === "awaiting_approval" && next.awaitingKind !== "continue_prompt") {
      round += 1;
    }
    showGate(next);
    setBusy(false);
  } catch (error) {
    showError(error);
  }
};

acceptAllButton.addEventListener("click", () => void submitRoundDecision(true));
rejectAllButton.addEventListener("click", () => void submitRoundDecision(false));

const submitContinueDecision = async (shouldContinue: boolean) => {
  if (!currentJob?.jobId) return showError(new Error("The active job ID is missing."));
  setBusy(true);
  setHidden(errorPanel, true);
  try {
    const next = await workflow.continueRound(
      sessionId,
      currentJob.jobId,
      shouldContinue,
    );
    showGate(next);
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
};

continueButton.addEventListener("click", () => void submitContinueDecision(true));
stopButton.addEventListener("click", () => void submitContinueDecision(false));

applyButton.addEventListener("click", async () => {
  const approved = currentJob?.updatedHtml?.trim();
  if (!approved) {
    return showError(new Error("There is no approved content to apply."));
  }
  setBusy(true);
  setHidden(errorPanel, true);
  try {
    const result = await workflow.applyToHost(approved);
    // Only "applied" means the document was observed to change. Writer applies
    // the edit almost immediately in practice but never confirms it, so
    // "unverified" reads as a heads-up to glance at the paragraph, not a failure.
    activityText.textContent =
      result.outcome === "applied"
        ? `Applied to the document via ${result.event}. If Track Changes was on, review it with Writer's accept/reject controls.`
        : "Sent to Writer — it usually lands within a second but doesn't confirm the write. Check the paragraph; if it didn't change, use the export below.";
    setHidden(activity, false);
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
});

exportButton.addEventListener("click", async () => {
  setBusy(true);
  setHidden(errorPanel, true);
  try {
    const result = await workflow.export(sessionId);
    const url = URL.createObjectURL(result.blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = result.filename;
    anchor.click();
    URL.revokeObjectURL(url);
    // Name the format actually delivered, and surface why if it was not .docx.
    activityText.textContent = result.note
      ? `Exported ${result.filename}. ${result.note}`
      : `Approved ${result.format.toUpperCase()} downloaded as ${result.filename}.`;
    setHidden(activity, false);
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
});

workflow = createWorkflow();
writer
  .initialize()
  .then(async () => {
    get<HTMLElement>("connection").textContent = "Ready";
    get<HTMLElement>("connection").classList.add("ready");
    const restored = await workflow.restore();
    if (restored) {
      sessionId = workflow.getActiveContext().sessionId ?? "";
      showGate(restored);
    }
  })
  .catch(showError);
