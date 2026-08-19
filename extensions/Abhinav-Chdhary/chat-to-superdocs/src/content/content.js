const RESPONSE_SELECTORS = {
  "chatgpt.com": ["[data-message-author-role='assistant']"],
  "claude.ai": ["[data-is-streaming='false'] .standard-markdown", ".standard-markdown"],
  default: ["[data-message-author-role='assistant']", ".model-response-text", ".assistant-message", ".response-content", "article .markdown", ".standard-markdown"],
};

let pollTimer = null;
let lastReviewedChangeIds = "";

function send(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, (response) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      if (!response?.ok) return reject(new Error(response?.error || "Extension action failed."));
      resolve(response);
    });
  });
}

function selectors() {
  return [...(RESPONSE_SELECTORS[location.hostname] ?? []), ...RESPONSE_SELECTORS.default];
}

function responses() {
  const found = new Set();
  for (const selector of selectors()) {
    for (const element of document.querySelectorAll(selector)) {
      if (element.textContent.trim().length > 1) found.add(element);
    }
  }
  return [...found].filter((element) => ![...found].some((other) => other !== element && other.contains(element)));
}

function sanitizeAnswer(element) {
  const copy = element.cloneNode(true);
  copy.querySelectorAll("button, nav, script, style, svg, form, textarea, iframe, object, embed, [aria-hidden='true']").forEach((node) => node.remove());
  copy.querySelectorAll("[data-testid*='copy'], [data-testid*='branch']").forEach((node) => node.remove());
  copy.querySelectorAll(".katex, mjx-container").forEach((node) => {
    const latex = node.querySelector("annotation[encoding='application/x-tex']")?.textContent?.trim();
    if (latex) node.outerHTML = `<span data-latex="${latex.replace(/[&<\"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", "\"": "&quot;" })[character])}">${node.innerHTML}</span>`;
  });
  copy.querySelectorAll("*").forEach((node) => {
    for (const attribute of [...node.attributes]) {
      if (!["href", "colspan", "rowspan", "start", "data-latex"].includes(attribute.name.toLowerCase())) node.removeAttribute(attribute.name);
    }
  });
  return copy.innerHTML.trim();
}

function firstReadableBlock(response) {
  return response.querySelector("p, h1, h2, h3, h4, pre, ul, ol, table, blockquote") ?? response;
}

function statusFor(button, message, tone = "") {
  let status = button.parentElement.querySelector(":scope > .cts-status");
  if (!status) { status = document.createElement("span"); status.className = "cts-status"; button.parentElement.append(status); }
  status.className = `cts-status ${tone}`; status.textContent = message;
  return status;
}

function removeChooser(button) { button.parentElement.querySelector(":scope > .cts-chooser")?.remove(); }

async function chooser(button, response) {
  removeChooser(button);
  const panel = document.createElement("div"); panel.className = "cts-chooser"; panel.setAttribute("role", "dialog");
  const label = document.createElement("p"); label.textContent = "Loading your SuperDocs templates…"; panel.append(label); button.parentElement.append(panel);
  try {
    const { templates } = await send({ type: "LIST_TEMPLATES" });
    label.textContent = templates.length ? "Start this chat document with" : "No saved SuperDocs templates found.";
    for (const template of templates) {
      const templateButton = document.createElement("button"); templateButton.type = "button"; templateButton.textContent = template.name;
      templateButton.addEventListener("click", () => addResponse(button, response, template)); panel.append(templateButton);
    }
    if (!templates.length) {
      const note = document.createElement("span"); note.className = "cts-template-note"; note.textContent = "Create or upload a template in SuperDocs, then try again."; panel.append(note);
    }
  } catch (error) {
    label.textContent = error.message;
  }
}

async function addResponse(button, response, template) {
  removeChooser(button); button.disabled = true; statusFor(button, "Adding to document…");
  try {
    await send({ type: "ADD_RESPONSE", html: sanitizeAnswer(response), template });
    button.setAttribute("aria-label", "Adding to doc"); schedulePoll(button);
  } catch (error) { button.disabled = false; statusFor(button, error.message, "error"); }
}

function reviewPanel(button, changes) {
  const key = changes.map((change) => change.change_id).join(",");
  if (key === lastReviewedChangeIds) return;
  lastReviewedChangeIds = key;
  button.parentElement.querySelector(":scope > .cts-review")?.remove();
  const panel = document.createElement("section"); panel.className = "cts-review";
  const heading = document.createElement("strong"); heading.textContent = "Review proposed changes"; panel.append(heading);
  for (const change of changes) {
    const label = document.createElement("label");
    const checkbox = document.createElement("input"); checkbox.type = "checkbox"; checkbox.value = change.change_id; checkbox.checked = true;
    const copy = document.createElement("span"); copy.textContent = change.ai_explanation || `${change.operation ?? "Edit"} document content`;
    label.append(checkbox, copy); panel.append(label);
  }
  const apply = document.createElement("button"); apply.type = "button"; apply.textContent = "Apply selected";
  apply.addEventListener("click", async () => {
    const allChanges = changes.map((change) => ({ change_id: change.change_id }));
    const approvedIds = [...panel.querySelectorAll("input:checked")].map((input) => input.value);
    apply.disabled = true;
    try { await send({ type: "DECIDE_CHANGES", changes: allChanges, approvedIds }); panel.remove(); statusFor(button, "Applying selected changes…"); schedulePoll(button); }
    catch (error) { apply.disabled = false; statusFor(button, error.message, "error"); }
  });
  panel.append(apply); button.parentElement.append(panel); statusFor(button, "Changes are ready to review.");
}

