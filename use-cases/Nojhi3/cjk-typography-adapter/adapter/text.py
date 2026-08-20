import re

from .profile import Profile

_CJK_TEXT_CLASS = r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]"
_CJK_CLASS = r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af\u3000-\u303f\uff00-\uffef]"
_LATIN_CLASS = r"[A-Za-z0-9]"
_CJK_TEXT_RE = re.compile(_CJK_TEXT_CLASS)
_CJK_RE = re.compile(_CJK_CLASS)
_LATIN_RE = re.compile(r"[A-Za-z]")
_DIGIT_RE = re.compile(r"[0-9]")
_SPACE_RE = re.compile(r"[ \t\u3000\u2009\u00a0\r\n]")

_FULLWIDTH_TRANS = str.maketrans(
    "０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ",
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
)
_FULLWIDTH_SET = set("０１２３４５６７８９ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ")

_SAMPLE_LIMIT = 8


def is_cjk(ch: str) -> bool:
    return bool(_CJK_RE.match(ch))


def is_cjk_text(ch: str) -> bool:
    return bool(_CJK_TEXT_RE.match(ch))


def is_latin(ch: str) -> bool:
    return bool(_LATIN_RE.match(ch))


def is_digit(ch: str) -> bool:
    return bool(_DIGIT_RE.match(ch))


def is_space(ch: str) -> bool:
    return bool(_SPACE_RE.match(ch))


def _needs_thin_space(a: str, b: str) -> bool:
    a_cjk, b_cjk = is_cjk_text(a), is_cjk_text(b)
    a_lat, b_lat = is_latin(a) or is_digit(a), is_latin(b) or is_digit(b)
    return (a_cjk and b_lat) or (a_lat and b_cjk)


def _new_stats() -> dict:
    return {k: {"count": 0, "samples": []} for k in
            ("punctuation", "quotes", "thin_spaces", "kinsoku", "halfwidth")}


def _record(stats: dict, key: str, before: str, after: str) -> None:
    stats[key]["count"] += 1
    if len(stats[key]["samples"]) < _SAMPLE_LIMIT:
        stats[key]["samples"].append([before, after])


def _subst_punctuation(text: str, profile: Profile, stats: dict) -> str:
    punc = profile.punctuation_map
    if not punc:
        return text
    n = len(text)
    out = []
    for i, ch in enumerate(text):
        if ch not in punc:
            out.append(ch)
            continue
        prv = next((text[j] for j in range(i - 1, -1, -1) if not is_space(text[j])), None)
        nxt = next((text[j] for j in range(i + 1, n) if not is_space(text[j])), None)
        adjacent_cjk = (prv is not None and is_cjk(prv)) or (nxt is not None and is_cjk(nxt))
        end_of_run = nxt is None
        if ch in ",:":
            if adjacent_cjk:
                out.append(punc[ch])
                _record(stats, "punctuation", ch, punc[ch])
            else:
                out.append(ch)
        elif ch in "()（）":
            out.append(punc[ch])
            _record(stats, "punctuation", ch, punc[ch])
        elif adjacent_cjk or end_of_run:
            out.append(punc[ch])
            _record(stats, "punctuation", ch, punc[ch])
        else:
            out.append(ch)
    return "".join(out)


def _subst_quotes(text: str, profile: Profile, stats: dict) -> str:
    q = profile.quote_map
    fullwidth = "\u201c\u201d\u300c\u300d"
    open_state = True
    out = []
    for ch in text:
        if ch == '"' or (profile.direction == "cjk-to-latin" and ch in fullwidth):
            out.append(q["open"] if open_state else q["close"])
            open_state = not open_state
            _record(stats, "quotes", ch, out[-1])
        else:
            out.append(ch)
    return "".join(out)


def _thin_spaces(text: str, profile: Profile, stats: dict) -> str:
    if profile.remove_thin_spaces:
        for m in re.finditer(re.escape(profile.thin_space), text):
            _record(stats, "thin_spaces", m.group(0), "")
        return text.replace(profile.thin_space, "")
    ts = profile.thin_space

    def _space_boundary(m: re.Match) -> str:
        a, b = m.group(1), m.group(2)
        if _needs_thin_space(a, b):
            _record(stats, "thin_spaces", m.group(0), a + ts + b)
            return a + ts + b
        return a + " " + b

    text = re.sub(
        r"(" + _CJK_CLASS + r"|" + _LATIN_CLASS + r")[ \t\u00a0]+(" + _LATIN_CLASS + r"|" + _CJK_CLASS + r")",
        _space_boundary,
        text,
    )
    out = []
    for i, ch in enumerate(text):
        out.append(ch)
        if i + 1 < len(text) and _needs_thin_space(ch, text[i + 1]):
            out.append(ts)
            _record(stats, "thin_spaces", ch + text[i + 1], ch + ts + text[i + 1])
    return "".join(out)


def _kinsoku_attach(text: str, profile: Profile, stats: dict) -> str:
    opening = re.escape(profile.kinsoku_no_line_end)
    closing = re.escape(profile.kinsoku_no_line_start)
    if not opening and not closing:
        return text
    for m in re.finditer(r"[" + opening + r"][ \t\u3000\u2009\r\n]+" if opening else r"(?!x)x", text):
        _record(stats, "kinsoku", m.group(0), m.group(0)[0])
    text = re.sub(r"([" + opening + r"])[ \t\u3000\u2009\r\n]+", r"\1", text) if opening else text
    for m in re.finditer(r"[ \t\u3000\u2009\r\n]+[" + closing + r"]" if closing else r"(?!x)x", text):
        _record(stats, "kinsoku", m.group(0), m.group(0)[-1])
    text = re.sub(r"[ \t\u3000\u2009\r\n]+([" + closing + r"])", r"\1", text) if closing else text
    return text


def _halfwidth_convert(text: str, profile: Profile, stats: dict) -> str:
    if profile.direction != "cjk-to-latin":
        return text
    out = []
    for ch in text:
        if ch in _FULLWIDTH_SET:
            out.append(ch.translate(_FULLWIDTH_TRANS))
            _record(stats, "halfwidth", ch, out[-1])
        else:
            out.append(ch)
    return "".join(out)


def apply_text_rules(text: str, profile: Profile) -> tuple[str, dict]:
    stats = _new_stats()
    text = _halfwidth_convert(text, profile, stats)
    text = _subst_punctuation(text, profile, stats)
    text = _subst_quotes(text, profile, stats)
    text = _kinsoku_attach(text, profile, stats)
    text = _thin_spaces(text, profile, stats)
    return text, stats
