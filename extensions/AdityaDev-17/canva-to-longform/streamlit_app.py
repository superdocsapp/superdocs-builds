"""
streamlit_app.py — Canva design to long-form document.

Tab 2 (Generate): now shows a debug expander per document type with
the raw response length, so if a document comes back looking like the
seed text instead of expanded content (a real issue observed once),
it's visible immediately rather than silently wrong.

Tab 3 (Human Review): restructured to match Tab 2's UX exactly - one
"Generate all 3 with review" button starts all three async jobs, polls
each independently, and shows results in three sub-tabs. Each sub-tab
independently shows either its pending approve/reject UI (if the job
paused for review) or its final content (if it didn't).
"""
import os
import uuid
import time
import difflib
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

from extract_content import extract_text, extract_palette
from document_quality import check_color_consistency, detect_duplicate_headings
from canva_pipeline import list_designs, pull_design_assets, get_user_info
from superdocs_pipeline import (
    upload_image, seed_document, generate_plain,
    generate_with_approval_start, poll_job, submit_approval_decision,
    export_document,
)
from canva_pipeline import list_designs, pull_design_assets, get_user_info
from sync_pipeline import check_and_sync

ASSET_ROOT = Path("design_assets")
DOC_TYPES = ["Leave-behind report", "Brochure", "Long-form article"]

