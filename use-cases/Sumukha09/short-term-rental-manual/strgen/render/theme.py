from __future__ import annotations

import html
from typing import Any

FONT_DISPLAY = "'Playfair Display', Georgia, 'Times New Roman', serif"
FONT_BODY = "'Segoe UI', 'Helvetica Neue', Helvetica, Arial, sans-serif"
FONT_MONO = "'Cascadia Code', Consolas, 'Courier New', monospace"

DEFAULT_BRAND: dict[str, Any] = {
    "primary": "#0F766E",     # deep teal
    "accent": "#C2703D",      # terracotta
    "sand": "#F7F2EA",        # warm paper
    "ink": "#232A31",
    "muted": "#68717A",
    "operator_name": "",
    "logo_url": "",
}


def esc(text: Any) -> str:
    return html.escape(str(text if text is not None else ""))


def brand_of(brand: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_BRAND)
    if brand:
        merged.update({k: v for k, v in brand.items()
                       if k in DEFAULT_BRAND and v not in (None, "")})
    return merged


def base_css(b: dict[str, Any]) -> str:
    return f"""
    * {{ box-sizing: border-box; }}
    body {{
      font-family: {FONT_BODY};
      color: {b['ink']};
      font-size: 13.5px;
      line-height: 1.6;
      margin: 0;
    }}
    h1, h2, h3 {{ font-family: {FONT_DISPLAY}; font-weight: 700; margin: 0; }}
    p {{ margin: 0 0 10px 0; }}
    a {{ color: {b['primary']}; text-decoration: none; }}

    .kicker {{
      display: flex; align-items: baseline; gap: 12px;
      margin: 0 0 18px 0;
      border-bottom: 1px solid {b['ink']}22;
      padding-bottom: 10px;
    }}
    .kicker .num {{
      font-family: {FONT_DISPLAY}; font-size: 30px; font-weight: 700;
      color: {b['accent']}; line-height: 1;
    }}
    .kicker .lbl {{
      font-size: 11px; letter-spacing: 3.5px; text-transform: uppercase;
      color: {b['muted']}; font-weight: 600;
    }}
    h2.sec {{ font-size: 30px; line-height: 1.15; margin: 0 0 16px 0; }}
    .lede {{ font-size: 14.5px; color: {b['ink']}; max-width: 92%; }}

    .panel {{
      background: {b['sand']}; border-radius: 10px;
      padding: 16px 18px; margin: 12px 0;
    }}
    .chip {{
      display: inline-block; background: {b['primary']}; color: #fff;
      border-radius: 999px; padding: 3px 12px;
      font-size: 11px; letter-spacing: 1.5px; text-transform: uppercase;
      font-weight: 600;
    }}
    .hairline {{ border: none; border-top: 1px solid {b['ink']}22; margin: 18px 0; }}

    /* cover ----------------------------------------------------------- */
    .cover {{ text-align: left; }}
    .cover-top {{
      display: flex; justify-content: space-between; align-items: center;
      padding: 8px 0 26px 0;
    }}
    .brandmark {{
      display: flex; align-items: center; gap: 9px;
      font-size: 11px; letter-spacing: 3px; text-transform: uppercase;
      color: {b['muted']}; font-weight: 700;
    }}
    .brandmark img {{ height: 34px; }}
    .cover-edition {{
      font-size: 11px; letter-spacing: 2.5px; text-transform: uppercase;
      color: {b['muted']};
    }}
    .cover-rule {{
      height: 4px; background: {b['primary']}; width: 64px;
      border-radius: 2px; margin: 22px 0;
    }}
    .cover-title {{
      font-size: 54px; line-height: 1.04; letter-spacing: -0.5px;
      margin: 0 0 14px 0; color: {b['ink']};
    }}
    .cover-tagline {{
      font-family: {FONT_DISPLAY}; font-style: italic;
      font-size: 17px; color: {b['accent']}; margin: 0 0 24px 0;
    }}
    .cover-hero {{
      width: 100%; border-radius: 12px; display: block;
      box-shadow: 0 10px 28px rgba(35,42,49,.16);
    }}
    .hero-frame {{
      position: relative; padding: 0; margin: 0 0 20px 0; line-height: 0;
    }}
    .cover-meta {{
      display: flex; justify-content: space-between; align-items: flex-end;
      color: {b['muted']}; font-size: 11.5px; letter-spacing: .4px;
      padding-top: 14px; border-top: 1px solid {b['ink']}22;
    }}
    .cover-meta b {{ color: {b['ink']}; }}

    /* stats & codes ---------------------------------------------------- */
    .stat-row {{ display: flex; gap: 12px; margin: 14px 0; }}
    .stat {{
      flex: 1; border: 1px solid {b['ink']}1F; border-radius: 10px;
      padding: 12px 14px; background: #fff;
    }}
    .stat .k {{
      font-size: 10px; letter-spacing: 2px; text-transform: uppercase;
      color: {b['muted']}; font-weight: 700; margin-bottom: 5px;
    }}
    .stat .v {{ font-size: 15px; font-weight: 700; }}
    .code-big {{
      font-family: {FONT_MONO}; font-size: 30px; font-weight: 700;
      letter-spacing: 6px; color: {b['primary']};
    }}

    /* wifi -------------------------------------------------------------- */
    .wifi-card {{
      display: flex; gap: 20px; align-items: center;
      background: {b['sand']}; border-radius: 12px; padding: 20px 22px;
      margin: 14px 0;
    }}
    .wifi-fields {{ flex: 1; }}
    .wifi-field {{ margin: 8px 0; }}
    .wifi-field .k {{
      font-size: 10px; letter-spacing: 2px; text-transform: uppercase;
      color: {b['muted']}; font-weight: 700;
    }}
    .wifi-field .v {{
      font-family: {FONT_MONO}; font-size: 19px; font-weight: 700;
      color: {b['ink']}; word-break: break-all;
    }}
    .qr-wrap {{
      background: #fff; border-radius: 10px; padding: 10px;
      box-shadow: 0 4px 14px rgba(35,42,49,.12);
      text-align: center; width: 158px; flex-shrink: 0;
    }}
    .qr-cap {{
      font-size: 9.5px; color: {b['muted']}; margin-top: 6px; line-height: 1.45;
    }}

    /* lists -------------------------------------------------------------- */
    ul.clean {{ list-style: none; padding: 0; margin: 8px 0; }}
    ul.clean li {{
      padding: 7px 0 7px 24px; position: relative;
      border-bottom: 1px dashed {b['ink']}1A;
    }}
    ul.clean li:last-child {{ border-bottom: none; }}
    ul.clean li:before {{
      content: ""; position: absolute; left: 4px; top: 14px;
      width: 7px; height: 7px; border-radius: 2px; background: {b['accent']};
    }}
    ol.steps {{ margin: 8px 0; padding-left: 20px; }}
    ol.steps li {{ margin: 5px 0; }}

    /* appliance cards ---------------------------------------------------- */
    .app-grid {{ display: flex; flex-wrap: wrap; gap: 12px; margin-top: 12px; }}
    .app-card {{
      width: calc(50% - 6px); border: 1px solid {b['ink']}1F;
      border-radius: 10px; padding: 14px 16px; background: #fff;
    }}
    .app-card h3 {{ font-size: 17px; margin-bottom: 2px; }}
    .app-card .icon {{ font-size: 20px; margin-right: 6px; }}

    /* rules ---------------------------------------------------------------- */
    .rule-row {{
      display: flex; gap: 12px; padding: 10px 0;
      border-bottom: 1px dashed {b['ink']}1A; align-items: baseline;
    }}
    .rule-row:last-of-type {{ border-bottom: none; }}
    .rule-mark {{
      min-width: 22px; height: 22px; border-radius: 6px;
      background: {b['primary']}; color: #fff; font-size: 12px; font-weight: 700;
      display: inline-flex; align-items: center; justify-content: center;
      transform: translateY(4px);
    }}
    .rule-body b {{ font-size: 13.5px; }}
    .quiet-chip {{
      display: inline-block; background: {b['ink']}; color: {b['sand']}
      ; border-radius: 8px; padding: 8px 14px; font-weight: 700;
      letter-spacing: 1px;
    }}

    /* recommendations ------------------------------------------------------- */
    .cat-label {{
      font-size: 11px; letter-spacing: 2.5px; text-transform: uppercase;
      color: {b['accent']}; font-weight: 800; margin: 16px 0 6px 0;
    }}
    .rec-grid {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    .rec-card {{
      width: calc(50% - 5px); background: {b['sand']};
      border-radius: 10px; padding: 11px 14px;
    }}
    .rec-card .name {{ font-weight: 700; font-size: 13px; }}
    .walk {{
      float: right; font-size: 10px; color: {b['primary']};
      font-weight: 800; letter-spacing: .5px; white-space: nowrap;
    }}
    .rec-card .desc {{ font-size: 12px; color: {b['ink']}; opacity: .85; }}

    /* emergency -------------------------------------------------------------- */
    .sos-band {{
      background: {b['accent']}; color: #fff; border-radius: 12px;
      padding: 16px 20px; display: flex; align-items: center; gap: 18px;
      margin: 14px 0;
    }}
    .sos-num {{
      font-family: {FONT_DISPLAY}; font-size: 40px; font-weight: 800;
      letter-spacing: 2px; white-space: nowrap;
    }}
    .em-table {{ width: 100%; border-collapse: collapse; margin: 10px 0; }}
    .em-table td {{
      padding: 9px 12px; border-bottom: 1px solid {b['ink']}1F;
      vertical-align: top; font-size: 13px;
    }}
    .em-table td:first-child {{
      color: {b['muted']}; font-size: 10.5px; text-transform: uppercase;
      letter-spacing: 1.6px; font-weight: 800; width: 32%;
      padding-top: 12px;
    }}
    .shutoff-grid {{ display: flex; gap: 10px; margin-top: 10px; }}
    .shutoff {{
      flex: 1; border: 1px solid {b['ink']}1F; border-radius: 10px;
      padding: 11px 13px; font-size: 12px; background: #fff;
    }}
    .shutoff b {{ display: block; color: {b['accent']}; font-size: 10px;
      text-transform: uppercase; letter-spacing: 1.6px; margin-bottom: 4px; }}

    /* photos ------------------------------------------------------------------ */
    .photo-duo {{ display: flex; gap: 12px; margin: 14px 0; }}
    .photo-duo figure {{ flex: 1; margin: 0; }}
    figure.photo {{ margin: 14px 0; }}
    figure.photo img, .photo-duo img {{
      width: 100%; border-radius: 10px; display: block;
      box-shadow: 0 6px 18px rgba(35,42,49,.14);
    }}
    figcaption {{
      font-size: 11px; color: {b['muted']}; padding-top: 7px;
      letter-spacing: .3px;
    }}
    figcaption b {{ color: {b['accent']}; text-transform: uppercase;
      font-size: 9.5px; letter-spacing: 2px; margin-right: 6px; }}

    /* floor plan ----------------------------------------------------------------- */
    .plan-wrap {{
      border: 1px solid {b['ink']}1F; border-radius: 12px;
      background: #fff; padding: 14px; text-align: center;
    }}
    .plan-note {{ font-size: 11px; color: {b['muted']}; margin-top: 8px; }}

    .page-break {{ page-break-before: always; }}
    .avoid-break {{ page-break-inside: avoid; }}
    """
