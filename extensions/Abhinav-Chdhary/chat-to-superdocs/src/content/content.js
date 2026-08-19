const RESPONSE_SELECTORS = {
  "chatgpt.com": ["[data-message-author-role='assistant']"],
  "chat.openai.com": ["[data-message-author-role='assistant']"],
  "claude.ai": ["[data-is-streaming='false'] .standard-markdown", ".font-claude-response", "[data-testid='assistant-message']", ".standard-markdown"],
  default: ["[data-message-author-role='assistant']", ".font-claude-response", ".model-response-text", ".assistant-message", ".response-content", "article .markdown", ".standard-markdown"],
};

let pollTimer = null;
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
  // KaTeX includes presentation MathML alongside its browser-only visual spans.
  // Keep that standards-based MathML intact: SuperDocs accepts HTML, whereas the
  // previous data-latex wrapper was an extension-private attribute it discarded.
  copy.querySelectorAll(".katex").forEach((node) => {
    const math = node.querySelector("math");
    if (!math) return;
    const replacement = math.cloneNode(true);
    replacement.setAttribute("xmlns", "http://www.w3.org/1998/Math/MathML");
    node.replaceWith(replacement);
  });
  copy.querySelectorAll("*").forEach((node) => {
    if (node.namespaceURI === "http://www.w3.org/1998/Math/MathML") return;
    for (const attribute of [...node.attributes]) {
      if (!["href", "colspan", "rowspan", "start"].includes(attribute.name.toLowerCase())) node.removeAttribute(attribute.name);
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
  removeChooser(button); setLoading(button, true); let handedOff = false;
  try {
    const { templates } = await send({ type: "LIST_TEMPLATES" });
    if (!templates.length) { handedOff = true; return await addResponse(button, response, null); }
    const panel = document.createElement("div"); panel.className = "cts-chooser"; panel.setAttribute("role", "dialog");
    const label = document.createElement("p"); label.textContent = "Choose a template"; panel.append(label);
    for (const template of templates) {
      const templateButton = document.createElement("button"); templateButton.type = "button"; templateButton.textContent = template.name;
      templateButton.addEventListener("click", () => addResponse(button, response, template)); panel.append(templateButton);
    }
    button.parentElement.append(panel);
  } catch (error) {
    statusFor(button, error.message, "error");
  } finally {
    if (!handedOff) setLoading(button, false);
  }
}

async function addResponse(button, response, template) {
  removeChooser(button); button.disabled = true; setComplete(button, false); setLoading(button, true);
  try {
    const result = await send({ type: "ADD_RESPONSE", html: sanitizeAnswer(response), template });
    button.setAttribute("aria-label", "Adding to doc");
    if (result.state === "complete") return finishAdd(button);
    schedulePoll(button);
  } catch (error) { button.disabled = false; setLoading(button, false); statusFor(button, error.message, "error"); }
}

function schedulePoll(button) {
  clearTimeout(pollTimer);
  pollTimer = setTimeout(async () => {
    try {
      const result = await send({ type: "POLL_CONVERSATION" });
      if (result.state === "processing") { schedulePoll(button); return; }
      if (result.state === "complete") return finishAdd(button);
    } catch (error) { button.disabled = false; setLoading(button, false); statusFor(button, error.message, "error"); }
  }, 900);
}

function setLoading(button, isLoading) {
  button.toggleAttribute("data-loading", isLoading);
  button.setAttribute("aria-busy", String(isLoading));
}

function setComplete(button, isComplete) {
  button.toggleAttribute("data-complete", isComplete);
}

function finishAdd(button) {
  button.disabled = false; setLoading(button, false); setComplete(button, true); button.setAttribute("aria-label", "Added to doc");
  window.setTimeout(() => { setComplete(button, false); button.setAttribute("aria-label", "Add to doc"); }, 700);
}

function attachControl(response) {
  if (response.dataset.ctsAttached === "true") return;
  response.dataset.ctsAttached = "true";
  const block = firstReadableBlock(response);
  if (getComputedStyle(block).position === "static") block.style.position = "relative";
  const rail = document.createElement("span"); rail.className = "cts-rail";
  const button = document.createElement("button"); button.type = "button"; button.className = "cts-add"; button.title = "Add to doc"; button.setAttribute("aria-label", "Add to doc");
  button.innerHTML = '<svg class="cts-plus" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 5v14M5 12h14"/></svg><svg class="cts-check" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="m5 12 4.5 4.5L19 7"/></svg>';
  button.addEventListener("click", async (event) => {
    event.preventDefault(); event.stopPropagation();
    try {
      const state = await send({ type: "POLL_CONVERSATION" });
      if (state.state === "processing") { setLoading(button, true); return schedulePoll(button); }
      if (state.state === "migrated") return finishAdd(button);
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
    .cts-add,.cts-chooser button { border:1px solid #b9c7df; border-radius:999px; background:#f8fbff; color:#18315d; cursor:pointer; font:600 11px/1 ui-rounded, "SF Pro Rounded", system-ui, sans-serif; letter-spacing:.01em; padding:6px 9px; box-shadow:0 1px 2px #162a4b1c; }
    .cts-add { position:relative; display:grid; place-items:center; width:27px; height:27px; padding:0; border-color:#f97766; background:#f97766; color:#fff; } .cts-add svg { position:absolute; width:15px; height:15px; fill:none; stroke:currentColor; stroke-linecap:round; stroke-linejoin:round; stroke-width:2.2; transition:opacity .16s ease, transform .16s ease; } .cts-add .cts-check { opacity:0; transform:scale(.7); } .cts-add[data-complete] .cts-plus { opacity:0; transform:scale(.7) rotate(45deg); } .cts-add[data-complete] .cts-check { opacity:1; transform:scale(1); } .cts-add[data-loading]::after { content:""; position:absolute; inset:-5px; border:2px solid #f97766; border-right-color:transparent; border-radius:50%; animation:cts-spin .75s linear infinite; }
    .cts-add:hover { background:#df5e50; border-color:#df5e50; } .cts-chooser button:hover { background:#18315d; border-color:#18315d; color:#fff; } .cts-add:focus-visible,.cts-chooser button:focus-visible { outline:3px solid #e6a56b; outline-offset:2px; }
    .cts-status { display:block; width:190px; color:#526176; font:500 11px/1.3 ui-rounded, "SF Pro Rounded", system-ui, sans-serif; } .cts-status.success { color:#1d6b52; } .cts-status.error { color:#a2362c; }
    .cts-chooser { position:absolute; left:0; top:30px; z-index:99999; width:240px; padding:11px; border:1px solid #b9c7df; border-radius:12px; background:#f8fbff; box-shadow:0 12px 28px #162a4b2b; color:#18315d; font-family:ui-rounded, "SF Pro Rounded", system-ui, sans-serif; }
    .cts-chooser p { margin:0 0 8px; font-size:11px; font-weight:650; } .cts-chooser button { display:block; width:100%; margin-top:5px; text-align:left; } .cts-template-note { display:block; color:#526176; font-size:11px; line-height:1.35; }
    @keyframes cts-spin { to { transform:rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) { .cts-add[data-loading]::after { animation:none; border-right-color:#f97766; } .cts-add svg,.cts-chooser button { transition:none; } }
  `;
  document.head.append(style);
}

function scan() { injectStyles(); responses().forEach(attachControl); }

scan();
new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true });