st.set_page_config(page_title="Canva → Long-Form Document", page_icon="📄", layout="wide")

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { direction: rtl; }
[data-testid="stAppViewContainer"] > * { direction: ltr; }
h1 { text-align: center; }
.subtitle-center { text-align: center; color: #999; margin-bottom: 1.5rem; }
</style>
""", unsafe_allow_html=True)

st.title("Canva → Long-Form Document")
st.markdown(
    '<p class="subtitle-center">Built on SuperDocs — turns a Canva design into a branded, long-form document</p>',
    unsafe_allow_html=True,
)

DEFAULTS = {
    "canva_token": os.environ.get("CANVA_ACCESS_TOKEN", ""),
    "superdocs_key": os.environ.get("SUPERDOCS_API_KEY", ""),
    "design_list": [],
    "selected_design": None,
    "canva_user_info": None,
    "token_connected_at": None,
    "pulled_text": None,
    "pulled_colors": None,
    "pulled_image_path": None,
    "image_url": None,
    "sessions": {},
    "generated": {},
    "generate_debug": {},
    "review_sessions": {},
    "review_pending": {},
    "review_generated": {},
    "review_debug": {},
}
for key, default in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default

TOKEN_LIFETIME_SECONDS = int(os.environ.get("CANVA_TOKEN_EXPIRES_IN", 14400))


with st.sidebar:
    st.subheader("How to use this app")
    st.markdown(
        "1. **Connect to Canva** below and pick a design\n"
        "2. **Pull & Preview** — extract the design's copy, colors, and a print-quality image\n"
        "3. **Generate** — creates all three document types (reliable path)\n"
        "4. **Human Review** — optional, experimental review-gated generation\n"
        "5. **Quality & Export** — check each result, then download\n"
        "6. **Sync** — check for updates if you edit the design in Canva later"
    )

    st.divider()
    st.subheader("Canva connection")

    if st.button("Connect to Canva", use_container_width=True, type="primary"):
        with st.spinner("Connecting..."):
            designs = list_designs(st.session_state.canva_token)
            user_info = get_user_info(st.session_state.canva_token)
        if designs:
            st.session_state.design_list = designs
            st.session_state.canva_user_info = user_info
            st.session_state.token_connected_at = time.time()
            st.success(f"Connected — {len(designs)} design(s) found")
        else:
            st.error("Could not connect. Token may have expired.")
            st.caption("Run `python refresh_canva_token.py`, update .env, then click again.")

    designs = st.session_state.design_list
    if designs:
        labels = {f"{d.get('title', '(untitled)')}": d["id"] for d in designs}
        chosen_label = st.selectbox("Design name", options=list(labels.keys()))
        st.session_state.selected_design = labels[chosen_label]
        st.caption("Design ID")
        st.code(st.session_state.selected_design, language=None)
    else:
        st.caption("Click 'Connect to Canva' to load your designs.")
        manual_id = st.text_input("Or enter a design ID directly")
        if manual_id:
            st.session_state.selected_design = manual_id

    if st.session_state.canva_user_info:
        st.caption("Canva user ID")
        st.code(st.session_state.canva_user_info.get("user_id", "unknown"), language=None)

    st.divider()
    st.subheader("Connection status")
    if st.session_state.canva_token:
        st.success("Canva token loaded")
        if st.session_state.token_connected_at:
            elapsed = time.time() - st.session_state.token_connected_at
            remaining = TOKEN_LIFETIME_SECONDS - elapsed
            if remaining > 0:
                mins_remaining = int(remaining // 60)
                st.caption(f"Token verified {int(elapsed // 60)} min ago — "
                           f"~{mins_remaining} min remaining before it likely expires")
                if mins_remaining < 15:
                    st.warning("Token expiring soon — refresh it after this session.")
            else:
                st.warning("Token likely expired — click 'Connect to Canva' to verify, or refresh it.")
        else:
            st.caption("Click 'Connect to Canva' to verify and start the countdown.")
    else:
        st.error("No Canva token found in .env")

    if st.session_state.superdocs_key:
        st.success("SuperDocs key loaded")
    else:
        st.error("No SuperDocs key found in .env")


if not st.session_state.selected_design:
    st.info("Connect to Canva and select a design in the sidebar to begin.")
    st.stop()

design_id = st.session_state.selected_design
asset_dir = ASSET_ROOT / design_id

tab_pull, tab_generate, tab_review, tab_quality, tab_sync = st.tabs(
    ["1. Pull & Preview", "2. Generate", "3. Human Review", "4. Quality & Export", "5. Sync"]
)

with tab_pull:
    st.subheader("Pull content from Canva")
    st.caption("Extracts copy (via PDF) and visual palette (via a print-resolution PNG export).")

    if st.button("Pull design", type="primary"):
        with st.spinner("Exporting and downloading from Canva..."):
            assets = pull_design_assets(st.session_state.canva_token, design_id, asset_dir)

        if not assets.get("pdf_path") or not assets.get("png_path"):
            st.error("Pull failed. Real errors below:")
            for err in assets.get("errors", []):
                st.code(err)
        else:
            st.session_state.pulled_text = extract_text(assets["pdf_path"])
            st.session_state.pulled_colors = extract_palette(assets["png_path"])
            st.session_state.pulled_image_path = assets["png_path"]
            st.success("Pulled successfully")

    if st.session_state.pulled_text:
        col1, col2 = st.columns([2, 1])
        with col1:
            st.markdown("**Extracted copy**")
            st.text_area("Copy", st.session_state.pulled_text, height=200, label_visibility="collapsed")
        with col2:
            st.markdown("**Brand palette**")
            for c in st.session_state.pulled_colors:
                st.markdown(
                    f'<div style="background-color:{c}; padding:8px; margin-bottom:4px; '
                    f'border-radius:4px; color:white; font-family:monospace;">{c}</div>',
                    unsafe_allow_html=True,
                )
        st.markdown("**Print-resolution preview**")
        st.image(str(st.session_state.pulled_image_path), width=300)

with tab_generate:
    st.subheader("Generate all document types")
    st.caption("Uses the direct generation path — verified reliable across every test in this build.")

    if not st.session_state.pulled_text:
        st.info("Pull a design first (Tab 1).")
    else:
        if st.button("Generate all 3 documents", type="primary"):
            colors = st.session_state.pulled_colors

            if not st.session_state.image_url:
                with st.spinner("Uploading image..."):
                    st.session_state.image_url = upload_image(st.session_state.superdocs_key, st.session_state.pulled_image_path)

            for doc_type in DOC_TYPES:
                session_id = f"canva-{design_id}-{doc_type.split()[0].lower()}-{uuid.uuid4().hex[:6]}"
                st.session_state.sessions[doc_type] = session_id

                seed_html = "\n".join(f"<p>{l}</p>" for l in st.session_state.pulled_text.split("\n") if l.strip())

                with st.spinner(f"Seeding '{doc_type}'..."):
                    seed_result = seed_document(st.session_state.superdocs_key, session_id, seed_html)

                instruction = (
                    f"Here is the original flyer copy:\n\n{st.session_state.pulled_text}\n\n"
                    f"Expand this into a full {doc_type.lower()}, in an energetic tone matching the brand. "
                    f"Use {colors[0]} for all section headings. Brand palette: {', '.join(colors)}. "
                    + (f"Include this image: {st.session_state.image_url}" if st.session_state.image_url else "")
                )

                with st.spinner(f"Generating '{doc_type}'..."):
                    result = generate_plain(st.session_state.superdocs_key, session_id, instruction)

                final_html = result.get("document_changes", {}).get("updated_html", "")
                st.session_state.generated[doc_type] = final_html
                st.session_state.generate_debug[doc_type] = {
                    "session_id": session_id,
                    "seed_response": seed_result.get("response", "")[:150],
                    "seed_html_length": len(seed_html),
                    "ai_response": result.get("response", "")[:200],
                    "final_html_length": len(final_html),
                    "matches_seed_exactly": final_html.strip() == seed_result.get("document_changes", {}).get("updated_html", "").strip(),
                }

            st.success("All 3 documents generated — see tabs below")

        if st.session_state.generated:
            doc_tabs = st.tabs([dt for dt in DOC_TYPES if dt in st.session_state.generated])
            for doc_type, doc_tab in zip([dt for dt in DOC_TYPES if dt in st.session_state.generated], doc_tabs):
                with doc_tab:
                    debug = st.session_state.generate_debug.get(doc_type, {})
                    with st.expander("Debug info", expanded=debug.get("matches_seed_exactly", False)):
                        st.write(f"Session ID: `{debug.get('session_id')}`")
                        st.write(f"Seed response: {debug.get('seed_response')}")
                        st.write(f"AI response: {debug.get('ai_response')}")
                        st.write(f"Final HTML length: {debug.get('final_html_length')} chars")
                        if debug.get("matches_seed_exactly"):
                            st.error("WARNING: final content is byte-identical to the seeded content — "
                                     "the expansion instruction may not have taken effect.")
                    st.markdown(st.session_state.generated[doc_type], unsafe_allow_html=True)

with tab_review:
    st.subheader("Human review mode (experimental)")
    st.warning(
        "Separate, independent generation path from Tab 2 — does NOT affect anything already "
        "generated there. Uses SuperDocs' approval flow. Found during testing to activate "
        "inconsistently and to sometimes propose placeholder content even when it does activate. "
        "Each document below shows its own raw status, independently."
    )

    if not st.session_state.pulled_text:
        st.info("Pull a design first (Tab 1).")
    else:
        if st.button("Generate all 3 with review", type="primary"):
            colors = st.session_state.pulled_colors

            if not st.session_state.image_url:
                with st.spinner("Uploading image..."):
                    st.session_state.image_url = upload_image(st.session_state.superdocs_key, st.session_state.pulled_image_path)

            for doc_type in DOC_TYPES:
                log = []
                session_id = f"canva-{design_id}-review-{doc_type.split()[0].lower()}-{uuid.uuid4().hex[:6]}"
                st.session_state.review_sessions[doc_type] = session_id
                log.append(f"New session: {session_id}")

                seed_html = "\n".join(f"<p>{l}</p>" for l in st.session_state.pulled_text.split("\n") if l.strip())
                with st.spinner(f"Seeding '{doc_type}'..."):
                    seed_document(st.session_state.superdocs_key, session_id, seed_html)
                log.append("Document seeded.")

                instruction = (
                    f"This is the copy from a promotional flyer. Expand it into a full {doc_type.lower()}, "
                    f"in an energetic tone matching the brand. Use {colors[0]} for all section headings. "
                    f"Brand palette: {', '.join(colors)}. "
                    + (f"Include this image: {st.session_state.image_url}" if st.session_state.image_url else "")
                )

                with st.spinner(f"Starting async job for '{doc_type}'..."):
                    job_id = generate_with_approval_start(st.session_state.superdocs_key, session_id, instruction)
                log.append(f"job_id: {job_id!r}")

                if not job_id:
                    log.append("FAILED: no job_id returned.")
                else:
                    with st.spinner(f"Polling '{doc_type}'..."):
                        job_data = poll_job(st.session_state.superdocs_key, job_id)
                        log.append(f"Poll: status={job_data.get('status')}")
                        poll_count = 0
                        while job_data.get("status") == "in_progress" and poll_count < 40:
                            time.sleep(3)
                            job_data = poll_job(st.session_state.superdocs_key, job_id)
                            poll_count += 1
                            log.append(f"Poll #{poll_count}: status={job_data.get('status')}")

                    final_status = job_data.get("status")
                    log.append(f"Final status: {final_status}")

                    if final_status == "awaiting_approval":
                        changes = job_data.get("metadata", {}).get("pending_changes", [])
                        st.session_state.review_pending[doc_type] = {"job_id": job_id, "changes": changes}
                        log.append(f"{len(changes)} pending change(s).")
                    elif final_status == "completed":
                        st.session_state.review_generated[doc_type] = job_data.get("result", {}).get("document_changes", {}).get("updated_html", "")
                        log.append("Completed WITHOUT pausing for approval (known inconsistent-activation issue).")
                    else:
                        log.append(f"Unexpected status. Full data: {job_data}")

                st.session_state.review_debug[doc_type] = log

            st.success("All 3 review-mode jobs processed — see tabs below")

        if st.session_state.review_debug:
            review_doc_tabs = st.tabs(DOC_TYPES)
            for doc_type, r_tab in zip(DOC_TYPES, review_doc_tabs):
                with r_tab:
                    log = st.session_state.review_debug.get(doc_type, [])
                    with st.expander("Debug log", expanded=True):
                        for line in log:
                            st.text(line)

                    pending_entry = st.session_state.review_pending.get(doc_type)
                    if pending_entry:
                        st.subheader("Proposed changes — review each one")
                        decisions = []
                        for i, change in enumerate(pending_entry["changes"]):
                            with st.container(border=True):
                                st.write(change.get("ai_explanation", "(no explanation)"))
                                st.markdown("**Preview:**")
                                st.markdown(change.get("new_html") or "(none)", unsafe_allow_html=True)
                                approved = st.radio(
                                    "Decision", ["Approve", "Reject"],
                                    key=f"review_decision_{doc_type}_{i}", horizontal=True,
                                )
                                decisions.append({"change_id": change.get("change_id"), "approved": approved == "Approve"})

                        if st.button(f"Submit decisions for {doc_type}", key=f"submit_review_{doc_type}"):
                            submit_approval_decision(
                                st.session_state.superdocs_key, st.session_state.review_sessions[doc_type],
                                pending_entry["job_id"], decisions,
                            )
                            final = poll_job(st.session_state.superdocs_key, pending_entry["job_id"])
                            st.session_state.review_generated[doc_type] = final.get("result", {}).get("document_changes", {}).get("updated_html", "")
                            del st.session_state.review_pending[doc_type]
                            st.rerun()

                    elif doc_type in st.session_state.review_generated:
                        st.info("This job completed without pausing for approval — a known SuperDocs reliability "
                                "issue (already reported). Try again or try a different document type to see the "
                                "approve/reject UI in action.")
                        st.subheader("Result")
                        st.markdown(st.session_state.review_generated[doc_type], unsafe_allow_html=True)
                    else:
                        st.caption("Not generated yet.")

with tab_quality:
    if not st.session_state.generated:
        st.info("Generate documents first (Tab 2).")
    else:
        primary = st.session_state.pulled_colors[0]
        available_types = [dt for dt in DOC_TYPES if dt in st.session_state.generated]
        quality_tabs = st.tabs(available_types)
        for doc_type, q_tab in zip(available_types, quality_tabs):
            with q_tab:
                html = st.session_state.generated[doc_type]
                consistency = check_color_consistency(html, primary)
                duplicates = detect_duplicate_headings(html)

                col1, col2 = st.columns(2)
                _ = col1.metric("On-brand headings", f"{consistency['on_brand_count']}/{consistency['total']}")
                _ = col2.metric("Duplicate sections", len(duplicates))

                if duplicates:
                    _ = st.warning("Duplicate sections found:")
                    for d in duplicates:
                        _ = st.write(f"- \"{d['text']}\" appears {d['count']} times")

                passed = not consistency["off_brand"] and not duplicates
                if passed:
                    _ = st.success("Quality gate passed")
                else:
                    _ = st.error("Quality gate failed — review before exporting")

                _ = st.divider()
                _ = st.subheader("Export")
                col1, col2, col3 = st.columns(3)
                session_id = st.session_state.sessions[doc_type]
                with col1:
                    if st.button(f"Export .docx", key=f"docx_{doc_type}"):
                        data = export_document(st.session_state.superdocs_key, session_id, "docx")
                        if data:
                            _ = st.download_button("Download .docx", data, file_name=f"{doc_type}.docx", key=f"dl_docx_{doc_type}")
                with col2:
                    if st.button(f"Export .pdf", key=f"pdf_{doc_type}"):
                        data = export_document(st.session_state.superdocs_key, session_id, "pdf")
                        if data:
                            _ = st.download_button("Download .pdf", data, file_name=f"{doc_type}.pdf", key=f"dl_pdf_{doc_type}")
                with col3:
                    _ = st.download_button("Download .html", html, file_name=f"{doc_type}.html", key=f"dl_html_{doc_type}")

with tab_sync:
    st.subheader("Check for design updates")
    st.caption("Re-pulls the Canva design and pushes updates to any already-generated documents, "
               "if the copy changed since the last check.")

    if not st.session_state.sessions:
        st.info("Generate at least one document first (Tab 2) before checking for updates.")
    else:
        if st.button("Check for updates", type="primary"):
            with st.spinner("Checking Canva for changes..."):
                sync_result = check_and_sync(
                    st.session_state.canva_token,
                    st.session_state.superdocs_key,
                    design_id,
                    st.session_state.sessions,
                    asset_dir,
                )

            if sync_result["status"] == "error":
                st.error(sync_result["message"])
            elif sync_result["status"] == "baseline_registered":
                st.info(sync_result["message"])
            elif sync_result["status"] == "no_changes":
                st.success(sync_result["message"])
            elif sync_result["status"] == "changed":
                st.warning(sync_result["message"])
                with st.expander("What changed", expanded=True):
                    diff_lines = list(difflib.unified_diff(
                        sync_result["old_text"].splitlines(), sync_result["new_text"].splitlines(),
                        lineterm="", n=0,
                    ))
                    for line in diff_lines:
                        st.text(line)
                st.subheader("Documents updated")
                for u in sync_result["updates"]:
                    st.write(f"**{u['doc_type']}**: {u['ai_response']}")