from __future__ import annotations

from strgen.i18n import T
from strgen.models import Property, resolve_text
from strgen.assembly import resolve

from .theme import base_css, brand_of, esc, FONT_DISPLAY


def render_card(prop: Property, blocks: dict, lang: str) -> str:
    t = T(lang, prop.base_lang)
    brand = brand_of(resolve("brand", prop, blocks)) if ("brand" in prop.links or "brand" in prop.overrides) \
        else brand_of(None)
    arrival = resolve("arrival", prop, blocks)
    wifi = resolve("wifi", prop, blocks)
    emergency = resolve("emergency", prop, blocks)

    b_primary, b_accent = brand["primary"], brand["accent"]
    b_sand, b_ink, b_muted = brand["sand"], brand["ink"], brand["muted"]
    greeting = _g(arrival.get("greeting"), lang, prop.base_lang) or t("welcome_line")

    qr_html = ""
    if wifi.get("ssid"):
        from strgen import qr as qrmod
        matrix = qrmod.make(qrmod.wifi_payload(str(wifi["ssid"]), str(wifi.get("password", ""))))
        qr_html = qrmod.svg(matrix, module_px=3)

    css = f"""
    {base_css(brand)}
    body {{ font-size: 12px; }}
    .sheet {{ display: flex; justify-content: center; padding-top: 26px; }}
    .card {{
      width: 540px; border-radius: 14px; overflow: hidden;
      box-shadow: 0 14px 34px rgba(35,42,49,.22); background: #fff;
      page-break-inside: avoid;
    }}
    .head {{
      background: linear-gradient(135deg, {b_primary} 0%, #0b5a54 100%);
      color: #fff; padding: 20px 24px 17px 24px;
    }}
    .head .op {{
      font-size: 9px; letter-spacing: 3px; text-transform: uppercase;
      opacity: .85; margin-bottom: 5px; font-weight: 700;
    }}
    .head h1 {{
      font-family: {FONT_DISPLAY}; font-size: 27px; line-height: 1.05;
      letter-spacing: -.3px;
    }}
    .head .hello {{
      font-family: {FONT_DISPLAY}; font-style: italic; font-size: 13px;
      opacity: .95; margin-top: 6px; color: {b_sand};
    }}
    .grid {{ display: flex; gap: 16px; padding: 16px 20px 12px 20px; }}
    .col {{ flex: 1; }}
    .lbl {{
      font-size: 8.5px; letter-spacing: 2px; text-transform: uppercase;
      color: {b_muted}; font-weight: 800; margin-bottom: 2px;
    }}
    .val {{ font-family: Consolas, 'Courier New', monospace; font-weight: 700;
      font-size: 15px; word-break: break-all; }}
    .doorcode {{ font-family: Consolas, monospace; font-size: 26px;
      font-weight: 700; letter-spacing: 5px; color: {b_primary}; }}
    .times {{ display: flex; gap: 10px; margin-top: 10px; }}
    .time {{ flex: 1; background: {b_sand}; border-radius: 8px; padding: 7px 10px; }}
    .time .lbl {{ margin-bottom: 1px; }}
    .time b {{ font-size: 13px; }}
    .qrbox {{ width: 118px; text-align: center; }}
    .qrbox svg {{ width: 104px; height: 104px; }}
    .foot {{
      background: {b_accent}; color: #fff; padding: 11px 20px;
      display: flex; justify-content: space-between; align-items: center;
    }}
    .foot .sos {{ font-size: 19px; font-weight: 800; letter-spacing: 1px; }}
    .foot .host {{ font-size: 11.5px; text-align: right; line-height: 1.35; opacity: .95; }}
    .trim {{ color: {b_muted}; opacity: .55; }}
    """

    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'/><title>",
        esc(t("welcome_card")), "</title><style>", css, "</style></head><body>",
        '<div class="sheet"><div class="card">',
        f'<div class="head"><div class="op">{esc(brand.get("operator_name") or "")}</div>',
        f"<h1>{esc(prop.name)}</h1>",
        f'<div class="hello">{esc(greeting)}</div></div>',
        '<div class="grid"><div class="col">',
        f'<div class="lbl">{esc(t("network"))}</div><div class="val">{esc(wifi.get("ssid", ""))}</div>',
        f'<div class="lbl" style="margin-top:7px;">{esc(t("password"))}</div>'
        f'<div class="val">{esc(wifi.get("password", ""))}</div>',
        "</div>",
        '<div class="col">',
    ]
    if arrival.get("door_code"):
        parts.append(f'<div class="lbl">{esc(t("door_code"))}</div>'
                     f'<div class="doorcode">{esc(arrival["door_code"])}</div>')
    checkin, checkout = arrival.get("checkin_time"), arrival.get("checkout_time")
    if checkin or checkout:
        parts.append('<div class="times">')
        if checkin:
            parts.append(f'<div class="time"><div class="lbl">{esc(t("check_in"))}</div>'
                         f'<b>{esc(checkin)}</b></div>')
        if checkout:
            parts.append(f'<div class="time"><div class="lbl">{esc(t("check_out"))}</div>'
                         f'<b>{esc(checkout)}</b></div>')
        parts.append("</div>")
    if qr_html:
        parts.append(f'<div class="qrbox">{qr_html}'
                     f'<div class="trim" style="font-size:8.5px;margin-top:3px;">'
                     f'{esc(t("scan_qr"))}</div></div>')
    parts.append("</div></div>")
    sos = str(emergency.get("number", "112"))
    host_bits = [prop.contact_name] if prop.contact_name else []
    if prop.contact_phone:
        host_bits.append(prop.contact_phone)
    parts.append(
        f'<div class="foot"><div class="sos">{esc(t("help"))} · {esc(sos)}</div>'
        f'<div class="host">{" · ".join(esc(x) for x in host_bits)}</div></div>')
    parts.append("</div></div></body></html>")
    return "".join(parts)


def _g(node, lang: str, base: str) -> str:
    return resolve_text(node, lang, base)
