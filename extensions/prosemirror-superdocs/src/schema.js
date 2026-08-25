import { Schema } from "prosemirror-model";
import { schema as basicSchema } from "prosemirror-schema-basic";
import { addListNodes } from "prosemirror-schema-list";

function withChunkId(spec) {
  const attrs = { ...(spec.attrs || {}), "data-chunk-id": { default: null } };

  const parseDOM = (spec.parseDOM || []).map((rule) => ({
    ...rule,
    getAttrs: (node) => {
      const base =
        typeof rule.getAttrs === "function"
          ? rule.getAttrs(node) || {}
          : rule.attrs || {};
      if (typeof node === "string") return base;
      return { ...base, "data-chunk-id": node.getAttribute("data-chunk-id") };
    },
  }));

  const originalToDOM = spec.toDOM;
  const toDOM = originalToDOM
    ? (node) => {
        const out = originalToDOM(node);
        if (!Array.isArray(out)) return out;
        const [tag, maybeAttrs, ...rest] = out;
        const chunkId = node.attrs["data-chunk-id"];
        if (!chunkId) return out;
        
        const isAttrs =
          maybeAttrs &&
          typeof maybeAttrs === "object" &&
          !Array.isArray(maybeAttrs) &&
          !maybeAttrs.nodeType;
          
        return isAttrs
          ? [tag, { ...maybeAttrs, "data-chunk-id": chunkId }, ...rest]
          : [tag, { "data-chunk-id": chunkId }, maybeAttrs, ...rest];
      }
    : undefined;

  return { ...spec, attrs, parseDOM, toDOM };
}

const chunkWrapperSpec = {
  group: "block",
  content: "block+",
  attrs: { "data-chunk-id": { default: null } },
  parseDOM: [{
    tag: "div[data-chunk-id]",
    getAttrs: (node) =>
      typeof node === "string"
        ? {}
        : { "data-chunk-id": node.getAttribute("data-chunk-id") },
  }],
  toDOM: (node) => [
    "div",
    node.attrs["data-chunk-id"]
      ? { "data-chunk-id": node.attrs["data-chunk-id"] }
      : {},
    0,
  ],
};

let nodes = basicSchema.spec.nodes;
for (const name of ["paragraph", "blockquote", "heading", "horizontal_rule", "code_block"]) {
  const spec = nodes.get(name);
  if (spec) nodes = nodes.update(name, withChunkId(spec));
}
nodes = addListNodes(nodes, "paragraph block*", "block");
for (const name of ["ordered_list", "bullet_list", "list_item"]) {
  const spec = nodes.get(name);
  if (spec) nodes = nodes.update(name, withChunkId(spec));
}
nodes = nodes.addToEnd("chunk_wrapper", chunkWrapperSpec);

export const schema = new Schema({ nodes, marks: basicSchema.spec.marks });
