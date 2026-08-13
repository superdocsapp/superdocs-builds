import "./styles.css";
import { SigmaSuperDocsClient } from "./api";
import { BrowserRunStateStore } from "./state";
import type { ApprovalDecision, NormalizedJob } from "./types";
import { createChangeCard } from "./view";
import { ReviewWorkflow, type Stage, type WorkflowEvent } from "./workflow";
import { ZohoWriterAdapter } from "./writer";

const app = document.querySelector<HTMLElement>("#app");
if (!app) throw new Error("App root not found.");

app.innerHTML = `
  <header class="hero">
    <div class="mark" aria-hidden="true">S</div>
    <div>
      <p class="eyebrow">SUPERDOCS × WRITER</p>
      <h1>Review selected text</h1>
    </div>
    <span id="connection" class="status-dot">Connecting</span>
  </header>

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
      <span id="decision-count" class="counter">0 decided</span>
    </div>
    <div id="changes"></div>
    <button id="submit" class="primary">Submit decisions</button>
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
    <h2>Approved session ready to export</h2>
    <p class="warning">Automatic Writer writeback is unavailable. Sigma SDK v3 documents cursor insertion, not verified selection replacement or Track Changes control. Apply reviewed text manually in Writer, or use the approved export.</p>
    <button id="export" class="secondary">Export approved DOCX</button>
    <p class="hint">SuperDocs structural HTML is review evidence only and is never substring-mapped onto Zoho HTML.</p>
  </section>
`;

const get = <T extends HTMLElement>(id: string): T => {
  const element = document.getElementById(id);
  if (!element) throw new Error(`Missing #${id}`);
  return element as T;
};

const instruction = get<HTMLTextAreaElement>("instruction");
const startButton = get<HTMLButtonElement>("start");
const submitButton = get<HTMLButtonElement>("submit");
const retryButton = get<HTMLButtonElement>("retry");
const continueButton = get<HTMLButtonElement>("continue-job");
const stopButton = get<HTMLButtonElement>("stop-job");
const exportButton = get<HTMLButtonElement>("export");
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
let decisions = new Map<string, boolean>();

const setHidden = (element: HTMLElement, hidden: boolean) =>
  element.classList.toggle("hidden", hidden);

const setBusy = (busy: boolean) => {
  startButton.disabled = busy;
  submitButton.disabled = busy;
  continueButton.disabled = busy;
  stopButton.disabled = busy;
  exportButton.disabled = busy;
};

const showError = (error: unknown) => {
  setBusy(false);
  setHidden(activity, true);
  setHidden(errorPanel, false);
  setHidden(retryButton, !workflow.canResume());
  errorText.textContent =
    `${error instanceof Error ? error.message : "An unexpected error occurred."}${
      workflow.canResume()
        ? " Resume will poll this same job; it will not upload or start another chat."
        : " No job ID exists to resume. Starting again is a separate new run."
    }`;
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
  updateStages(event.stage);
  activityText.textContent = event.message;
  setHidden(activity, event.stage === "review" || event.stage === "complete");
  renderUsage(event.job);
};

const createWorkflow = () =>
  new ReviewWorkflow(writer, api, onEvent, {}, stateStore);

const renderChange = (change: NormalizedJob["changes"][number]) =>
  createChangeCard(change, (approved) => {
    decisions.set(change.id, approved);
    decisionCount.textContent = `${decisions.size}/${currentJob?.changes.length ?? 0} decided`;
  });

const showReview = (job: NormalizedJob) => {
  currentJob = job;
  decisions = new Map();
  get<HTMLElement>("round").textContent = String(round);
  decisionCount.textContent = `0/${job.changes.length} decided`;
  changesElement.replaceChildren(...job.changes.map(renderChange));
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

submitButton.addEventListener("click", async () => {
  if (!currentJob?.jobId) return showError(new Error("The active job ID is missing."));
  if (decisions.size !== currentJob.changes.length) {
    return showError(new Error("Accept or reject every proposal in this round."));
  }
  setBusy(true);
  setHidden(errorPanel, true);
  try {
    const payload: ApprovalDecision[] = currentJob.changes.map((change) => ({
      changeId: change.id,
      approved: decisions.get(change.id) ?? false,
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
});

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

exportButton.addEventListener("click", async () => {
  setBusy(true);
  setHidden(errorPanel, true);
  try {
    const blob = await workflow.export(sessionId);
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "superdocs-reviewed-selection.docx";
    anchor.click();
    URL.revokeObjectURL(url);
    activityText.textContent = "Approved DOCX downloaded.";
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
