const { parse: parseHtml } = require("node-html-parser");

const OPAQUE = new Set([
  "table",
  "codeBlock",
  "extension",
  "bodiedExtension",
  "inlineExtension",
  "mediaSingle",
  "mediaGroup",
  "embedCard",
  "decisionList",
  "taskList",
  "layoutSection",
  "expand",
  "nestedExpand",
]);

function textOf(node) {
  if (!node) return "";
  if (node.type === "text") return node.text || "";
  return (node.content || []).map(textOf).join("");
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function marksWrap(text, marks) {
  let html = escapeHtml(text);
  for (const mark of marks || []) {
    if (mark.type === "strong") html = `<strong>${html}</strong>`;
    else if (mark.type === "em") html = `<em>${html}</em>`;
    else if (mark.type === "underline") html = `<u>${html}</u>`;
    else if (mark.type === "strike") html = `<s>${html}</s>`;
    else if (mark.type === "code") html = `<code>${html}</code>`;
    else if (mark.type === "link" && mark.attrs?.href) {
      html = `<a href="${escapeHtml(mark.attrs.href)}">${html}</a>`;
    }
  }
  return html;
}

function inlineHtml(node) {
  if (!node) return "";
  if (node.type === "text") return marksWrap(node.text || "", node.marks);
  if (node.type === "hardBreak") return "<br/>";
  return (node.content || []).map(inlineHtml).join("");
}

function stableId(node, path) {
  return (node.attrs && node.attrs.localId) || `adf-${path.replace(/\//g, "-")}`;
}

function ensureLocalIds(doc) {
  const clone = JSON.parse(JSON.stringify(doc));
  (clone.content || []).forEach((node, i) => {
    node.attrs = node.attrs || {};
    if (!node.attrs.localId) node.attrs.localId = `adf-${i}`;
  });
  return clone;
}

function blockToHtml(node, path) {
  const id = stableId(node, path);
  const attr = `data-chunk-id="${id}" data-adf-path="${path}" data-adf-type="${node.type}"`;

  if (OPAQUE.has(node.type)) {
    return `<div ${attr} data-adf-opaque="true"><em>[${node.type} preserved — not rewritten]</em></div>`;
  }

  if (node.type === "heading") {
    const level = Math.min(Math.max(node.attrs?.level || 1, 1), 6);
    return `<h${level} ${attr}>${inlineHtml(node)}</h${level}>`;
  }
  if (node.type === "paragraph") {
    return `<p ${attr}>${inlineHtml(node)}</p>`;
  }
  if (node.type === "blockquote") {
    const inner = (node.content || []).map((c, i) => blockToHtml(c, `${path}/${i}`)).join("");
    return `<blockquote ${attr}>${inner}</blockquote>`;
  }
  if (node.type === "bulletList" || node.type === "orderedList") {
    const tag = node.type === "bulletList" ? "ul" : "ol";
    const items = (node.content || [])
      .map((li) => `<li>${(li.content || []).map((c, i) => blockToHtml(c, `${path}-li-${i}`)).join("")}</li>`)
      .join("");
    return `<${tag} ${attr}>${items}</${tag}>`;
  }
  if (node.type === "rule") return `<hr ${attr}/>`;
  return `<div ${attr}>${escapeHtml(textOf(node))}</div>`;
}

function adfToHtml(doc) {
  const rooted = ensureLocalIds(doc);
  const html = (rooted.content || [])
    .map((node, i) => blockToHtml(node, String(i)))
    .join("\n");
  return { html: `<div class="confluence-page">${html}</div>`, doc: rooted };
}

function listSections(doc) {
  const rooted = ensureLocalIds(doc);
  const sections = [];
  let current = null;
  (rooted.content || []).forEach((node, i) => {
    if (node.type === "heading") {
      current = {
        id: stableId(node, String(i)),
        heading: textOf(node) || "(untitled)",
        level: node.attrs?.level || 1,
        start: i,
        end: i,
        opaqueCount: 0,
      };
      sections.push(current);
      return;
    }
    if (!current) {
      current = {
        id: `intro`,
        heading: "(intro)",
        level: 0,
        start: i,
        end: i,
        opaqueCount: 0,
      };
      sections.push(current);
    }
    current.end = i;
    if (OPAQUE.has(node.type)) current.opaqueCount += 1;
  });
  return { sections, doc: rooted };
}

function sliceSectionHtml(doc, start, end) {
  const rooted = ensureLocalIds(doc);
  const nodes = (rooted.content || []).slice(start, end + 1);
  const html = nodes.map((node, i) => blockToHtml(node, String(start + i))).join("\n");
  return { html: `<div class="confluence-section">${html}</div>`, doc: rooted };
}

function htmlFragmentToAdf(html) {
  const root = parseHtml(`<div>${html || ""}</div>`);
  const out = [];
  for (const el of root.firstChild?.childNodes || root.childNodes || []) {
    const node = elementToAdf(el);
    if (Array.isArray(node)) out.push(...node);
    else if (node) out.push(node);
  }
  return out;
}

function textNodesFromEl(el) {
  if (el.nodeType === 3) {
    const t = (el.rawText || el.text || "").replace(/\s+/g, " ");
    if (!t.trim()) return [];
    return [{ type: "text", text: t }];
  }
  const tag = (el.rawTagName || "").toLowerCase();
  if (!tag) {
    return (el.childNodes || []).flatMap(textNodesFromEl);
  }
  if (tag === "br") return [{ type: "hardBreak" }];
  const kids = (el.childNodes || []).flatMap(textNodesFromEl);
  const mark =
    tag === "strong" || tag === "b"
      ? { type: "strong" }
      : tag === "em" || tag === "i"
        ? { type: "em" }
        : tag === "u"
          ? { type: "underline" }
          : tag === "s" || tag === "strike"
            ? { type: "strike" }
            : tag === "code"
              ? { type: "code" }
              : tag === "a" && el.getAttribute?.("href")
                ? { type: "link", attrs: { href: el.getAttribute("href") } }
                : null;
  if (!mark) return kids;
  return kids.map((n) => {
    if (n.type !== "text") return n;
    return { ...n, marks: [...(n.marks || []), mark] };
  });
}

function elementToAdf(el) {
  if (!el || el.nodeType === 3) {
    const t = (el?.rawText || el?.text || "").trim();
    if (!t) return null;
    return { type: "paragraph", content: [{ type: "text", text: t }] };
  }
  const tag = (el.rawTagName || "").toLowerCase();
  if (el.getAttribute?.("data-adf-opaque") === "true") return null;
  if (/^h[1-6]$/.test(tag)) {
    return {
      type: "heading",
      attrs: { level: Number(tag[1]) },
      content: textNodesFromEl(el),
    };
  }
  if (tag === "p" || tag === "div") {
    const content = textNodesFromEl(el);
    if (!content.length) return { type: "paragraph", content: [] };
    if (tag === "div") {
      const kids = (el.childNodes || []).map(elementToAdf).filter(Boolean).flat();
      if (kids.length) return kids;
    }
    return { type: "paragraph", content };
  }
  if (tag === "ul" || tag === "ol") {
    return {
      type: tag === "ul" ? "bulletList" : "orderedList",
      content: (el.childNodes || [])
        .filter((c) => (c.rawTagName || "").toLowerCase() === "li")
        .map((li) => ({
          type: "listItem",
          content: [{ type: "paragraph", content: textNodesFromEl(li) }],
        })),
    };
  }
  if (tag === "blockquote") {
    return {
      type: "blockquote",
      content: (el.childNodes || []).map(elementToAdf).filter(Boolean).flat(),
    };
  }
  if (tag === "hr") return { type: "rule" };
  const content = textNodesFromEl(el);
  return content.length ? { type: "paragraph", content } : null;
}

function applyAcceptedChanges(originalDoc, changes) {
  const doc = ensureLocalIds(originalDoc);
  const byId = new Map();
  (doc.content || []).forEach((node, i) => {
    byId.set(stableId(node, String(i)), { node, index: i });
  });

  const next = doc.content.slice();
  const sorted = [...changes].sort((a, b) => {
    const ia = byId.get(a.chunk_id)?.index ?? 0;
    const ib = byId.get(b.chunk_id)?.index ?? 0;
    return ib - ia;
  });

  for (const change of sorted) {
    if (change.approved === false) continue;
    const loc = byId.get(change.chunk_id);
    if (change.operation === "delete") {
      if (!loc) continue;
      if (OPAQUE.has(loc.node.type)) continue;
      next.splice(loc.index, 1);
      continue;
    }
    if (change.operation === "create") {
      const frag = htmlFragmentToAdf(change.new_html || "");
      const after = byId.get(change.insert_after_chunk_id);
      const at = after ? after.index + 1 : next.length;
      next.splice(at, 0, ...frag);
      continue;
    }
    if (change.operation === "edit") {
      if (!loc) continue;
      if (OPAQUE.has(loc.node.type)) continue;
      const frag = htmlFragmentToAdf(change.new_html || "");
      if (!frag.length) continue;
      next.splice(loc.index, 1, ...frag);
    }
  }

  return { type: "doc", version: 1, content: next };
}

function isOpaque(type) {
  return OPAQUE.has(type);
}

module.exports = {
  OPAQUE,
  isOpaque,
  textOf,
  ensureLocalIds,
  adfToHtml,
  listSections,
  sliceSectionHtml,
  htmlFragmentToAdf,
  applyAcceptedChanges,
  stableId,
};