function exportAction(button) {
  let exportButton = button.parentElement.querySelector(":scope > .cts-export");
  if (exportButton) return;
  exportButton = document.createElement("button"); exportButton.type = "button"; exportButton.className = "cts-export"; exportButton.textContent = "Export DOCX";
  exportButton.addEventListener("click", async () => {
    exportButton.disabled = true;
    try { await send({ type: "EXPORT_CONVERSATION" }); statusFor(button, "Export download started."); }
    catch (error) { exportButton.disabled = false; statusFor(button, error.message, "error"); }
  });
  button.parentElement.append(exportButton);
}

function schedulePoll(button) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    try {
      const result = await send({ type: "POLL_CONVERSATION" });
      if (result.state === "processing") { statusFor(button, "Document is being styled…"); schedulePoll(button); return; }
      if (result.state === "review") { reviewPanel(button, result.changes); return; }
      if (result.state === "complete") { button.disabled = false; button.setAttribute("aria-label", "Add to doc"); statusFor(button, "Added to this chat’s document.", "success"); exportAction(button); return; }
    } catch (error) { button.disabled = false; statusFor(button, error.message, "error"); }
  }, 900);
}

function attachControl(response) {
  if (response.dataset.ctsAttached === "true") return;
  response.dataset.ctsAttached = "true";
  const block = firstReadableBlock(response);
  if (getComputedStyle(block).position === "static") block.style.position = "relative";
  const rail = document.createElement("span"); rail.className = "cts-rail";
  const button = document.createElement("button"); button.type = "button"; button.className = "cts-add"; button.title = "Add to doc"; button.setAttribute("aria-label", "Add to doc");
  button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M5 19 19 5M9 5h10v10"/></svg>';
  button.addEventListener("click", async (event) => {
    event.preventDefault(); event.stopPropagation();
    try {
      const state = await send({ type: "POLL_CONVERSATION" });
      if (state.state === "review") return reviewPanel(button, state.changes);
      if (state.state === "processing") { statusFor(button, "Document is still being styled…"); return schedulePoll(button); }
      if (state.hasDocument || state.state === "complete") return addResponse(button, response);
      await chooser(button, response);
    } catch (error) { statusFor(button, error.message, "error"); }
  });
  rail.append(button); block.prepend(rail);
}

function injectStyles() {
  if (document.querySelector("#chat-to-superdocs-styles")) return;
  const style = document.createElement("style"); style.id = "chat-to-superdocs-styles";
  style.textContent = `
    .cts-rail { position:absolute; left:-42px; top:0; z-index:3; display:flex; flex-direction:column; align-items:flex-start; gap:6px; font-family:ui-rounded, "SF Pro Rounded", system-ui, sans-serif; }
    .cts-add,.cts-export,.cts-chooser button,.cts-review button { border:1px solid #b9c7df; border-radius:999px; background:#f8fbff; color:#18315d; cursor:pointer; font:600 11px/1 ui-rounded, "SF Pro Rounded", system-ui, sans-serif; letter-spacing:.01em; padding:6px 9px; box-shadow:0 1px 2px #162a4b1c; }
    .cts-add { display:grid; place-items:center; width:27px; height:27px; padding:0; border-color:#f97766; background:#f97766; color:#fff; } .cts-add svg { width:15px; height:15px; fill:none; stroke:currentColor; stroke-linecap:round; stroke-linejoin:round; stroke-width:2.2; }
    .cts-add:hover { background:#df5e50; border-color:#df5e50; transform:translate(1px,-1px); } .cts-export:hover,.cts-chooser button:hover,.cts-review button:hover { background:#18315d; border-color:#18315d; color:#fff; } .cts-add:focus-visible,.cts-export:focus-visible,.cts-chooser button:focus-visible,.cts-review button:focus-visible { outline:3px solid #e6a56b; outline-offset:2px; }
    .cts-status { display:block; width:190px; color:#526176; font:500 11px/1.3 ui-rounded, "SF Pro Rounded", system-ui, sans-serif; } .cts-status.success { color:#1d6b52; } .cts-status.error { color:#a2362c; }
    .cts-chooser,.cts-review { position:absolute; left:0; top:30px; z-index:99999; width:240px; padding:11px; border:1px solid #b9c7df; border-radius:12px; background:#f8fbff; box-shadow:0 12px 28px #162a4b2b; color:#18315d; font-family:ui-rounded, "SF Pro Rounded", system-ui, sans-serif; }
    .cts-chooser p { margin:0 0 8px; font-size:11px; font-weight:650; } .cts-chooser button { display:block; width:100%; margin-top:5px; text-align:left; } .cts-template-note { display:block; color:#526176; font-size:11px; line-height:1.35; }
    .cts-review strong { display:block; margin-bottom:7px; font-size:12px; } .cts-review label { display:flex; gap:6px; align-items:flex-start; margin:7px 0; font-size:11px; line-height:1.3; } .cts-review button { margin-top:6px; }
    @media (prefers-reduced-motion: reduce) { .cts-add,.cts-export,.cts-chooser button,.cts-review button { transition:none; } }
  `;
  document.head.append(style);
}

function scan() { injectStyles(); responses().forEach(attachControl); }

scan();
new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true });
