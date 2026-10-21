from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any


@dataclass
class Chunk:
    document_id: str
    chunk_index: int
    text: str
    page_number: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class DocumentChunker:
    """
    Splits document text into overlapping chunks suitable for embedding.

    Uses simple character-level sliding window with sentence-boundary awareness.
    """

    def __init__(self, chunk_size: int = 512, chunk_overlap: int = 64):
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    def chunk(
        self,
        text: str,
        document_id: str,
        page_number: Optional[int] = None,
    ) -> List[Chunk]:
        """
        Split text into overlapping chunks.

        Returns empty list for empty/whitespace-only input.
        """
        text = text.strip()
        if not text:
            return []

        chunks: List[Chunk] = []
        start = 0
        idx = 0
        step = self.chunk_size - self.chunk_overlap

        while start < len(text):
            end = min(start + self.chunk_size, len(text))
            chunk_text = text[start:end]

            # Try to end at a sentence boundary (period, newline) near the end
            if end < len(text):
                # Look for last sentence boundary in the last 20% of the chunk
                boundary = max(
                    chunk_text.rfind(". ", len(chunk_text) - max(20, self.chunk_size // 5)),
                    chunk_text.rfind("\n", len(chunk_text) - max(20, self.chunk_size // 5)),
                )
                if boundary > 0:
                    end = start + boundary + 1
                    chunk_text = text[start:end]

            chunks.append(Chunk(
                document_id=document_id,
                chunk_index=idx,
                text=chunk_text.strip(),
                page_number=page_number,
                metadata={"document_id": document_id, "chunk_index": idx},
            ))
            idx += 1
            start = start + step
            if start >= len(text):
                break

        return chunks
