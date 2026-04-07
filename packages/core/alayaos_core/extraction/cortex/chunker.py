"""Source-aware chunker for Cortex intelligence pipeline."""

import json
import re
import unicodedata
from dataclasses import dataclass

import tiktoken


@dataclass
class RawChunk:
    text: str
    index: int
    total: int
    source_type: str
    source_id: str
    token_count: int


def _is_emoji_only(text: str) -> bool:
    """Return True if text contains only emoji characters and whitespace."""
    stripped = text.strip()
    if not stripped:
        return False
    for char in stripped:
        cat = unicodedata.category(char)
        # Allow emoji: So (other symbol), Sk (modifier symbol), Sm (math symbol),
        # and variation selectors / zero-width joiners in the Cf category
        if char in ("\u200d", "\ufe0f", "\ufe0e"):
            continue
        if cat not in ("So", "Sk", "Sm") and not unicodedata.name(char, "").startswith("EMOJI"):
            return False
    return True


class CortexChunker:
    def __init__(self, max_chunk_tokens: int = 3000, model: str = "cl100k_base") -> None:
        self.encoding = tiktoken.get_encoding(model)
        self.max_tokens = max_chunk_tokens

    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def chunk(self, text: str, source_type: str, source_id: str) -> list[RawChunk]:
        """Split text into chunks based on source type."""
        if source_type == "slack":
            return self._chunk_slack(text, source_id)
        elif source_type in ("meeting_transcript", "document"):
            return self._chunk_by_speaker_turns(text, source_id)
        else:
            return self._chunk_by_paragraphs(text, source_type, source_id)

    # ── helpers ──────────────────────────────────────────────────────────────

    def _finalize(self, texts: list[str], source_type: str, source_id: str) -> list[RawChunk]:
        """Convert a list of text segments to RawChunks with correct index/total."""
        if not texts:
            return [
                RawChunk(
                    text="",
                    index=0,
                    total=1,
                    source_type=source_type,
                    source_id=source_id,
                    token_count=0,
                )
            ]
        total = len(texts)
        return [
            RawChunk(
                text=t,
                index=i,
                total=total,
                source_type=source_type,
                source_id=source_id,
                token_count=self.count_tokens(t),
            )
            for i, t in enumerate(texts)
        ]

    def _split_at_sentence_boundary(self, text: str) -> list[str]:
        """Split oversized text at sentence boundaries, never mid-sentence."""
        sentence_pattern = re.compile(r"(?<=[.!?])\s+")
        sentences = sentence_pattern.split(text)
        parts: list[str] = []
        current = ""
        for sentence in sentences:
            candidate = (current + " " + sentence).strip() if current else sentence
            if self.count_tokens(candidate) > self.max_tokens and current:
                parts.append(current)
                current = sentence
            else:
                current = candidate
        if current:
            parts.append(current)
        return parts if parts else [text]

    def _accumulate(self, segments: list[str]) -> list[str]:
        """Accumulate segments into chunks, never exceeding max_tokens."""
        chunks: list[str] = []
        current = ""
        for seg in segments:
            if self.count_tokens(seg) > self.max_tokens:
                # Segment is too big on its own — split at sentence boundary
                if current:
                    chunks.append(current)
                    current = ""
                chunks.extend(self._split_at_sentence_boundary(seg))
                continue
            candidate = (current + "\n\n" + seg).strip() if current else seg
            if self.count_tokens(candidate) > self.max_tokens and current:
                chunks.append(current)
                current = seg
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks if chunks else [""]

    # ── Slack ─────────────────────────────────────────────────────────────────

    def _chunk_slack(self, text: str, source_id: str) -> list[RawChunk]:
        """Chunk Slack export — handles both JSON and plaintext formats."""
        if not text.strip():
            return self._finalize([], "slack", source_id)

        # Try JSON parse
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return self._chunk_slack_json(data, source_id)
        except (json.JSONDecodeError, ValueError):
            pass

        return self._chunk_slack_plaintext(text, source_id)

    def _chunk_slack_json(self, messages: list[dict], source_id: str) -> list[RawChunk]:
        """Process structured Slack JSON export."""
        # Group by thread_ts (HARD split between threads)
        threads: dict[str, list[dict]] = {}
        thread_order: list[str] = []
        for msg in messages:
            ts = msg.get("thread_ts") or msg.get("ts", "root")
            if ts not in threads:
                threads[ts] = []
                thread_order.append(ts)
            threads[ts].append(msg)

        all_chunks: list[str] = []
        for ts in thread_order:
            thread_msgs = threads[ts]
            # Group consecutive same-author messages within thread
            groups = self._group_by_author_json(thread_msgs)
            # Accumulate groups into thread-level chunks
            thread_chunks = self._accumulate_groups(groups)
            all_chunks.extend(thread_chunks)

        return self._finalize(all_chunks, "slack", source_id)

    def _group_by_author_json(self, messages: list[dict]) -> list[str]:
        """Group consecutive same-author messages into single text blocks."""
        groups: list[str] = []
        current_author = None
        current_texts: list[str] = []

        for msg in messages:
            author = msg.get("user", "unknown")
            msg_text = msg.get("text", "").strip()
            if not msg_text:
                continue
            if author == current_author:
                current_texts.append(msg_text)
            else:
                if current_texts:
                    groups.append("\n".join(current_texts))
                current_author = author
                current_texts = [msg_text]

        if current_texts:
            groups.append("\n".join(current_texts))

        return groups

    def _accumulate_groups(self, groups: list[str]) -> list[str]:
        """Accumulate message groups into chunks, never splitting mid-message."""
        chunks: list[str] = []
        current = ""
        for group in groups:
            # Filter emoji-only groups
            if _is_emoji_only(group):
                continue
            if self.count_tokens(group) > self.max_tokens:
                if current:
                    chunks.append(current)
                    current = ""
                # Oversized group — split at sentence boundary
                chunks.extend(self._split_at_sentence_boundary(group))
                continue
            candidate = (current + "\n" + group).strip() if current else group
            if self.count_tokens(candidate) > self.max_tokens and current:
                chunks.append(current)
                current = group
            else:
                current = candidate
        if current:
            chunks.append(current)
        return chunks if chunks else [""]

    def _chunk_slack_plaintext(self, text: str, source_id: str) -> list[RawChunk]:
        """Chunk plaintext Slack format, splitting by thread separator or author pattern."""
        # Split by thread separator first (HARD split)
        thread_sections = re.split(r"\n---+\n", text)
        all_chunks: list[str] = []

        for section in thread_sections:
            lines = section.splitlines()
            # Detect author-prefixed lines: `^<@\w+>:` or `^[\w\s]+:`
            author_pattern = re.compile(r"^(<@\w+>|[\w][\w\s]*):\s*(.+)?$")
            groups: list[str] = []
            current_author: str | None = None
            current_texts: list[str] = []

            for line in lines:
                m = author_pattern.match(line)
                if m:
                    author = m.group(1)
                    content = (m.group(2) or "").strip()
                    if author == current_author:
                        if content:
                            current_texts.append(content)
                    else:
                        if current_texts:
                            groups.append("\n".join(current_texts))
                        current_author = author
                        current_texts = [content] if content else []
                else:
                    # Continuation line
                    stripped = line.strip()
                    if stripped:
                        current_texts.append(stripped)

            if current_texts:
                groups.append("\n".join(current_texts))

            if not groups:
                # No author pattern detected — treat as generic text
                groups = [section.strip()] if section.strip() else []

            all_chunks.extend(self._accumulate_groups(groups))

        return self._finalize(all_chunks, "slack", source_id)

    # ── Meeting transcript / document ──────────────────────────────────────────

    def _chunk_by_speaker_turns(self, text: str, source_id: str) -> list[RawChunk]:
        """Chunk by speaker turns for meeting transcripts and documents."""
        if not text.strip():
            return self._finalize([], "meeting_transcript", source_id)

        # Regex: line starts with optional bracket, speaker name, closing bracket/colon
        speaker_pattern = re.compile(r"^[\[({]?\s*([\w][\w\s]*)[\])}]?\s*:", re.MULTILINE)

        lines = text.splitlines()
        turns: list[tuple[str, str]] = []  # (speaker, text)
        current_speaker: str | None = None
        current_lines: list[str] = []

        for line in lines:
            m = speaker_pattern.match(line)
            if m:
                if current_lines and current_speaker is not None:
                    turns.append((current_speaker, "\n".join(current_lines).strip()))
                current_speaker = m.group(1).strip()
                # Rest of the line after the colon
                rest = line[m.end() :].strip()
                current_lines = [rest] if rest else []
            else:
                stripped = line.strip()
                if stripped:
                    current_lines.append(stripped)
                elif current_lines:
                    # Blank line acts as paragraph break within turn
                    current_lines.append("")

        if current_lines and current_speaker is not None:
            turns.append((current_speaker, "\n".join(current_lines).strip()))

        if not turns:
            # No speaker pattern found — fall back to paragraph chunking
            return self._chunk_by_paragraphs_generic(text, "meeting_transcript", source_id)

        # Group consecutive same-speaker turns
        groups: list[str] = []
        prev_speaker: str | None = None
        prev_text_parts: list[str] = []

        for speaker, turn_text in turns:
            if speaker == prev_speaker:
                prev_text_parts.append(turn_text)
            else:
                if prev_text_parts:
                    groups.append("\n".join(prev_text_parts))
                prev_speaker = speaker
                prev_text_parts = [turn_text]

        if prev_text_parts:
            groups.append("\n".join(prev_text_parts))

        segments = self._accumulate(groups)
        return self._finalize(segments, "meeting_transcript", source_id)

    # ── Generic paragraph ─────────────────────────────────────────────────────

    def _chunk_by_paragraphs(self, text: str, source_type: str, source_id: str) -> list[RawChunk]:
        """Split by \\n\\n paragraphs, oversized paragraphs split at sentence boundary."""
        return self._chunk_by_paragraphs_generic(text, source_type, source_id)

    def _chunk_by_paragraphs_generic(self, text: str, source_type: str, source_id: str) -> list[RawChunk]:
        if not text.strip():
            return self._finalize([], source_type, source_id)

        paragraphs = [p.strip() for p in re.split(r"\n\n+", text) if p.strip()]
        segments = self._accumulate(paragraphs)
        return self._finalize(segments, source_type, source_id)
