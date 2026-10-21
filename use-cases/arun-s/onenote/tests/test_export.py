"""The whole pipeline, keyless: fake OneNote (Graph) + fake SuperDocs prove
page -> reading-order HTML -> export, with no Microsoft account and no API key."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from graph import OneNote
from superdocs_min import SuperDocs
from export import export_page

SAMPLE = (pathlib.Path(__file__).resolve().parent.parent / "sample_page.html").read_text()


def _fake_graph(method, url, headers):
    if url.endswith("/pages?$top=20"):
        return 200, '{"value":[{"id":"1-abc","title":"Status"}]}'
    if url.endswith("/content"):
        return 200, SAMPLE
    return 404, "{}"


def _fake_superdocs(method, url, headers, body):
    if url.endswith("/chat/async"):
        return 200, '{"job_id":"job-1","status":"completed"}'
    if url.endswith("/documents/export"):
        return 200, "PK\x03\x04 fake-docx-bytes"
    return 404, ""


def test_graph_list_and_content():
    on = OneNote("t", transport=_fake_graph)
    assert on.list_pages()[0]["title"] == "Status"
    assert "position:absolute" in on.page_html("1-abc")


def test_full_pipeline_page_to_export():
    on = OneNote("t", transport=_fake_graph)
    sd = SuperDocs("k", transport=_fake_superdocs)
    res = export_page(on, sd, "1-abc", title="Status")
    # reading order applied (Highlights before Risks), and an export was produced
    assert res["html"].index("Highlights") < res["html"].index("Risks")
    assert res["docx_bytes"] > 0
