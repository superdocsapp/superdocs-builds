RULE_LABELS = {
    "punctuation": "Punctuation substitution",
    "quotes": "Quote substitution",
    "thin_spaces": "Thin-space around Latin and digits",
    "kinsoku": "Kinsoku punctuation attachment",
    "halfwidth": "Half-width digit/letter conversion",
}


def build_checklist_data(profile, stats: dict, css: str) -> dict:
    page = profile.page
    return {
        "locale": profile.name,
        "label": profile.label,
        "direction": profile.direction,
        "lang": profile.lang,
        "styles": {
            "body_font": profile.body_font,
            "heading_font": profile.heading_font,
            "latin_font": profile.latin_font,
            "body_size_pt": profile.body_size_pt,
            "heading_sizes_pt": profile.heading_sizes_pt,
            "heading_bold": profile.heading_bold,
            "line_spacing": profile.line_spacing,
            "paragraph_spacing_pt": profile.paragraph_spacing_pt,
            "text_align": profile.text_align,
        },
        "page": page,
        "rules": {
            key: {"count": stats[key]["count"], "samples": stats[key]["samples"]}
            for key in RULE_LABELS
        },
        "css": css,
    }


def _rule_md(key: str, rule: dict) -> str:
    lines = [f"### {RULE_LABELS[key]}", "", f"Applied: **{rule['count']}** change(s)", ""]
    if rule["samples"]:
        lines.append("Examples:")
        lines.append("")
        lines.append("| Before | After |")
        lines.append("| --- | --- |")
        for before, after in rule["samples"]:
            lines.append(f"| `{before}` | `{after}` |")
        lines.append("")
    return "\n".join(lines)


def render_checklist_md(data: dict) -> str:
    p = data["page"]
    s = data["styles"]
    out = [
        f"# Typography adaptation checklist - {data['label']} ({data['locale']})",
        "",
        f"- Locale / language: `{data['locale']}` / `{data['lang']}`",
        f"- Direction: `{data['direction']}`",
        "",
        "## Page geometry",
        "",
        f"- Page size: {p['width_mm']} x {p['height_mm']} mm",
        f"- Margins: top {p['margin_top_mm']} mm, bottom {p['margin_bottom_mm']} mm, left {p['margin_left_mm']} mm, right {p['margin_right_mm']} mm",
        "",
        "## Typeface and layout",
        "",
        f"- Body font: `{s['body_font']}`",
        f"- Heading font: `{s['heading_font']}`",
        f"- Latin fallback: `{s['latin_font']}`",
        f"- Body size: {s['body_size_pt']} pt",
        f"- Heading sizes: " + ", ".join(f"{k} {v} pt" for k, v in s["heading_sizes_pt"].items()),
        f"- Heading bold: {s['heading_bold']}",
        f"- Line spacing: {s['line_spacing']}",
        f"- Paragraph spacing: {s['paragraph_spacing_pt']} pt",
        f"- Text alignment: {s['text_align']}",
        "",
        "## Rules applied",
        "",
    ]
    for key in RULE_LABELS:
        out.append(_rule_md(key, data["rules"][key]))
    out.append("## CSS emitted")
    out.append("")
    out.append("```css")
    out.append(data["css"])
    out.append("```")
    out.append("")
    return "\n".join(out)
