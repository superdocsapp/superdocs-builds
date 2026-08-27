"""Platform listing pack: conversion-focused copy for Airbnb / Vrbo /
Booking.com plus a pretty printable dossier."""

from __future__ import annotations

from typing import Any

from strgen.i18n import T
from strgen.models import Property, resolve_text
from strgen.assembly import resolve, strip_i18n

from .theme import base_css, brand_of, esc, FONT_DISPLAY, FONT_BODY

# Soft character targets per platform (informational; enforced as warnings)
PLATFORM_LIMITS = {
    "airbnb": 1000,
    "vrbo": 4000,
    "booking": 2000,
    "short": 280,
}

_LABELS: dict[str, dict[str, str]] = {
    "highlights":     {"en": "What makes it special", "es": "Lo que lo hace especial", "fr": "Ce qui le rend unique", "de": "Was es besonders macht", "it": "Cosa lo rende speciale", "pt": "O que o torna especial", "nl": "Wat het bijzonder maakt"},
    "space":          {"en": "The space", "es": "El espacio", "fr": "Le logement", "de": "Die Unterkunft", "it": "Gli spazi", "pt": "O espaço", "nl": "De ruimte"},
    "guest_access":   {"en": "Guest access", "es": "Acceso de los huéspedes", "fr": "Accès des voyageurs", "de": "Zugang für Gäste", "it": "Accesso per gli ospiti", "pt": "Acesso dos hóspedes", "nl": "Toegang voor gasten"},
    "neighborhood":   {"en": "The neighbourhood", "es": "El barrio", "fr": "Le quartier", "de": "Die Nachbarschaft", "it": "Il quartiere", "pt": "A vizinhança", "nl": "De buurt"},
    "transit":        {"en": "Getting around", "es": "Cómo moverse", "fr": "Se déplacer", "de": "Fortbewegung", "it": "Come muoversi", "pt": "Como circular", "nl": "Vervoer"},
    "amenities":      {"en": "Amenities", "es": "Servicios", "fr": "Équipements", "de": "Ausstattung", "it": "Servizi", "pt": "Comodidades", "nl": "Voorzieningen"},
    "rules_label":    {"en": "Good to know (house rules)", "es": "Bueno saber (normas)", "fr": "Bon à savoir (règlement)", "de": "Gut zu wissen (Hausregeln)", "it": "Buono a sapersi (regole)", "pt": "Bom saber (regras)", "nl": "Goed om te weten (huisregels)"},
}

_CTA = {
    "en": "We can't wait to welcome you.",
    "es": "Estamos deseando recibirte.",
    "fr": "Nous avons hâte de vous accueillir.",
    "de": "Wir freuen uns auf Ihren Besuch!",
    "it": "Non vediamo l'ora di accoglierti.",
    "pt": "Mal podemos esperar para recebê-lo.",
    "nl": "We kijken ernaar uit je te verwelkomen.",
}


def _lbl(key: str, t: T) -> str:
    row = _LABELS[key]
    return row.get(t.lang) or row["en"]


def _bullets(items: list[Any], lang: str, base: str) -> list[str]:
    out = []
    for item in items:
        text = resolve_text(item, lang, base) if isinstance(item, dict) else str(item)
        if text:
            out.append(text)
    return out


def _listing_data(prop: Property, blocks: dict, lang: str) -> dict[str, Any]:
    t = T(lang, prop.base_lang)
    data = prop.listing or {}
    rules = None
    try:
        rules = resolve("rules", prop, blocks)
    except KeyError:
        pass

    def g(key: str) -> str:
        return resolve_text(data.get(key), lang, prop.base_lang)

    selling = _bullets(data.get("selling_points", []), lang, prop.base_lang)
    unique = _bullets(data.get("unique_features", []), lang, prop.base_lang)
    amenities = [a for a in data.get("amenities", []) if a]

    paragraphs: list[tuple[str | None, list[str]]] = []
    if g("summary"):
        paragraphs.append((None, [g("summary")]))
    if selling:
        paragraphs.append((_lbl("highlights", t), ["• " + b for b in selling]))
    if g("space"):
        paragraphs.append((_lbl("space", t), [g("space")]))
    if unique:
        paragraphs.append((None, ["• " + b for b in unique]))
    if g("guest_access"):
        paragraphs.append((_lbl("guest_access", t), [g("guest_access")]))
    if g("neighborhood"):
        paragraphs.append((_lbl("neighborhood", t), [g("neighborhood")]))
    if g("transit"):
        paragraphs.append((_lbl("transit", t), [g("transit")]))
    if amenities:
        paragraphs.append((_lbl("amenities", t), ["• " + a for a in amenities]))

    rules_bits: list[str] = []
    if rules:
        for r in rules.get("rules", []):
            title = resolve_text(r.get("title"), lang, prop.base_lang) if isinstance(r, dict) else str(r)
            if title:
                rules_bits.append(title)
        quiet = rules.get("quiet_hours")
        if quiet:
            rules_bits.append(f"{_quiet_label(t.lang)}: {quiet}")
    if rules_bits:
        paragraphs.append((_lbl("rules_label", t), ["• " + r for r in rules_bits]))

    long_desc = f"{prop.name} — {resolve_text(prop.tagline, lang, prop.base_lang)}\n\n"
    long_desc += "\n\n".join(
        (f"{heading}\n" + "\n".join(lines)) if heading else "\n".join(lines)
        for heading, lines in paragraphs
    )
    long_desc += "\n\n" + _CTA.get(t.lang, _CTA["en"])

    first_point = selling[0] if selling else g("summary")[:80]
    short = (f"{resolve_text(prop.tagline, lang, prop.base_lang)} "
             f"{first_point} {_CTA.get(t.lang, _CTA['en'])}")

    return {"long": long_desc, "short": short, "name": prop.name,
            "tagline": resolve_text(prop.tagline, lang, prop.base_lang)}


