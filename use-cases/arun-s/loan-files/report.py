"""Render the loan decision as a themed memo (HTML) and hand it to SuperDocs to export."""
from analyze import analyze

def memo_html(result: dict) -> str:
    f, src = result["facts"], result["sources"]
    rows = "".join(f"<tr><td>{k.replace('_',' ')}</td><td>{v}</td><td>{src.get(k,'')}</td></tr>" for k, v in f.items())
    findings = "".join(f"<li>{x['message']} <em>[{', '.join(x['citations'])}]</em></li>" for x in result["findings"]) \
               or "<li>No adverse findings.</li>"
    badge = "REFER" if result["decision"] == "refer" else "CLEAR"
    return (f"<h1>Loan Decision Memo</h1><p><b>Decision:</b> {badge}</p>"
            f"<h2>Grounded facts</h2><table>{rows}</table>"
            f"<h2>Findings</h2><ul>{findings}</ul>")

def export_memo(superdocs, docs, session_id="loan-memo"):
    result = analyze(docs)
    html = memo_html(result)
    superdocs.send_document(html, session_id, "Format as a branded one-page loan decision memo.")
    return {"result": result, "html": html, "docx": superdocs.export(session_id, "docx")}
