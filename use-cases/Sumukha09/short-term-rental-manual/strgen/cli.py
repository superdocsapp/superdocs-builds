"""STR Pack CLI — zero to a complete branded guest pack in under two minutes."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import APP_NAME, __version__
from .config import resolve_api_key
from .errors import StrGenError
from .i18n import LANGUAGES
from .mcp_client import SuperDocsMCP
from .models import BLOCK_KINDS, PHOTO_SECTIONS, Photo, Property, SharedBlock, new_id
from .pipeline import generate_pack
from .store import Store

# ------------------------------------------------------------------ styling

if os.name == "nt":
    os.system("")  # enable ANSI escapes on Windows terminals


class C:
    GREEN, RED, YELLOW, CYAN, DIM, BOLD, END = (
        "\033[92m", "\033[91m", "\033[93m", "\033[96m",
        "\033[2m", "\033[1m", "\033[0m")


def _ok(msg: str) -> None:
    print(f"{C.GREEN}[ok]{C.END} {msg}")


def _info(msg: str) -> None:
    print(f"{C.CYAN}>{C.END} {msg}")


def _warn(msg: str) -> None:
    print(f"{C.YELLOW}[!]{C.END} {msg}")


def _err(msg: str) -> None:
    print(f"{C.RED}[x]{C.END} {msg}")


def _head(title: str) -> None:
    print(f"\n{C.BOLD}{title}{C.END}\n{'-' * len(title)}")


def _client(args) -> SuperDocsMCP:
    key = resolve_api_key(getattr(args, "api_key", None),
                          getattr(args, "dotenv", ".env"))
    return SuperDocsMCP(api_key=key, endpoint=args.endpoint)


def _store(args) -> Store:
    return Store(getattr(args, "data", "data"))


def _parse_json_arg(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"--set must be valid JSON ({exc}). Example: "
            "--set '{\"password\": \"newpass\"}'") from exc
    if not isinstance(parsed, dict):
        raise ValueError("--set must be a JSON object")
    return parsed


# ------------------------------------------------------------------- doctor

def cmd_doctor(args) -> int:
    _head("SuperDocs connectivity")
    try:
        client = _client(args)
        started = time.time()
        healthy, detail = client.ping()
        ms = int((time.time() - started) * 1000)
        if healthy:
            _ok(f"MCP endpoint reachable ({ms} ms) - session established")
            _info(f"endpoint: {args.endpoint}")
            _info("api key:  ********" if client.api_key else "api key:  MISSING")
            return 0
        _err(detail)
        return 1
    except (StrGenError, Exception) as exc:
        _err(str(exc))
        _warn("check SUPERDOCS_API_KEY in your environment or .env file")
        return 1


# ------------------------------------------------------------------ demo

def cmd_demo(args) -> int:
    store = _store(args)
    existing = store.load_properties()
    if existing and not args.force:
        _warn("data directory already has properties; use --force to reseed")
        return 1
    from .seed import seed_demo_data
    prop_id = seed_demo_data(store, force=True)
    prop = store.get_property(prop_id)
    _ok(f"created shared content library "
        f"({len(store.find_blocks())} SharedBlocks)")
    _ok(f"created property '{prop.name}' ({prop.id})")
    print(f"""
{C.BOLD}Try it:{C.END}
  python main.py generate {prop.id} --lang en,es,fr --formats pdf,docx
