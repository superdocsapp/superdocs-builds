"""Streamlit UI for the research-paper writing agent. Pure UI — all
pipeline logic lives in app/services.py and app/evaluation.py.

Run with:
    streamlit run app\\streamlit_app.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st
import pandas as pd

from app.services import (
    sources_from_uploads, infer_topic_from_sources, run_pipeline,
    combine_sections_for_editing, save_combined_draft, export_current,
    get_openai_client,
)
from app.evaluation import compute_all_metrics
from src.openai_client import CHAT_MODEL, EMBEDDING_MODEL
from src.outline_agent import FIXED_SECTION_TITLES


st.set_page_config(page_title="Research Paper Writing Agent", layout="wide")

for key, default in [
    ("paper", None), ("run_logs", []), ("retrieval_index", None),
    ("chunk_id_to_source_id", {}), ("metrics", None),
]:
    if key not in st.session_state:
        st.session_state[key] = default


st.title("📄 Research Paper Writing Agent")
st.caption("RAG-grounded drafting, citation verification, and targeted revision — built on SuperDocs MCP.")

# ============================================================
# SIDEBAR: sources only. Topic is inferred AFTER sources are given.
# ============================================================
with st.sidebar:
    st.header("Sources")
    uploaded_files = st.file_uploader(
        "Source files", type=["txt", "pdf", "docx"], accept_multiple_files=True,
    )
    generate_clicked = st.button("Generate Paper", type="primary", disabled=not uploaded_files)

    if generate_clicked:
        sources = sources_from_uploads(uploaded_files)

        with st.spinner("Inferring topic from your sources..."):
            topic = infer_topic_from_sources(sources)
        st.success(f"Topic: **{topic}**")

        checklist_steps = list(FIXED_SECTION_TITLES)
        completed: set[str] = set()
        checklist_area = st.empty()

        def render_checklist(current: str | None = None) -> None:
            lines = []
            for step in checklist_steps:
                if step in completed:
                    lines.append(f"✅ {step}")
                elif step == current:
                    lines.append(f"🔄 {step}")
                else:
                    lines.append(f"⬜ {step}")
            checklist_area.markdown("\n\n".join(lines))

        render_checklist()

        for event in run_pipeline(topic, sources):
            if event["event"] == "drafting":
                render_checklist(event["section"])
            elif event["event"] == "section_done":
                completed.add(event["section"])
                render_checklist()
            elif event["event"] == "draft_failed":
                st.warning(f"Could not draft '{event['section']}': {event['error']}")
            elif event["event"] == "done":
                completed.update(checklist_steps)
                render_checklist()
                st.session_state.paper = event["paper"]
                st.session_state.run_logs = event["run_logs"]
                st.session_state.retrieval_index = event["retrieval_index"]
                st.session_state.chunk_id_to_source_id = event["chunk_id_to_source_id"]
                # Reset the combined draft editor to reflect the freshly generated paper
                st.session_state.combined_draft_editor = combine_sections_for_editing(event["paper"])

        st.success("Paper generated — see tabs below.")


# ============================================================
# MAIN TABS — always visible, each handles the empty state itself
# ============================================================
paper = st.session_state.paper

tab_draft, tab_runlog, tab_cost, tab_eval, tab_export = st.tabs(
    ["📝 Draft", "📊 Run Log", "💰 Model & Cost", "✅ Evaluation", "📤 Export"]
)

with tab_draft:
    if paper is None:
        st.info("Upload sources in the sidebar and click **Generate Paper** to begin.")
    else:
        st.subheader(f"Topic: {paper.topic}")
        if "combined_draft_editor" not in st.session_state:
            st.session_state.combined_draft_editor = combine_sections_for_editing(paper)

        st.text_area(
            "Full paper draft — edit anywhere, then save",
            height=600, key="combined_draft_editor",
        )
        if st.button("Save Draft"):
            changed = save_combined_draft(paper, st.session_state.combined_draft_editor)
            if changed:
                st.success(f"Updated: {', '.join(changed)}")
            else:
                st.info("No changes detected.")

with tab_runlog:
    if not st.session_state.run_logs:
        st.info("No run log entries yet — generate a paper first.")
    else:
        df = pd.DataFrame([
            {
                "action": log.action.value,
                "sections_touched": ", ".join(log.sections_touched),
                "tokens_used": log.tokens_used,
                "cost_usd": round(log.cost_usd, 4),
                "timestamp": log.timestamp,
            }
            for log in st.session_state.run_logs
        ])
        st.dataframe(df, use_container_width=True)

with tab_cost:
    openai_client = get_openai_client()
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Chat model", CHAT_MODEL)
        st.metric("Embedding model", EMBEDDING_MODEL)
    with col2:
        st.metric("Total tokens", f"{openai_client.total_tokens:,}")
        st.metric("Total cost (USD)", f"${openai_client.total_cost_usd:.4f}")

with tab_eval:
    if paper is None:
        st.info("Generate a paper first to compute evaluation metrics.")
    else:
        if st.button("Compute evaluation metrics"):
            openai_client = get_openai_client()
            st.session_state.metrics = compute_all_metrics(
                paper, st.session_state.run_logs,
                st.session_state.chunk_id_to_source_id, openai_client.embed_fn,
            )

        metrics = st.session_state.metrics
        if metrics:
            cs = metrics["citation_support"]
            st.metric("Citation support rate", f"{cs['overall']:.0%}" if cs["overall"] is not None else "N/A",
                       help=f"{cs['verified']} of {cs['total']} citations verified")

            rev = metrics["revision"]
            st.metric("Revision rate", f"{rev['rate']:.0%}" if rev["rate"] is not None else "N/A",
                       help=f"{rev['sections_revised']} of {rev['total_sections']} sections needed revision")

            cov = metrics["source_coverage"]
            st.metric("Source coverage", f"{cov['rate']:.0%}" if cov["rate"] is not None else "N/A",
                       help=f"{cov['cited_chunks']} of {cov['total_chunks']} source chunks cited")

            redundancy = metrics["redundancy"]["flagged_pairs"]
            if redundancy:
                st.warning(f"{len(redundancy)} section pair(s) look redundant:")
                st.dataframe(pd.DataFrame(redundancy), use_container_width=True)
            else:
                st.success("No redundant section pairs detected.")
        else:
            st.info("Click 'Compute evaluation metrics' to run the checks above.")

with tab_export:
    if paper is None:
        st.info("Generate a paper first to export it.")
    else:
        st.write("Export the current document state (including any manual edits saved above).")
        col1, col2 = st.columns(2)
        for col, fmt, label in [(col1, "html", "HTML"), (col2, "pdf", "PDF")]:
            with col:
                if st.button(f"Export {label}", key=f"export_{fmt}"):
                    try:
                        path = export_current(paper, fmt)
                        st.success(f"Exported to {path}")
                        with open(path, "rb") as f:
                            st.download_button(f"Download {label}", f, file_name=Path(path).name, key=f"dl_{fmt}")
                    except ValueError as e:
                        st.error(str(e))