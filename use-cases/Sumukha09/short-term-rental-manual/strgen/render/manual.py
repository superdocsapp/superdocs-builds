"""Guest House Manual renderer — the star deliverable.

Layout contract: every numbered section opens with an explicit page break,
so pagination is IDENTICAL across languages. Photos occupy fixed slots.
Only words change between language editions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from strgen.i18n import LANGUAGES, T
from strgen.models import Photo, Property, resolve_text
from strgen.assembly import resolve

from .theme import base_css, brand_of, esc, FONT_DISPLAY

SECTION_ORDER = ["arrival", "wifi", "appliances", "rules",
                 "recommendations", "emergency", "floorplan"]

ROOM_LABELS: dict[str, dict[str, str]] = {
    "living":     {"en": "Living room", "es": "Salón", "fr": "Séjour", "de": "Wohnzimmer", "it": "Soggiorno", "pt": "Sala", "nl": "Woonkamer"},
    "kitchen":    {"en": "Kitchen", "es": "Cocina", "fr": "Cuisine", "de": "Küche", "it": "Cucina", "pt": "Cozinha", "nl": "Keuken"},
    "bedroom1":   {"en": "Bedroom 1", "es": "Dormitorio 1", "fr": "Chambre 1", "de": "Schlafzimmer 1", "it": "Camera 1", "pt": "Quarto 1", "nl": "Slaapkamer 1"},
    "bedroom2":   {"en": "Bedroom 2", "es": "Dormitorio 2", "fr": "Chambre 2", "de": "Schlafzimmer 2", "it": "Camera 2", "pt": "Quarto 2", "nl": "Slaapkamer 2"},
    "bathroom":   {"en": "Bathroom", "es": "Baño", "fr": "Salle de bain", "de": "Bad", "it": "Bagno", "pt": "Casa de banho", "nl": "Badkamer"},
    "terrace":    {"en": "Terrace", "es": "Terraza", "fr": "Terrasse", "de": "Terrasse", "it": "Terrazza", "pt": "Terraço", "nl": "Terras"},
    "pool":       {"en": "Pool", "es": "Piscina", "fr": "Piscine", "de": "Pool", "it": "Piscina", "pt": "Piscina", "nl": "Zwembad"},
    "dining":     {"en": "Dining", "es": "Comedor", "fr": "Salle à manger", "de": "Essbereich", "it": "Pranzo", "pt": "Jantar", "nl": "Eetkamer"},
    "entrance":   {"en": "Entrance", "es": "Entrada", "fr": "Entrée", "de": "Eingang", "it": "Ingresso", "pt": "Entrada", "nl": "Ingang"},
}


def _room_label(name: str, t: T) -> str:
    table = ROOM_LABELS.get(name.lower())
    if table:
        return table.get(t.lang) or table["en"]
    return name


def _i(node: Any, lang: str, base: str) -> str:
    return resolve_text(node, lang, base)


# ---------------------------------------------------------------- components

def _kicker(num: int, label: str) -> str:
    return (f'<div class="kicker"><span class="num">{num:02d}</span>'
            f'<span class="lbl">{esc(label)}</span></div>')


def _stat(k: str, v: str, big: bool = False) -> str:
    cls = "code-big" if big else "v"
    return f'<div class="stat"><div class="k">{esc(k)}</div><div class="{cls}">{esc(v)}</div></div>'


def _figure(photo: Photo, lang: str, base: str, tag: str = "") -> str:
    if not photo.url:
        return ""
    cap = _i(photo.caption, lang, base)
    cap_html = f"<figcaption>{f'<b>{esc(tag)}</b>' if tag else ''}{esc(cap)}</figcaption>" if cap else ""
    alt = esc(photo.alt or cap)
    return f'<figure class="photo"><img src="{esc(photo.url)}" alt="{alt}"/>{cap_html}</figure>'


def _duo(photos: list[Photo], lang: str, base: str) -> str:
    usable = [p for p in photos if p.url][:2]
    if len(usable) < 2:
        return _figure(usable[0], lang, base) if usable else ""
    cells = "".join(_figure(p, lang, base) for p in usable)
    return f'<div class="photo-duo">{cells}</div>'


def _floorplan_svg(prop: Property, lang: str, b: dict[str, Any]) -> str:
    rooms = prop.floorplan
    if not rooms:
        return ""
    min_x = min(r.x for r in rooms)
    min_y = min(r.y for r in rooms)
    max_x = max(r.x + r.w for r in rooms)
    max_y = max(r.y + r.h for r in rooms)
    span_x, span_y = max_x - min_x, max_y - min_y
    target_w, target_h = 620.0, 400.0
    scale = min(target_w / span_x, target_h / span_y)
    off_x = (target_w - span_x * scale) / 2 + 10
    off_y = (target_h - span_y * scale) / 2 + 10

    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {target_w + 20} {target_h + 20}" '
             f'width="100%" role="img">']
    parts.append('<defs><pattern id="grid" width="20" height="20" patternUnits="userSpaceOnUse">'
                 '<path d="M 20 0 L 0 0 0 20" fill="none" stroke="#232A3114" stroke-width="1"/>'
                 '</pattern></defs>')
    parts.append(f'<rect x="0" y="0" width="{target_w + 20}" height="{target_h + 20}" fill="#FFFFFF"/>')
    parts.append(f'<rect x="10" y="10" width="{target_w}" height="{target_h}" fill="url(#grid)" stroke="none"/>')

    for idx, r in enumerate(rooms):
        x = off_x + (r.x - min_x) * scale
        y = off_y + (r.y - min_y) * scale
        w, h = r.w * scale, r.h * scale
        fill = "#F7F2EA" if idx % 2 == 0 else "#FFFFFF"
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                     f'fill="{fill}" stroke="#232A31" stroke-width="3" rx="2"/>')
        label = _room_label(r.name, T(lang))
        fs = max(11.0, min(15.0, min(w, h) / 5))
        parts.append(f'<text x="{x + w / 2:.1f}" y="{y + h / 2:.1f}" text-anchor="middle" '
                     f'dominant-baseline="middle" font-family=\'Segoe UI,Arial\' '
                     f'font-size="{fs:.0f}" font-weight="600" fill="#232A31">{esc(label)}</text>')

    # north arrow
    nx, ny = target_w - 6, 34
    parts.append(f'<g transform="translate({nx},{ny})">'
                 f'<circle r="13" fill="#FFFFFF" stroke="#232A3155" stroke-width="1.5"/>'
                 f'<path d="M 0,-8 L 5,7 L 0,3.5 L -5,7 Z" fill="{b["accent"]}"/>'
                 f'<text y="-16" text-anchor="middle" font-size="10" font-weight="800" '
                 f'fill="#68717A">N</text></g>')
    parts.append("</svg>")
    return "".join(parts)


def _qr_block(wifi: dict[str, Any]) -> str:
    from strgen import qr as qrmod
    ssid = str(wifi.get("ssid", ""))
    password = str(wifi.get("password", ""))
    payload = qrmod.wifi_payload(ssid, password)
    matrix = qrmod.make(payload)
    svg = qrmod.svg(matrix, module_px=4)
    return f'<div class="qr-wrap">{svg}<div class="qr-cap">WiFi QR</div></div>'


# ------------------------------------------------------------------- render

def render_manual(prop: Property, blocks: dict, lang: str) -> str:
    """Full standalone HTML document for one language edition."""
    t = T(lang, prop.base_lang)
    brand = brand_of(resolve("brand", prop, blocks)) if ("brand" in prop.links or "brand" in prop.overrides) \
        else brand_of(None)

    arrival = resolve("arrival", prop, blocks)
    wifi = resolve("wifi", prop, blocks)
    appliances = resolve("appliances", prop, blocks)
    rules = resolve("rules", prop, blocks)
    recs = resolve("recommendations", prop, blocks)
    emergency = resolve("emergency", prop, blocks)

    photos_by_section: dict[str, list[Photo]] = {}
    for p in prop.photos:
        photos_by_section.setdefault(p.section, []).append(p)

    now = datetime.now()
    edition = f"{t('edition')} · {t.month_year(now.year, now.month)} · {LANGUAGES.get(lang, lang)}"
    address = "<br/>".join(esc(a) for a in prop.address_lines)
    hero = next(iter(photos_by_section.get("cover", [])), None)
    logo = (f'<img src="{esc(brand["logo_url"])}" alt="logo"/>'
            if brand.get("logo_url") else "")
    operator = esc(brand.get("operator_name") or "")

    # ------------------------------------------------------------- cover
    html_parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'/><title>",
        esc(prop.name), "</title><style>", base_css(brand), "</style></head><body>",
        '<div class="cover">',
        f'<div class="cover-top"><div class="brandmark">{logo}<span>{operator}</span></div>'
        f'<div class="cover-edition">{esc(edition)}</div></div>',
        '<div class="cover-rule"></div>',
        f'<h1 class="cover-title">{esc(prop.name)}</h1>',
        f'<p class="cover-tagline">{esc(_i(prop.tagline, lang, prop.base_lang))}</p>',
    ]
    if hero and hero.url:
        html_parts.append(
            f'<div class="hero-frame"><img class="cover-hero" src="{esc(hero.url)}" '
            f'alt="{esc(hero.alt or prop.name)}"/></div>')
    html_parts.append(
        f'<div class="cover-meta"><div>{address}</div>'
        f'<div><b>{t("house_manual")}</b></div></div>')
    html_parts.append("</div>")

    # ------------------------------------------------- 01 welcome & arrival
    html_parts.append('<div class="page-break"></div>')
    html_parts.append(_kicker(1, t("sec_arrival")))
    html_parts.append(f'<h2 class="sec">{t("sec_arrival")}</h2>')
    greeting = _i(arrival.get("greeting"), lang, prop.base_lang) or t("welcome_line")
    html_parts.append(f'<p class="lede">{esc(greeting)}</p>')

    stats = []
    if arrival.get("checkin_time"):
        stats.append(_stat(t("check_in"), str(arrival["checkin_time"])))
    if arrival.get("checkout_time"):
        stats.append(_stat(t("check_out"), str(arrival["checkout_time"])))
    door_code = arrival.get("door_code")
    if door_code:
        html_parts.append('<div class="stat-row">' +
                          _stat(t("door_code"), "", True) +
                          '</div>')
        # replace empty value with styled code
        html_parts[-1] = (f'<div class="stat"><div class="k">{esc(t("door_code"))}</div>'
                          f'<div class="code-big">{esc(door_code)}</div></div>')
    if stats:
        html_parts.append(f'<div class="stat-row avoid-break">{"".join(stats)}</div>')

    key_loc = _i(arrival.get("key_location"), lang, prop.base_lang)
    parking = _i(arrival.get("parking"), lang, prop.base_lang)
    extras = []
    if key_loc:
        extras.append(_stat(t("key_lockbox"), key_loc))
    if parking:
        extras.append(_stat(t("parking"), parking))
    if extras:
        html_parts.append(f'<div class="stat-row">{"".join(extras)}</div>')

    steps = [_i(s, lang, prop.base_lang) for s in arrival.get("steps", [])]
    steps = [s for s in steps if s]
    if steps:
        html_parts.append(f'<h3 style="margin:14px 0 6px 0;font-size:18px;">'
                          f'{esc(t("quick_steps"))}</h3><ol class="steps">')
        html_parts.extend(f"<li>{esc(s)}</li>" for s in steps)
        html_parts.append("</ol>")
    duo = _duo(photos_by_section.get("living", []) + photos_by_section.get("exterior", []),
               lang, prop.base_lang)
    if duo:
        html_parts.append(duo)

    # ------------------------------------------------------------ 02 wifi
    html_parts.append('<div class="page-break"></div>')
    html_parts.append(_kicker(2, t("sec_wifi")))
    html_parts.append(f'<h2 class="sec">{t("sec_wifi")}</h2>')
    instructions = _i(wifi.get("instructions"), lang, prop.base_lang)
    if instructions:
        html_parts.append(f'<p class="lede">{esc(instructions)}</p>')
    qr_html = _qr_block(wifi) if wifi.get("ssid") else ""
    fields = []
    if wifi.get("ssid"):
        fields.append((t("network"), str(wifi["ssid"])))
    if wifi.get("password"):
        fields.append((t("password"), str(wifi["password"])))
    field_html = "".join(
        f'<div class="wifi-field"><div class="k">{esc(k)}</div>'
        f'<div class="v">{esc(v)}</div></div>' for k, v in fields)
    html_parts.append(f'<div class="wifi-card"><div class="wifi-fields">{field_html}</div>{qr_html}</div>')
    tips = [_i(x, lang, prop.base_lang) for x in wifi.get("tips", [])]
    tips = [x for x in tips if x]
    if tips:
        html_parts.append(f'<div class="cat-label">{esc(t("wifi_tips"))}</div><ul class="clean">')
        html_parts.extend(f"<li>{esc(x)}</li>" for x in tips)
        html_parts.append("</ul>")

    # ------------------------------------------------------ 03 appliances
    html_parts.append('<div class="page-break"></div>')
    html_parts.append(_kicker(3, t("sec_appliances")))
    html_parts.append(f'<h2 class="sec">{t("sec_appliances")}</h2>')
    intro = _i(appliances.get("intro"), lang, prop.base_lang)
    if intro:
        html_parts.append(f'<p class="lede">{esc(intro)}</p>')
    items = appliances.get("items", [])
    cards = []
    for item in items:
        name = _i(item.get("name"), lang, prop.base_lang)
        icon = item.get("icon", "")
        step_items = [_i(s, lang, prop.base_lang) for s in item.get("steps", [])]
        step_items = [s for s in step_items if s]
        card = (f'<div class="app-card avoid-break"><h3>'
                f'{f"<span class=\'icon\'>{esc(icon)}</span>" if icon else ""}'
                f'{esc(name)}</h3><ol class="steps">')
        card += "".join(f"<li>{esc(s)}</li>" for s in step_items)
        card += "</ol></div>"
        cards.append(card)
    if cards:
        html_parts.append(f'<div class="app-grid">{"".join(cards)}</div>')
    kitchen_duo = _duo(photos_by_section.get("kitchen", []), lang, prop.base_lang)
    if kitchen_duo:
        html_parts.append(kitchen_duo)

    # ------------------------------------------------------------- 04 rules
    html_parts.append('<div class="page-break"></div>')
    html_parts.append(_kicker(4, t("sec_rules")))
    html_parts.append(f'<h2 class="sec">{t("sec_rules")}</h2>')
    note = _i(rules.get("note"), lang, prop.base_lang)
    if note:
        html_parts.append(f'<p class="lede">{esc(note)}</p>')
    rule_rows = []
    for i, r in enumerate(rules.get("rules", []), start=1):
        title = _i(r.get("title"), lang, prop.base_lang) if isinstance(r, dict) else str(r)
        detail = _i(r.get("detail"), lang, prop.base_lang) if isinstance(r, dict) else ""
        row = (f'<div class="rule-row"><span class="rule-mark">{i}</span>'
               f'<div class="rule-body"><b>{esc(title)}</b>')
        if detail:
            row += f'<br/><span style="font-size:12.5px;color:{brand["muted"]}">{esc(detail)}</span>'
        row += "</div></div>"
        rule_rows.append(row)
    if rule_rows:
        html_parts.append("".join(rule_rows))
    quiet = rules.get("quiet_hours")
    if quiet:
        html_parts.append(f'<p style="margin-top:14px;"><span class="quiet-chip">'
                          f'{esc(t("quiet_hours"))}: {esc(quiet)}</span></p>')

    # ---------------------------------------------------- 05 recommendations
    html_parts.append('<div class="page-break"></div>')
    html_parts.append(_kicker(5, t("sec_recommendations")))
    html_parts.append(f'<h2 class="sec">{t("sec_recommendations")}</h2>')
    recs_note = _i(recs.get("note"), lang, prop.base_lang)
    if recs_note:
        html_parts.append(f'<p class="lede">{esc(recs_note)}</p>')
    for cat in recs.get("categories", []):
        cname = _i(cat.get("name"), lang, prop.base_lang)
        icon = cat.get("icon", "")
        html_parts.append(f'<div class="cat-label">{esc(icon)} {esc(cname)}</div>')
        place_cards = []
        for place in cat.get("places", [])[:6]:
            pname = place.get("name", "")
            pdesc = _i(place.get("desc"), lang, prop.base_lang)
            walk = place.get("walk", "")
            walk_html = f'<span class="walk">{esc(walk)}</span>' if walk else ""
            place_cards.append(
                f'<div class="rec-card">{walk_html}<div class="name">{esc(pname)}</div>'
                f'<div class="desc">{esc(pdesc)}</div></div>')
        if place_cards:
            html_parts.append(f'<div class="rec-grid">{"".join(place_cards)}</div>')
    pool_duo = _duo(photos_by_section.get("pool", []) + photos_by_section.get("dining", []),
                    lang, prop.base_lang)
    if pool_duo:
        html_parts.append(pool_duo)

    # --------------------------------------------------------- 06 emergency
    html_parts.append('<div class="page-break"></div>')
    html_parts.append(_kicker(6, t("sec_emergency")))
    html_parts.append(f'<h2 class="sec">{t("sec_emergency")}</h2>')
    emergency_number = emergency.get("number", "112")
    html_parts.append(
        f'<div class="sos-band avoid-break"><div class="sos-num">{esc(emergency_number)}</div>'
        f'<div style="font-size:13px;line-height:1.45;">{esc(t("in_emergency"))}'
        f'<br/><b>{esc(emergency_number)}</b></div></div>')

    em_rows = []
    hospital = emergency.get("hospital") or {}
    if hospital.get("name"):
        em_rows.append((t("hospital"),
                        f"{esc(hospital['name'])}<br/>"
                        f'<span style="color:{brand["muted"]}">{esc(hospital.get("address", ""))}</span>'
                        + (f"<br/>{esc(hospital['phone'])}" if hospital.get("phone") else "")))
    if prop.contact_name:
        host_line = esc(prop.contact_name)
        if prop.contact_phone:
            host_line += f" · <b>{esc(prop.contact_phone)}</b>"
        if prop.contact_email:
            host_line += f" · {esc(prop.contact_email)}"
        em_rows.append((t("host_contact"), host_line + f'<br/><span style="color:{brand["muted"]}">'
                        f'{esc(t("reach_host"))}</span>'))
    for extra in emergency.get("contacts", []):
        label = _i(extra.get("label"), lang, prop.base_lang)
        value = extra.get("value", "")
        detail = _i(extra.get("detail"), lang, prop.base_lang)
        value_html = esc(value)
        if detail:
            value_html += f'<br/><span style="color:{brand["muted"]}">{esc(detail)}</span>'
        if label:
            em_rows.append((label, value_html))
    if em_rows:
        html_parts.append('<table class="em-table">' + "".join(
            f"<tr><td>{esc(k)}</td><td>{v}</td></tr>" for k, v in em_rows) + "</table>")

    shutoffs = emergency.get("shutoffs") or {}
    shutoff_cards = []
    for key, label_key in (("gas", "gas"), ("water", "water"), ("electrics", "electrics")):
        detail = _i(shutoffs.get(key), lang, prop.base_lang)
        if detail:
            shutoff_cards.append(f'<div class="shutoff"><b>{esc(t(label_key))}</b>{esc(detail)}</div>')
    if shutoff_cards:
        html_parts.append(f'<div class="shutoff-grid avoid-break">{"".join(shutoff_cards)}</div>')

    bed_duo = _duo(photos_by_section.get("bedroom", []) + photos_by_section.get("bathroom", []),
                   lang, prop.base_lang)
    if bed_duo:
        html_parts.append(bed_duo)

    # -------------------------------------------------------- 07 floor plan
    plan_svg = _floorplan_svg(prop, lang, brand)
    if plan_svg:
        html_parts.append('<div class="page-break"></div>')
        html_parts.append(_kicker(7, t("sec_floorplan")))
        html_parts.append(f'<h2 class="sec">{t("sec_floorplan")}</h2>')
        plan_note = _i(prop.floorplan_note, lang, prop.base_lang) or t("plan_note")
        html_parts.append(f'<div class="plan-wrap">{plan_svg}'
                          f'<div class="plan-note">{esc(plan_note)}</div></div>')

    # ------------------------------------------------------------- closing
    html_parts.append(
        f'<div class="panel avoid-break" style="margin-top:26px;text-align:center;'
        f'font-family:{FONT_DISPLAY};font-style:italic;font-size:19px;">'
        f'{esc(t("enjoy_stay"))}</div>')

    html_parts.append("</body></html>")
    return "".join(html_parts)
