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

export const createChangeCard = (
  change: PendingChange,
  onDecision: (approved: boolean) => void,
): HTMLElement => {
  const card = element("article", "change-card");
  const top = element("div", "change-top");
  top.append(
    element("span", "change-type", change.operation),
    element("span", "change-id", change.chunkId ?? change.id),
  );

  const explanation = element("p", "explanation", change.explanation);
  const diff = element("div", "diff");
  const before = element("div");
  before.append(
    element("span", "diff-label removed", "BEFORE"),
    element("pre", "before", change.oldHtml || "(new content)"),
  );
  const after = element("div");
  after.append(
    element("span", "diff-label added", "AFTER"),
    element("pre", "after", change.newHtml || "(delete content)"),
  );
  diff.append(before, after);

  const decision = element("div", "decision");
  decision.setAttribute("role", "group");
  decision.setAttribute("aria-label", "Decision");
  const reject = element("button", "reject secondary", "Reject");
  reject.setAttribute("type", "button");
  const accept = element("button", "accept secondary", "Accept");
  accept.setAttribute("type", "button");
  reject.addEventListener("click", () => {
    reject.classList.add("selected");
    accept.classList.remove("selected");
    onDecision(false);
  });
  accept.addEventListener("click", () => {
    accept.classList.add("selected");
    reject.classList.remove("selected");
    onDecision(true);
  });
  decision.append(reject, accept);
  card.append(top, explanation, diff, decision);
  return card;
};
