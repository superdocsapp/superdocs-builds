from soc2_index.diff import compute
from soc2_index.render import apply_patch, html
from tests.conftest import FIXTURES, build_from


def test_unchanged_tr_bytes(sample_catalog):
    v1, _, _ = build_from(FIXTURES / "cedar-harbor-v1", sample_catalog)
    v2, _, _ = build_from(FIXTURES / "cedar-harbor-v2", sample_catalog)
    old = html(v1)
    d = compute(v1, v2, "v1", "v2")
    patched = apply_patch(old, v2, d)
    for rid in d.unchanged_ids:
        needle = f'data-row-id="{rid}"'
        i = old.find(needle)
        assert i >= 0
        start = old.rfind("<tr", 0, i)
        end = old.find("</tr>", i) + len("</tr>")
        original = old[start:end]
        j = patched.find(needle)
        assert j >= 0
        start2 = patched.rfind("<tr", 0, j)
        end2 = patched.find("</tr>", j) + len("</tr>")
        copied = patched[start2:end2]
        assert copied == original
