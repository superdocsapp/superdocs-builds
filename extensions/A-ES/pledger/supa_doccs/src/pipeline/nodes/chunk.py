"""Chunk node for the Understand stage of the pipeline.

Splits extracted_text into segments of configurable maximum size with
configurable overlap. Supports skip when text is below minimum threshold
and permanent error when extracted_text is None or empty.
"""

from src.pipeline.state import ChunkEntry, PipelineState, SkippedNodeEntry

NODE_NAME = "chunk"


async def chunk(state: PipelineState) -> PipelineState:
    """Split extracted_text into overlapping chunks.

    Input keys: extracted_text, config
    Output keys: chunks, current_node, node_status, error_type, error_detail,
                 skipped_nodes, completed_nodes

    Terminal states:
        - completed: chunks produced
        - skipped: text below min_chunk_threshold (single-element chunk list)
        - error/permanent: extracted_text is None or empty

    Chunking algorithm:
        Window slides by (chunk_max_size - chunk_overlap) each step.
        Each chunk: start_offset = step * stride, end_offset = min(start + max_size, len(text))
        Final chunk may be shorter than chunk_max_size.
        All characters in the original text are covered (no gaps).
    """
    extracted_text = state.get("extracted_text")  # type: ignore[call-overload]
    config = state["config"]

    # Permanent error: extracted_text is None or empty
    if extracted_text is None or len(extracted_text) == 0:
        return PipelineState(
            **{
                **state,
                "current_node": NODE_NAME,
                "node_status": "error",
                "error_type": "permanent",
                "error_detail": "extracted_text is None or empty",
                "chunks": state.get("chunks", []),  # type: ignore[call-overload]
                "skipped_nodes": state.get("skipped_nodes", []),  # type: ignore[call-overload]
                "completed_nodes": state.get("completed_nodes", []),  # type: ignore[call-overload]
            },
        )

    min_chunk_threshold = config["min_chunk_threshold"]

    # Skip: text below minimum chunk threshold
    if len(extracted_text) < min_chunk_threshold:
        single_chunk = ChunkEntry(
            index=0,
            text=extracted_text,
            start_offset=0,
            end_offset=len(extracted_text),
        )
        skipped_nodes = list(state.get("skipped_nodes", []))  # type: ignore[call-overload]
        skipped_nodes.append(
            SkippedNodeEntry(node_name=NODE_NAME, reason="below_chunk_threshold")
        )
        completed_nodes = list(state.get("completed_nodes", []))  # type: ignore[call-overload]
        completed_nodes.append(NODE_NAME)
        return PipelineState(
            **{
                **state,
                "current_node": NODE_NAME,
                "node_status": "skipped",
                "error_type": None,
                "error_detail": None,
                "chunks": [single_chunk],
                "skipped_nodes": skipped_nodes,
                "completed_nodes": completed_nodes,
            },
        )

    # Normal chunking
    chunk_max_size = config["chunk_max_size"]
    chunk_overlap = config["chunk_overlap"]
    stride = chunk_max_size - chunk_overlap
    text_length = len(extracted_text)

    chunks: list[ChunkEntry] = []
    step = 0
    while True:
        start_offset = step * stride
        if start_offset >= text_length:
            break
        end_offset = min(start_offset + chunk_max_size, text_length)
        chunks.append(
            ChunkEntry(
                index=step,
                text=extracted_text[start_offset:end_offset],
                start_offset=start_offset,
                end_offset=end_offset,
            )
        )
        # If we've reached the end of the text, stop
        if end_offset == text_length:
            break
        step += 1

    completed_nodes = list(state.get("completed_nodes", []))  # type: ignore[call-overload]
    completed_nodes.append(NODE_NAME)

    return PipelineState(
        **{
            **state,
            "current_node": NODE_NAME,
            "node_status": "completed",
            "error_type": None,
            "error_detail": None,
            "chunks": chunks,
            "skipped_nodes": state.get("skipped_nodes", []),  # type: ignore[call-overload]
            "completed_nodes": completed_nodes,
        },
    )
