"""Source-aware preprocessor with token-based chunking."""

from dataclasses import dataclass, field

import tiktoken


@dataclass
class Chunk:
    text: str
    index: int
    total: int
    source_type: str
    source_id: str
    prior_entities: list[str] = field(default_factory=list)


class Preprocessor:
    def __init__(self, max_chunk_tokens: int = 3000, model: str = "cl100k_base") -> None:
        self._max_tokens = max_chunk_tokens
        self._encoder = tiktoken.get_encoding(model)

    def count_tokens(self, text: str) -> int:
        return len(self._encoder.encode(text))

    def chunk(self, text: str, source_type: str, source_id: str) -> list[Chunk]:
        """Split text into chunks based on source type."""
        if source_type == "slack":
            return self._chunk_slack(text, source_id)
        elif source_type == "github":
            return self._chunk_github(text, source_id)
        elif source_type == "linear":
            return self._chunk_linear(text, source_id)
        else:  # manual or unknown
            return self._chunk_by_tokens(text, source_type, source_id)

    def _chunk_by_tokens(self, text: str, source_type: str, source_id: str) -> list[Chunk]:
        """Generic chunking by token count."""
        tokens = self._encoder.encode(text)
        if len(tokens) <= self._max_tokens:
            return [
                Chunk(
                    text=text,
                    index=0,
                    total=1,
                    source_type=source_type,
                    source_id=source_id,
                    prior_entities=[],
                )
            ]

        chunks: list[str] = []
        # Split by paragraphs first, then by token limit
        paragraphs = text.split("\n\n")
        current_text = ""

        for para in paragraphs:
            candidate = current_text + "\n\n" + para if current_text else para
            if self.count_tokens(candidate) > self._max_tokens and current_text:
                chunks.append(current_text)
                current_text = para
            else:
                current_text = candidate

        if current_text:
            chunks.append(current_text)

        return [
            Chunk(
                text=c,
                index=i,
                total=len(chunks),
                source_type=source_type,
                source_id=source_id,
                prior_entities=[],
            )
            for i, c in enumerate(chunks)
        ]

    def _chunk_slack(self, text: str, source_id: str) -> list[Chunk]:
        """Slack: split by thread boundaries (---) or by tokens."""
        return self._chunk_by_tokens(text, "slack", source_id)

    def _chunk_github(self, text: str, source_id: str) -> list[Chunk]:
        """GitHub: issue/PR as one chunk, chunk by tokens if too long."""
        return self._chunk_by_tokens(text, "github", source_id)

    def _chunk_linear(self, text: str, source_id: str) -> list[Chunk]:
        """Linear: ticket as one chunk, chunk by tokens if too long."""
        return self._chunk_by_tokens(text, "linear", source_id)

    def propagate_entities(self, chunks: list[Chunk], extracted_entities: list[str]) -> None:
        """Update subsequent chunks with entity names from previous chunks."""
        for i in range(1, len(chunks)):
            chunks[i].prior_entities = extracted_entities[:]
