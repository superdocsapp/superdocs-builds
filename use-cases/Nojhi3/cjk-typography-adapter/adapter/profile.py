import json
from dataclasses import dataclass, fields
from pathlib import Path

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"

LOCALES = ("ja", "zh-CN", "zh-TW", "ko")


@dataclass
class Profile:
    name: str
    label: str
    direction: str
    lang: str
    body_font: str
    heading_font: str
    latin_font: str
    body_size_pt: float
    heading_sizes_pt: dict
    heading_bold: bool
    line_spacing: float
    paragraph_spacing_pt: float
    text_align: str
    page: dict
    punctuation_map: dict
    quote_map: dict
    thin_space: str
    kinsoku_no_line_start: str
    kinsoku_no_line_end: str
    css_extra: str
    remove_thin_spaces: bool = False

    @property
    def cjk_body_font(self) -> str:
        for part in self.body_font.split(","):
            part = part.strip().strip("'\"")
            if part and part not in ("serif", "sans-serif"):
                return part
        return self.body_font

    @property
    def latin_primary(self) -> str:
        for part in self.latin_font.split(","):
            part = part.strip().strip("'\"")
            if part and part not in ("serif", "sans-serif"):
                return part
        return self.latin_font


def load_profile(locale: str, reverse: bool = False) -> Profile:
    if reverse:
        locale = "en"
    if locale not in LOCALES and locale != "en":
        raise ValueError(f"unknown locale {locale!r}; expected one of {LOCALES}")
    path = PROFILES_DIR / f"{locale}.json"
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    valid = {f.name for f in fields(Profile)}
    kwargs = {k: v for k, v in data.items() if k in valid}
    return Profile(**kwargs)