""")
    return 0


# ---------------------------------------------------------------- properties

def cmd_property_create(args) -> int:
    store = _store(args)
    langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    bad = [l for l in langs if l not in LANGUAGES]
    if bad:
        _err(f"unknown languages: {', '.join(bad)}. Available: "
             f"{', '.join(sorted(LANGUAGES))}")
        return 1
    prop = Property(
        id=new_id("prop", args.name), name=args.name,
        tagline={"$i18n": {"(args.base or 'en')": args.tagline}} if args.tagline else {},
        address_lines=[a.strip() for a in (args.address or "").split("|") if a.strip()],
        contact_name=args.contact_name or "", contact_phone=args.contact_phone or "",
        contact_email=args.contact_email or "",
        paper_size=args.paper.upper(), base_lang=args.base or (langs[0] if langs else "en"),
        languages=langs or ["en"])
    store.create_property(prop)
    _ok(f"property created: {prop.name} (id: {C.BOLD}{prop.id}{C.END})")
    _info(f"next: python main.py block link {prop.id} wifi <block_id>")
    return 0


def cmd_property_list(args) -> int:
    props = _store(args).load_properties()
    if not props:
        _warn("no properties yet - run `python main.py demo` first")
        return 0
    _head(f"{len(props)} propert{'y' if len(props)==1 else 'ies'}")
    for p in props.values():
        linked = ", ".join(sorted(p.links)) or "no blocks linked"
        photos = f"{len(p.photos)} photos"
        print(f"  {C.BOLD}{p.id}{C.END}  {p.name}")
        print(f"    langs: {','.join(p.languages)}  |  {photos}  |  {linked}")
    return 0


def cmd_property_show(args) -> int:
    p = _store(args).get_property(args.property_id)
    _head(p.name)
    d = p.to_dict()
    for key in ("id", "name", "tagline", "address_lines", "languages", "base_lang",
                "paper_size", "links", "contact_name", "contact_phone"):
        print(f"  {key:<14}: {json.dumps(d.get(key), ensure_ascii=False)}")
    print(f"  photos        : {[ph.id + ':' + ph.section for ph in p.photos]}")
    ov = {k: sorted(v.keys()) for k, v in p.overrides.items()}
    print(f"  overrides     : {ov}")
    return 0


def cmd_property_set(args) -> int:
    store = _store(args)
    prop = store.get_property(args.property_id)
    updates = _parse_json_arg(args.set)
    if not updates:
        _err("--set requires a JSON object")
        return 1
    allowed = {"tagline", "address_lines", "contact_name", "contact_phone",
               "contact_email", "paper_size", "base_lang", "languages", "listing"}
    for key, value in updates.items():
        if key not in allowed:
            _err(f"'{key}' is not settable. Allowed: {', '.join(sorted(allowed))}")
            return 1
        setattr(prop, key, value)
    prop.touch()
    store.save_property(prop)
    _ok(f"updated '{prop.name}'")
    return 0


# -------------------------------------------------------------------- blocks

def cmd_block_list(args) -> int:
    blocks = _store(args).find_blocks(args.kind)
    if not blocks:
        _warn("no blocks yet - run `python main.py demo` or `block create`")
        return 0
    _head("SharedBlocks")
    props_by_block: dict[str, int] = {}
    for p in _store(args).load_properties().values():
        for bid in p.links.values():
            props_by_block[bid] = props_by_block.get(bid, 0) + 1
    for b in blocks:
        used = props_by_block.get(b.id, 0)
        print(f"  {C.BOLD}{b.id}{C.END}")
        print(f"    {b.kind:<15} v{b.version}  used by {used} propert"
              f"{'y' if used == 1 else 'ies'}  {C.DIM}{b.description}{C.END}")
    return 0


def cmd_block_create(args) -> int:
    store = _store(args)
    content = _parse_json_arg(args.set)
    block = SharedBlock(id=new_id("blk", args.name), kind=args.kind,
                        name=args.name, description=args.desc or "",
                        content=content)
    block.validate()
    store.save_block(block)
    _ok(f"SharedBlock '{block.name}' created ({block.kind})")
    _info(f"id: {block.id}")
    return 0


def cmd_block_show(args) -> int:
    b = _store(args).get_block(args.block_id)
    _head(b.name)
    print(f"  kind: {b.kind}   version: {b.version}   updated: {b.updated_at}")
    print(json.dumps(b.content, indent=2, ensure_ascii=False))
    return 0


def cmd_block_edit(args) -> int:
    store = _store(args)
    block = store.get_block(args.block_id)
    patch = _parse_json_arg(args.set)
    if not patch:
        _err("--set requires a JSON object")
        return 1
    from .assembly import deep_merge_copy
    merged = deep_merge_copy(block.content, patch)
    block.content = merged
    block.touch()

    users = store.properties_using_block(block.id)
    store.save_block(block)
    _ok(f"block '{block.id}' updated (now v{block.version})")
    if users:
        names = ", ".join(u.name for u in users)
        _ok(f"change propagated live to {len(users)} propert"
            f"{'y' if len(users) == 1 else 'ies'}: {names}")
    else:
        _warn("no properties currently reference this block")
    return 0


def cmd_block_link(args) -> int:
    store = _store(args)
    prop = store.get_property(args.property_id)
    block = store.get_block(args.block_id)
    if block.kind != args.kind:
        _err(f"block '{block.id}' is kind '{block.kind}', not '{args.kind}'")
        return 1
    prop.link_block(args.kind, block.id)
    store.save_property(prop)
    _ok(f"linked {args.kind} -> {block.id} for '{prop.name}'")
    return 0


def cmd_block_unlink(args) -> int:
    store = _store(args)
    prop = store.get_property(args.property_id)
    had = args.kind in prop.links
    prop.unlink_block(args.kind)
    store.save_property(prop)
    _ok(f"unlinked {args.kind}" + ("" if had else " (was already unlinked)"))
    _info("property overrides (if any) were kept - nothing was deleted")
    return 0


def cmd_override_set(args) -> int:
    """Write property-specific values into the override namespace."""
    store = _store(args)
    prop = store.get_property(args.property_id)
    patch = _parse_json_arg(args.set)
    if not patch:
        _err("--set requires a JSON object")
        return 1
    prop.set_override(args.kind, patch)
    store.save_property(prop)
    _ok(f"override saved for '{prop.name}' / {args.kind}")
    _info("these values now win over any shared-block edits")
    return 0


# --------------------------------------------------------------------- photos

def cmd_photo_add(args) -> int:
    store = _store(args)
    prop = store.get_property(args.property_id)
    path = Path(args.file)
    if not path.exists():
        _err(f"file not found: {path}")
        return 1
    caption: dict = {}
    if args.caption_en:
        caption = {"$i18n": {"en": args.caption_en}}
    photo = Photo(id=new_id("ph", path.stem), section=args.section,
                  caption=caption, local_path=str(path), alt=args.caption_en or "")
    prop.photos.append(photo)
    prop.touch()
    store.save_property(prop)
    _ok(f"photo added: {photo.id} ({photo.section})")
    _info("it will be uploaded automatically during `generate`")
    return 0


def cmd_photo_list(args) -> int:
    prop = _store(args).get_property(args.property_id)
    if not prop.photos:
        _warn("no photos yet")
        return 0
    for p in prop.photos:
        state = "remote" if p.url else ("local file" if p.local_path else "MISSING FILE")
        print(f"  {p.id:<28} {p.section:<10} {state}")
    return 0


# ------------------------------------------------------------------- generate

def cmd_generate(args) -> int:
    store = _store(args)
    prop = store.get_property(args.property_id)
    langs = ([l.strip() for l in args.lang.split(",") if l.strip()]
             if args.lang else list(prop.languages))
    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
    for fmt in formats:
        if fmt not in ("pdf", "docx"):
            _err(f"unsupported format '{fmt}' (use pdf and/or docx)")
            return 1
    client = _client(args)

    _head(f"Generating pack for '{prop.name}'")
    started = time.time()
    healthy, detail = client.ping()
    if not healthy:
        _err(f"SuperDocs unreachable: {detail}")
        return 1
    _ok(f"connected to SuperDocs ({LANGUAGES.get(langs[0], '')} pack incoming)")

    manifest = generate_pack(store, prop.id, langs, formats, args.out,
                             client, save_html=args.html, log=_info)
    elapsed = time.time() - started
    total = sum(len(e["files"]) for e in manifest["languages"])
    print()
    _ok(f"{total} files generated in {elapsed:.1f}s across "
        f"{len(manifest['languages'])} language(s)")
    for entry in manifest["languages"]:
        for f in entry["files"]:
            print(f"      {Path(f)}")
    print(f"\n{C.BOLD}Ready to hand to your guests.{C.END}")
    return 0


# ----------------------------------------------------------------------- app

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python main.py",
        description=f"{APP_NAME} - STR House Manual & Listing Pack generator")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--data", default="data", help="data directory (default ./data)")
    parser.add_argument("--endpoint", default="https://api.superdocs.app/mcp/")
    parser.add_argument("--api-key", default=None, help="SuperDocs API key "
                        "(else SUPERDOCS_API_KEY env or .env)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("doctor", help="check SuperDocs MCP connectivity")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("demo", help="seed a complete sample property + library")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("languages", help="list supported languages")
    def _langs(a):
        _head("Supported languages")
        print("  " + ", ".join(f"{c}={n}" for c, n in sorted(LANGUAGES.items())))
        return 0
    p.set_defaults(func=_langs)

    # property ------------------------------------------------------------
    p = sub.add_parser("property", help="manage properties")
    psub = p.add_subparsers(dest="subcmd", required=True)
    pc = psub.add_parser("create")
    pc.add_argument("name")
    pc.add_argument("--tagline", default="")
    pc.add_argument("--address", default="", help="'line1|line2|country'")
    pc.add_argument("--langs", default="en", help="comma list e.g. en,es,fr")
    pc.add_argument("--base", default=None, help="base/fallback language")
    pc.add_argument("--paper", default="A4", choices=["A4", "Letter"])
    pc.add_argument("--contact-name", dest="contact_name", default="")
    pc.add_argument("--contact-phone", dest="contact_phone", default="")
    pc.add_argument("--contact-email", dest="contact_email", default="")
    pc.set_defaults(func=cmd_property_create)
    pl = psub.add_parser("list"); pl.set_defaults(func=cmd_property_list)
    ps = psub.add_parser("show"); ps.add_argument("property_id")
    ps.set_defaults(func=cmd_property_show)
    pst = psub.add_parser("set"); pst.add_argument("property_id")
    pst.add_argument("--set", required=True, help='JSON, e.g. \'{"paper_size":"Letter"}\'')
    pst.set_defaults(func=cmd_property_set)

    # block ---------------------------------------------------------------
    p = sub.add_parser("block", help="manage SharedBlocks")
    bsub = p.add_subparsers(dest="subcmd", required=True)
    bl = bsub.add_parser("list"); bl.add_argument("kind", nargs="?", default=None)
    bl.set_defaults(func=cmd_block_list)
    bc = bsub.add_parser("create")
    bc.add_argument("kind", choices=BLOCK_KINDS)
    bc.add_argument("name")
    bc.add_argument("--desc", default="")
    bc.add_argument("--set", default="{}", help="initial content JSON")
    bc.set_defaults(func=cmd_block_create)
    bs = bsub.add_parser("show"); bs.add_argument("block_id")
    bs.set_defaults(func=cmd_block_show)
    be = bsub.add_parser("edit"); be.add_argument("block_id")
    be.add_argument("--set", required=True, help="JSON patch merged into content")
    be.set_defaults(func=cmd_block_edit)
    bli = bsub.add_parser("link"); bli.add_argument("property_id")
    bli.add_argument("kind", choices=BLOCK_KINDS); bli.add_argument("block_id")
    bli.set_defaults(func=cmd_block_link)
    bun = bsub.add_parser("unlink"); bun.add_argument("property_id")
    bun.add_argument("kind", choices=BLOCK_KINDS)
    bun.set_defaults(func=cmd_block_unlink)

    # override --------------------------------------------------------------
    p = sub.add_parser("override", help="property-specific values that always win")
    osub = p.add_subparsers(dest="subcmd", required=True)
    oo = osub.add_parser("set"); oo.add_argument("property_id")
    oo.add_argument("kind", choices=BLOCK_KINDS)
    oo.add_argument("--set", required=True)
    oo.set_defaults(func=cmd_override_set)

    # photo -----------------------------------------------------------------
    p = sub.add_parser("photo", help="manage property photos")
    phsub = p.add_subparsers(dest="subcmd", required=True)
    pa = phsub.add_parser("add"); pa.add_argument("property_id")
    pa.add_argument("--file", required=True)
    pa.add_argument("--section", default="other", choices=PHOTO_SECTIONS)
    pa.add_argument("--caption-en", dest="caption_en", default="")
    pa.set_defaults(func=cmd_photo_add)
    pll = phsub.add_parser("list"); pll.add_argument("property_id")
    pll.set_defaults(func=cmd_photo_list)

    # generate ----------------------------------------------------------------
    pg = sub.add_parser("generate", help="produce the full branded pack")
    pg.add_argument("property_id")
    pg.add_argument("--lang", default=None, help="e.g. en,es,fr (default: property languages)")
    pg.add_argument("--formats", default="pdf,docx", help="pdf,docx")
    pg.add_argument("--out", default="output")
    pg.add_argument("--html", action="store_true", help="also save HTML sources")
    pg.set_defaults(func=cmd_generate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except StrGenError as exc:
        _err(str(exc))
        return 1
    except FileNotFoundError as exc:
        _err(str(exc))
        return 1
    except KeyboardInterrupt:
        _warn("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
