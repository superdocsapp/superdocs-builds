"""
Runnable end-to-end demo, using the REAL SuperDocsClient once SUPERDOCS_API_KEY is set. This is what the
demo video runs — the same code the test suite exercises against FakeSuperDocsClient, just pointed at the
real API. Nothing here is a separate "production" implementation from what's tested.

Usage:
    python -m src.cli demo path/to/chapter.docx
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # reads .env in the current working directory -- this is what makes SUPERDOCS_API_KEY
# actually visible to os.getenv() in client.py. Found missing during a real run on 2026-08-22: the .env
# file existed and was correctly filled in, but nothing was loading it into the process environment.

from src.adaptation import run_all_adaptations
from src.client import SuperDocsClient
from src.comparison import build_comparison, render_html
from src.glossary import extract_glossary


def demo(filepath: str):
    client = SuperDocsClient()  # reads SUPERDOCS_API_KEY from env
    # Unique per invocation, not just per filename -- a real bug found in production use (2026-08-22):
    # reusing the same deterministic session_id across repeated demo runs meant each run's content piled up
    # in the SAME server-side SuperDocs session instead of starting clean, and the exported file ended up
    # containing many duplicated, differently-worded copies of the chapter. A fresh session per run avoids
    # this regardless of the exact server-side replace/append semantics.
    import time
    run_tag = str(int(time.time()))
    session_id = f"chapter-{Path(filepath).stem}-{run_tag}"

    print(f"Uploading {filepath} ...")
    doc = client.upload_document(filepath, session_id)
    print(f"  {doc.chunks_count} chunks parsed.")

    print("Running all four adaptations (this calls the real API and will use operations)...")
    results = run_all_adaptations(client, session_id, doc.html, terminology_map="NGSS standard terminology")

    for adaptation_type, result in results.items():
        print(f"  {adaptation_type}: {result.verification.report()}")
        if not result.verification.ok:
            print("    STOPPING — will not export an adaptation that failed verification.")
            continue
        # CRITICAL: sync the (possibly repaired) html back to the server-side session before exporting.
        # export() reads from the SERVER's session state, not from result.html in this process's memory --
        # skipping this call is the exact bug found in production use where verification correctly reported
        # success but the exported file still contained the AI's uncorrected output.
        client.load_html_as_document(result.session_id, result.html)
        out_bytes = client.export(result.session_id, fmt="docx")
        out_path = Path(f"output_{adaptation_type}.docx")
        out_path.write_bytes(out_bytes)
        print(f"    exported -> {out_path}")

    lang_learner_result = results.get("language_learner")
    if lang_learner_result and lang_learner_result.verification.ok:
        print("Extracting glossary from the language-learner version...")
        terms = extract_glossary(client, session_id, lang_learner_result.html)
        for t in terms:
            print(f"  - {t.term}: {t.definition}")

    print("Building comparison view...")
    rows = build_comparison(doc.html, results)
    comparison_html = render_html(rows, list(results.keys()))
    Path("comparison.html").write_text(comparison_html, encoding="utf-8")
    print("  -> comparison.html")

    # Diagnostic: show exactly what changed in the FIRST corrupted protected chunk of the FIRST failed
    # adaptation. IMPORTANT: this must NOT look the chunk up by id in the adapted document -- ids are
    # reassigned every turn (see README's "real bug found" section), so an id-based lookup always reports
    # "not found" regardless of whether the content actually survived, which is misleading, not diagnostic.
    # Instead, find the chunk's POSITION in the source's chunk list and show whatever chunk sits at that
    # same position in the adapted output -- the same alignment strategy comparison.py uses.
    for adaptation_type, result in results.items():
        if not result.verification.ok:
            from src.chunk_classifier import classify_document
            source_chunks = classify_document(doc.html)
            adapted_chunks = classify_document(result.html)
            bad_id = result.verification.corrupted_chunk_ids[0]
            bad_index = next((i for i, c in enumerate(source_chunks) if c.chunk_id == bad_id), None)
            source_chunk = source_chunks[bad_index] if bad_index is not None else None
            adapted_chunk = adapted_chunks[bad_index] if bad_index is not None and bad_index < len(adapted_chunks) else None
            print(f"\n--- DIAGNOSTIC: {adaptation_type}, source chunk {bad_id} (position {bad_index}) ---")
            print(f"SOURCE HTML:\n{source_chunk.html if source_chunk else '(not found)'}")
            print(f"ADAPTED HTML AT SAME POSITION:\n{adapted_chunk.html if adapted_chunk else '(position past end of adapted document)'}")
            break


if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] != "demo":
        print("Usage: python -m src.cli demo path/to/chapter.docx")
        sys.exit(1)
    demo(sys.argv[2])