def _quiet_label(lang: str) -> str:
    from strgen.i18n import STRINGS
    return STRINGS.get(lang, STRINGS["en"]).get("quiet_hours", "Quiet hours")


def build_listing_texts(prop: Property, blocks: dict, lang: str) -> dict[str, str]:
    """Paste-ready plain-text versions keyed by platform."""
    data = _listing_data(prop, blocks, lang)
    texts = {"short": data["short"], "airbnb": data["long"],
             "vrbo": data["long"], "booking": data["long"]}
    return texts


def _count_html(text: str, limit: int, t: T) -> str:
    over = len(text) > limit
    cls = ' class="over"' if over else ""
    suffix = f' <span{cls}>(limit {limit:,})</span>' if over else ""
    return f'{len(text):,} {esc(t("characters"))}{suffix}'


def render_listing(prop: Property, blocks: dict, lang: str) -> str:
    from datetime import datetime
    t = T(lang, prop.base_lang)
    brand = brand_of(resolve("brand", prop, blocks)) if ("brand" in prop.links or "brand" in prop.overrides) \
        else brand_of(None)
    data = _listing_data(prop, blocks, lang)

    css = base_css(brand) + f"""
    .doc-head {{ border-bottom: 3px solid {brand['primary']}; padding-bottom: 12px;
      margin-bottom: 18px; display: flex; justify-content: space-between;
      align-items: flex-end; }}
    .doc-head h1 {{ font-size: 30px; }}
    .doc-head .sub {{ color: {brand['muted']}; font-size: 11.5px;
      letter-spacing: 2.5px; text-transform: uppercase; }}
    .copy {{ white-space: pre-wrap; font-size: 13px; line-height: 1.65;
      background: {brand['sand']}; border-radius: 10px; padding: 16px 18px; }}
    .platform {{ margin-top: 18px; page-break-inside: avoid; }}
    .platform h3 {{ font-size: 17px; display: flex; justify-content: space-between;
      align-items: baseline; }}
    .count {{ font-family: {FONT_BODY}; font-size: 11px; color: {brand['muted']};
      font-weight: 600; letter-spacing: .5px; }}
    .over {{ color: {brand['accent']}; font-weight: 800; }}
    """

    platforms: list[tuple[str, str]] = [
        (t("short_blurb"), data["short"]),
        ("Airbnb", data["long"]),
        ("Vrbo", data["long"]),
        ("Booking.com", data["long"]),
    ]
    limits = [PLATFORM_LIMITS["short"], PLATFORM_LIMITS["airbnb"],
              PLATFORM_LIMITS["vrbo"], PLATFORM_LIMITS["booking"]]

    platform_blocks = "".join(
        f'<div class="platform"><h3>{esc(name)}'
        f'<span class="count">{_count_html(text, lim, t)}</span></h3>'
        f'<div class="copy">{esc(text)}</div></div>'
        for (name, text), lim in zip(platforms, limits)
    )

    now = datetime.now()
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'/><title>",
        esc(f"{prop.name} — {t('listing_pack')}"), "</title><style>", css,
        "</style></head><body>",
        f'<div class="doc-head"><div><h1>{esc(prop.name)}</h1>'
        f'<div class="sub">{esc(t("listing_pack"))} · {esc(data["tagline"])}</div></div>'
        f'<div class="sub">{esc(t.month_year(now.year, now.month))}</div></div>',
        platform_blocks,
        "</body></html>",
    ]
    return "".join(parts)


_ = strip_i18n  # keep import referenced for API completeness
