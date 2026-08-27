import type { PendingChange } from "./types";

const element = <K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

// Proposal markup is untrusted. It is parsed in a detached document — DOMParser
// executes no scripts and this tree is never attached — and only its text is
// read back. Nothing here is ever assigned to innerHTML.
export const readableText = (html: string): string => {
  if (!html) return "";
  try {
    const parsed = new DOMParser().parseFromString(html, "text/html");
    return (parsed.body.textContent ?? "").replace(/\s+/g, " ").trim();
  } catch {
    return "";
  }
};

// One decision now applies to every proposed change in a round (see
// #accept-all/#reject-all in main.ts), so each card is a read-only preview of
// what that decision will cover, not an independent accept/reject control.
export const createChangeCard = (change: PendingChange): HTMLElement => {
  const card = element("article", "change-card");
  const top = element("div", "change-top");
  top.append(
    element("span", "change-type", change.operation),
    element("span", "change-id", change.chunkId ?? change.id),
  );

  const explanation = element("p", "explanation", change.explanation);

  // The wording is what a reviewer decides on, so the text is shown first and
  // the markup is kept one click away rather than dropped.
  const oldText = readableText(change.oldHtml);
  const newText = readableText(change.newHtml);
  const diff = element("div", "diff");
  const before = element("div");
  before.append(
    element("span", "diff-label removed", "BEFORE"),
    element("p", "before prose", oldText || "(new content)"),
  );
  const after = element("div");
  after.append(
    element("span", "diff-label added", "AFTER"),
    element("p", "after prose", newText || "(deleted content)"),
  );
  diff.append(before, after);

  const markup = element("details", "markup");
  markup.append(element("summary", undefined, "Show markup"));
  markup.append(
    element("pre", "before", change.oldHtml || "—"),
    element("pre", "after", change.newHtml || "—"),
  );

  card.append(top, explanation, diff, markup);
  return card;
};
