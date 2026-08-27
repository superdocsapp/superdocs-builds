"""Generation pipelines: Property + SharedBlocks -> branded document packs.

Three artifacts per language:
  * House Manual  (session route: running headers/footers + Page X of Y)
  * Welcome Card  (ad-hoc export, single page)
  * Listing Pack  (ad-hoc export + paste-ready .txt files, always local)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .assembly import resolve
from .i18n import LANGUAGES, T
from .mcp_client import SuperDocsMCP
from .models import Property, SharedBlock, now_iso, slugify
from .render import build_listing_texts, render_card, render_listing, render_manual
from .store import Store

Log = Callable[[str], None]


def _furniture_texts(prop: Property, brand: dict, lang: str) -> tuple[str, str]:
    t = T(lang, prop.base_lang)
    header = f"{prop.name} - {t('house_manual')}".upper()
    operator = brand.get("operator_name") or prop.contact_name or ""
    footer = f"{operator} - {prop.contact_phone}".strip(" -") if prop.contact_phone \
        else (operator or t("house_manual"))
    return header[:120], footer[:120]


def ensure_remote_assets(store: Store, prop: Property,
                         client: SuperDocsMCP, log: Log) -> None:
    """Upload any photo/brand art that lacks a stable URL; persist results."""
    dirty_prop = False
    missing = [p for p in prop.photos
               if not p.url and (not p.local_path or not Path(p.local_path).exists())]
    if missing:
        names = ", ".join(p.id for p in missing)
        raise FileNotFoundError(
            f"Photos without a usable file or URL: {names}. "
            f"Add files via `python main.py photo add`.")

    for photo in prop.photos:
        if not photo.url:
            log(f"   uploading photo {photo.id} ...")
            result = client.upload_image_file(photo.local_path)
            photo.url = result["url"]
            dirty_prop = True

    blocks = store.load_blocks()
    block_dirty = False
    if "brand" in prop.links:
        brand_block = blocks.get(prop.links["brand"])
        if brand_block:
            logo_path = brand_block.content.get("logo_path")
            if logo_path and not brand_block.content.get("logo_url"):
                log("   uploading operator logo ...")
                result = client.upload_image_file(logo_path)
                brand_block.content["logo_url"] = result["url"]
                brand_block.touch()
                block_dirty = True
    if block_dirty:
        store.save_block(brand_block)
    if dirty_prop:
        store.save_property(prop)


def generate_pack(store: Store, prop_id: str, langs: list[str],
                  formats: list[str], out_root: str | Path,
                  client: SuperDocsMCP, save_html: bool = False,
                  log: Log = print) -> dict:
    unknown = [l for l in langs if l not in LANGUAGES]
    if unknown:
        raise ValueError(
            f"Unsupported language(s): {', '.join(unknown)}. "
            f"Available: {', '.join(sorted(LANGUAGES))}")
    prop = store.get_property(prop_id)
    blocks = store.load_blocks()
    ensure_remote_assets(store, prop, client, log)

    brand: dict = {}
    try:
        brand = resolve("brand", prop, blocks)
    except (KeyError, Exception):
        brand = {}

    slug = slugify(prop.name)
    paper = prop.paper_size if prop.paper_size in ("A4", "Letter") else "A4"
    base_dir = Path(out_root) / slug
    manifest = {"property": prop.name, "id": prop.id, "paper": paper,
                "generated_at": now_iso(), "languages": []}

    for lang in langs:
        t = T(lang, prop.base_lang)
        lang_dir = base_dir / lang
        lang_dir.mkdir(parents=True, exist_ok=True)
        entry: dict = {"lang": lang, "files": []}
        log(f"-> {LANGUAGES[lang]} ({lang})")

        manual_html = render_manual(prop, blocks, lang)
        card_html = render_card(prop, blocks, lang)
        listing_html = render_listing(prop, blocks, lang)

        # paste-ready listing copy is always written locally
        texts = build_listing_texts(prop, blocks, lang)
        for name, text in texts.items():
            path = lang_dir / f"listing-{name}.txt"
            path.write_text(text, encoding="utf-8")
            entry["files"].append(str(path))
        counts = {k: len(v) for k, v in texts.items()}
        entry["listing_chars"] = counts
        log(f"   listing copy: short {counts['short']}, "
            f"airbnb {counts['airbnb']}, booking {counts['booking']} chars")

        if save_html:
            for name, html_src in (("house-manual", manual_html),
                                   ("welcome-card", card_html),
                                   ("listing-pack", listing_html)):
                path = lang_dir / f"{name}-{lang}.html"
                path.write_text(html_src, encoding="utf-8")
                entry["files"].append(str(path))

        # ---- House Manual via session (running heads + exports) ------------
        wanted = [f for f in ("pdf", "docx") if f in formats]
        if wanted:
            # Client-chosen session ids are first-class: this creates a
            # persistent, browsable copy of every manual we generate.
            session_id = f"strpack-{slug}-{lang}-{int(time.time())}"
            client.upload_document(session_id, manual_html, stem := f"{slug}-house-manual-{lang}" + ".html")
            header_text, footer_text = _furniture_texts(prop, brand, lang)
            ok, note = client.add_running_furniture(session_id, header_text, footer_text)
            log(f"   running heads: {'set' if ok else 'skipped'}")
            for fmt in wanted:
                url = client.request_download(session_id, fmt,
                                              stem.removesuffix(".html"),
                                              paper_size=paper)
                dest = lang_dir / f"{stem.removesuffix('.html')}.{fmt}"
                client.download(url, dest)
                entry["files"].append(str(dest))
                log(f"   house manual -> {dest.name} ({dest.stat().st_size // 1024} KB)")

        # ---- Card & Listing via ad-hoc export ------------------------------
        adhoc = [("welcome-card", card_html), ("listing-pack", listing_html)]
        for name, html_src in adhoc:
            for fmt in wanted:
                stem = f"{slug}-{name}-{lang}"
                url = client.export_adhoc(html_src, fmt, stem, paper_size=paper)
                dest = lang_dir / f"{stem}.{fmt}"
                client.download(url, dest)
                entry["files"].append(str(dest))
                log(f"   {name.replace('-', ' ')} -> {dest.name} "
                    f"({dest.stat().st_size // 1024} KB)")

        manifest["languages"].append(entry)

    manifest_path = base_dir / "manifest.json"
    base_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                             encoding="utf-8")
    return manifest
