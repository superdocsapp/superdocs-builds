import html
from html.parser import HTMLParser

from .text import apply_text_rules

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}
SKIP_TEXT = {"script", "style", "pre", "code", "textarea"}
BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "th", "td", "blockquote"}


class Node:
    __slots__ = ("tag", "attrs", "children", "doctype")

    def __init__(self, tag: str, attrs: dict | None = None, children=None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children = children if children is not None else []
        self.doctype = None

    def __repr__(self) -> str:
        return f"<{self.tag} {self.attrs} {len(self.children)} children>"


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("html")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs))
        self.stack[-1].children.append(node)
        if tag not in VOID_ELEMENTS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if data:
            self.stack[-1].children.append(data)

    def handle_decl(self, decl):
        if decl.strip().lower().startswith("doctype"):
            self.root.doctype = f"<!{decl.strip()}>"


def parse_html(text: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(text)
    return builder.root


def serialize(node: Node) -> str:
    if isinstance(node, str):
        return html.escape(node, quote=False)
    attrs = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in node.attrs.items())
    if node.tag in VOID_ELEMENTS:
        return f"<{node.tag}{attrs}>"
    inner = "".join(serialize(c) for c in node.children)
    prefix = f"{node.doctype}\n" if node.doctype else ""
    return f"{prefix}<{node.tag}{attrs}>{inner}</{node.tag}>"


def walk(node: Node):
    yield node
    for child in node.children:
        if isinstance(child, Node):
            yield from walk(child)


def apply_text_rules_to_tree(tree: Node, profile, stats) -> None:
    def visit(node: Node, skip_depth: int) -> None:
        for idx, child in enumerate(node.children):
            if isinstance(child, str):
                if skip_depth == 0 and child.strip():
                    new_text, node_stats = apply_text_rules(child, profile)
                    if new_text != child:
                        node.children[idx] = new_text
                    for key in stats:
                        stats[key]["count"] += node_stats[key]["count"]
                        remaining = 8 - len(stats[key]["samples"])
                        stats[key]["samples"].extend(node_stats[key]["samples"][:remaining])
            elif child.tag in SKIP_TEXT:
                visit(child, skip_depth + 1)
            else:
                visit(child, skip_depth)

    visit(tree, 0)


def build_css(profile) -> str:
    p = profile.page
    css = [
        "@page {",
        f"  size: {p['width_mm']}mm {p['height_mm']}mm;",
        f"  margin: {p['margin_top_mm']}mm {p['margin_right_mm']}mm {p['margin_bottom_mm']}mm {p['margin_left_mm']}mm;",
        "}",
        f"body {{ font-family: {profile.body_font}, {profile.latin_font};"
        f" font-size: {profile.body_size_pt}pt; line-height: {profile.line_spacing};"
        f" text-align: {profile.text_align}; }}",
        f"h1, h2, h3, h4, h5, h6 {{ font-family: {profile.heading_font}, {profile.latin_font};"
        f"{' font-weight: bold;' if profile.heading_bold else ''} }}",
        f"p {{ margin: {profile.paragraph_spacing_pt}pt 0; }}",
        "table { border-collapse: collapse; width: 100%; }",
        "th, td { border: 0.75pt solid #333; padding: 4pt 6pt; }",
        "th { font-family: " + profile.heading_font + "; }",
        profile.css_extra,
    ]
    return "\n".join(css)


def apply_html_structure(tree: Node, profile) -> None:
    tree.attrs["lang"] = profile.lang
    style = Node("style", children=["\n" + build_css(profile) + "\n"])
    head = next((n for n in tree.children if isinstance(n, Node) and n.tag == "head"), None)
    if head is None:
        head = Node("head")
        tree.children.insert(0, head)
    head.children.append(style)
    title = next((n for n in walk(tree) if isinstance(n, Node) and n.tag == "title"), None)
    if title is None:
        head.children.insert(0, Node("title", children=["Document"]))


def collect_plain_text(node) -> str:
    if isinstance(node, str):
        return node
    return "".join(collect_plain_text(c) for c in node.children)


def collect_blocks(tree: Node) -> list[str]:
    blocks = []
    for node in walk(tree):
        if isinstance(node, Node) and node.tag in BLOCK_TAGS:
            text = collect_plain_text(node).strip()
            if text:
                blocks.append(text)
    return blocks


def find_title(tree: Node) -> str:
    for node in walk(tree):
        if isinstance(node, Node) and node.tag == "title":
            text = collect_plain_text(node).strip()
            if text:
                return text
    for node in walk(tree):
        if isinstance(node, Node) and node.tag == "h1":
            text = collect_plain_text(node).strip()
            if text:
                return text
    return "Document"
