import json
from dataclasses import dataclass, field
from pathlib import Path

from . import htmltree, markdown
from .checklist import build_checklist_data, render_checklist_md
from .compare import build_comparison
from .docx_io import render_docx
from .profile import Profile, load_profile
from .text import _new_stats


@dataclass
class AdaptResult:
    out_html: Path
    out_docx: Path | None
    comparison_html: Path
    checklist_json: Path
    checklist_md: Path
    profile: Profile
    stats: dict = field(default_factory=dict)
    title: str = ""


def _parse_input(raw: str, suffix: str) -> htmltree.Node:
    if suffix == ".md":
        return htmltree.parse_html(markdown.md_to_html(raw))
    return htmltree.parse_html(raw)


def adapt(
    input_path: str | Path,
    locale: str = "ja",
    out_dir: str | Path = "out",
    formats=("html", "docx"),
    reverse: bool = False,
) -> AdaptResult:
    input_path = Path(input_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    profile = load_profile(locale, reverse)
    raw = input_path.read_text(encoding="utf-8")
    original = _parse_input(raw, input_path.suffix.lower())
    tree = _parse_input(raw, input_path.suffix.lower())
    stats = _new_stats()
    htmltree.apply_text_rules_to_tree(tree, profile, stats)
    htmltree.apply_html_structure(tree, profile)
    title = htmltree.find_title(original)

    out_html = out_dir / "adapted.html"
    out_html.write_text(htmltree.serialize(tree), encoding="utf-8")

    out_docx = None
    if "docx" in formats:
        out_docx = out_dir / "adapted.docx"
        render_docx(tree, profile, out_docx)

    comparison_html = out_dir / "comparison.html"
    comparison_html.write_text(
        build_comparison(original, tree, title), encoding="utf-8"
    )

    data = build_checklist_data(profile, stats, htmltree.build_css(profile))
    checklist_json = out_dir / "checklist.json"
    checklist_json.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    checklist_md = out_dir / "checklist.md"
    checklist_md.write_text(render_checklist_md(data), encoding="utf-8")

    return AdaptResult(
        out_html=out_html,
        out_docx=out_docx,
        comparison_html=comparison_html,
        checklist_json=checklist_json,
        checklist_md=checklist_md,
        profile=profile,
        stats=stats,
        title=title,
    )
