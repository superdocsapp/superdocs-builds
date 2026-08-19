const HOSTS = {
  "chatgpt.com": ["[data-message-author-role='assistant']"],
  "claude.ai": ["[data-is-streaming='false'] .standard-markdown", ".standard-markdown"],
};

function latestAnswer() {
  const selectors = HOSTS[location.hostname];
  if (!selectors) return null;
  for (const selector of selectors) {
    const matches = [...document.querySelectorAll(selector)].filter((element) => element.textContent.trim());
    if (matches.length) return matches.at(-1);
  }
  return null;
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
      const allowed = ["href", "colspan", "rowspan", "start", "data-latex"];
      if (!allowed.includes(attribute.name.toLowerCase())) node.removeAttribute(attribute.name);
    }
  });
  return copy.innerHTML.trim();
}

chrome.runtime.onMessage.addListener((message, _sender, respond) => {
  if (message?.type !== "CAPTURE_LATEST_ANSWER") return;
  const answer = latestAnswer();
  if (!answer) {
    respond({ ok: false, error: "No completed assistant answer was found. Wait for the answer to finish, then try again." });
    return;
  }
  respond({ ok: true, source: location.hostname, html: sanitizeAnswer(answer), text: answer.innerText.trim() });
});
