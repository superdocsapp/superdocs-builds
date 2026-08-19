const RESPONSE_SELECTORS = {
  "chatgpt.com": ["[data-message-author-role='assistant']"],
  "chat.openai.com": ["[data-message-author-role='assistant']"],
  "claude.ai": ["[data-is-streaming='false'] .standard-markdown", ".font-claude-response", "[data-testid='assistant-message']", ".standard-markdown"],
  default: ["[data-message-author-role='assistant']", ".font-claude-response", ".model-response-text", ".assistant-message", ".response-content", "article .markdown", ".standard-markdown"],
};

let pollTimer = null;
let chooserOutsideListener = null;
function send(message) {
  return new Promise((resolve, reject) => {
    const runtime = globalThis.chrome?.runtime;
    if (!runtime?.sendMessage) {
      reject(new Error("The extension was reloaded. Refresh this chat page, then try again."));
      return;
    }
    runtime.sendMessage(message, (response) => {
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
  // SuperDocs' equation nodes use the KaTeX source plus a data-type marker.
  // MathML alone is not an editor node, so it is silently dropped on import.
  copy.querySelectorAll(".katex").forEach((node) => {
    const latex = node.querySelector("annotation[encoding='application/x-tex']")?.textContent?.trim();
    if (!latex) return;
    const replacement = copy.ownerDocument.createElement("span");
    replacement.setAttribute("data-latex", latex);
    replacement.setAttribute("data-type", node.closest(".katex-display") ? "block-math" : "inline-math");
    replacement.textContent = latex;
    node.replaceWith(replacement);
  });
  copy.querySelectorAll("*").forEach((node) => {
    for (const attribute of [...node.attributes]) {
      if (!["href", "colspan", "rowspan", "start", "data-latex", "data-type"].includes(attribute.name.toLowerCase())) node.removeAttribute(attribute.name);
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

function removeChooser(button) {
  button.parentElement.querySelector(":scope > .cts-chooser")?.remove();
  if (chooserOutsideListener) {
    document.removeEventListener("pointerdown", chooserOutsideListener, true);
    chooserOutsideListener = null;
  }
}

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
    const blankButton = document.createElement("button");
    blankButton.type = "button";
    blankButton.className = "cts-blank-document";
    blankButton.textContent = "Blank document";
    blankButton.addEventListener("click", () => addResponse(button, response, null));
    panel.append(blankButton);
    button.parentElement.append(panel);
    window.setTimeout(() => {
      chooserOutsideListener = (event) => {
        if (!panel.contains(event.target) && !button.contains(event.target)) removeChooser(button);
      };
      document.addEventListener("pointerdown", chooserOutsideListener, true);
    }, 0);
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
    .cts-add,.cts-chooser button { border:1px solid #e4dbd5; border-radius:10px; background:#fffdfb; color:#2b2623; cursor:pointer; font:600 12px/1.25 ui-rounded, "SF Pro Rounded", system-ui, sans-serif; letter-spacing:.005em; box-shadow:0 1px 2px #2b262312; }
    .cts-add { position:relative; display:grid; place-items:center; width:28px; height:28px; padding:0; border-color:#f97766; border-radius:50%; background:#f97766; color:#fff; } .cts-add svg { position:absolute; width:15px; height:15px; fill:none; stroke:currentColor; stroke-linecap:round; stroke-linejoin:round; stroke-width:2.2; transition:opacity .16s ease, transform .16s ease; } .cts-add .cts-check { opacity:0; transform:scale(.7); } .cts-add[data-complete] .cts-plus { opacity:0; transform:scale(.7) rotate(45deg); } .cts-add[data-complete] .cts-check { opacity:1; transform:scale(1); } .cts-add[data-loading]::after { content:""; position:absolute; inset:-5px; border:2px solid #f97766; border-right-color:transparent; border-radius:50%; animation:cts-spin .75s linear infinite; }
    .cts-add:hover { background:#df5e50; border-color:#df5e50; } .cts-chooser button:hover { border-color:#f97766; background:#fff0ed; color:#2b2623; transform:translateY(-1px); box-shadow:0 5px 13px #2b26231a; } .cts-add:focus-visible,.cts-chooser button:focus-visible { outline:3px solid #f9b4aa; outline-offset:2px; }
    .cts-status { display:block; width:190px; color:#706863; font:500 11px/1.35 ui-rounded, "SF Pro Rounded", system-ui, sans-serif; } .cts-status.success { color:#706863; } .cts-status.error { color:#c45b4e; }
    .cts-chooser { position:absolute; left:0; top:34px; z-index:99999; box-sizing:border-box; width:min(272px, calc(100vw - 52px)); padding:12px; border:1px solid #e4dbd5; border-radius:14px; background:#fffdfb; box-shadow:0 14px 32px #2b26232b; color:#2b2623; font-family:ui-rounded, "SF Pro Rounded", system-ui, sans-serif; }
    .cts-chooser p { margin:0 0 9px; color:#514944; font-size:12px; font-weight:700; letter-spacing:.01em; } .cts-chooser button { display:block; width:100%; margin-top:6px; padding:10px 11px; text-align:left; overflow-wrap:anywhere; transition:border-color .16s ease, background .16s ease, color .16s ease, transform .16s ease, box-shadow .16s ease; } .cts-template-note { display:block; color:#706863; font-size:11px; line-height:1.35; }
    @keyframes cts-spin { to { transform:rotate(360deg); } }
    @media (prefers-reduced-motion: reduce) { .cts-add[data-loading]::after { animation:none; border-right-color:#f97766; } .cts-add svg,.cts-chooser button { transition:none; } }
  `;
  document.head.append(style);
}

function scan() { injectStyles(); responses().forEach(attachControl); }

scan();
new MutationObserver(scan).observe(document.documentElement, { childList: true, subtree: true });
