#!/usr/bin/env python3
"""Sanitize a production Slack JSONL export into an anonymized bench fixture.

Usage:
    uv run python scripts/sanitize_corpus.py \\
      --input <raw.jsonl> \\
      --output <sanitized.jsonl> \\
      --company-name Globex \\
      --seed 42 \\
      [--time-shift-days 365] \\
      [--mapping-out <file.mapping.json>]

Exit codes:
    0  — success
    1  — secret pattern detected (halts immediately, no output written)
    2  — malformed input (JSON parse error or missing required field)
    3  — I/O error

The script NEVER pulls production data — it only transforms an existing local JSONL file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, cast

# ---------------------------------------------------------------------------
# Secret detection patterns — FAIL the run (do not replace)
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("anthropic_key", re.compile(r"sk-ant-[A-Za-z0-9_-]{40,}")),  # Anthropic sk-ant-* format
    ("openai_key", re.compile(r"sk-[A-Za-z0-9_-]{20,}")),  # OpenAI-style (also catches short sk-ant if first misses)
    ("github_pat", re.compile(r"ghp_[A-Za-z0-9]{20,}")),
    ("aws_access_key", re.compile(r"AKIA[A-Z0-9]{16}")),
    ("jwt", re.compile(r"eyJ[A-Za-z0-9_-]{20,}\.")),
    ("aws_secret_config", re.compile(r"aws_secret_access_key\s*=")),
]

# Required fields in each input record
_REQUIRED_FIELDS = ("id", "raw_text", "ts", "channel_id", "actor")

# ---------------------------------------------------------------------------
# Counter registry — deterministic per-run NN assignments
# ---------------------------------------------------------------------------


class _CounterRegistry:
    """Maps real values to deterministic fake IDs using counters.

    Counters are seeded deterministically: the first time a real value is
    seen (in input order) it gets the next integer in sequence.  Same seed +
    same input order => same output.
    """

    def __init__(self) -> None:
        self._users: dict[str, int] = {}
        self._channels: dict[str, int] = {}
        self._emails: dict[str, int] = {}
        self._phones: dict[str, str] = {}  # real -> fake phone string
        self._names: dict[str, str] = {}  # real -> fake name string

    def get_user_nn(self, real_id: str) -> int:
        if real_id not in self._users:
            self._users[real_id] = len(self._users) + 1
        return self._users[real_id]

    def get_channel_nn(self, real_id: str) -> int:
        if real_id not in self._channels:
            self._channels[real_id] = len(self._channels) + 1
        return self._channels[real_id]

    def get_email_nn(self, real_email: str) -> int:
        if real_email not in self._emails:
            self._emails[real_email] = len(self._emails) + 1
        return self._emails[real_email]

    def register_phone(self, real_phone: str, fake_phone: str) -> None:
        if real_phone not in self._phones:
            self._phones[real_phone] = fake_phone

    def get_phone(self, real_phone: str) -> str | None:
        return self._phones.get(real_phone)

    def register_name(self, real_name: str, fake_name: str) -> None:
        if real_name not in self._names:
            self._names[real_name] = fake_name

    def get_name(self, real_name: str) -> str | None:
        return self._names.get(real_name)

    def to_mapping(self) -> dict[str, str]:
        """Return a flat {real -> fake} mapping for operator verification."""
        result: dict[str, str] = {}
        for real_id, nn in self._users.items():
            result[real_id] = f"U_FAKE_{nn:02d}"
        for real_id, nn in self._channels.items():
            result[real_id] = f"C_FAKE_{nn:02d}"
        for real_email, nn in self._emails.items():
            result[real_email] = f"user_{nn:02d}@example.com"
        for real_phone, fake_phone in self._phones.items():
            result[real_phone] = fake_phone
        for real_name, fake_name in self._names.items():
            result[real_name] = fake_name
        return result


# ---------------------------------------------------------------------------
# Sanitizer
# ---------------------------------------------------------------------------


class CorpusSanitizer:
    """Performs deterministic PII scrubbing on a stream of JSONL event records."""

    # Slack-formatted URL: <https://...>
    _RE_SLACK_URL = re.compile(r"<https?://[^>]+>")
    # Bare URL
    _RE_BARE_URL = re.compile(r"https?://[^\s<>\"']+")
    # Slack user mention: <@U...>
    _RE_SLACK_USER = re.compile(r"<@(U[A-Z0-9]+)>")
    # Slack channel mention: <#C...|name>
    _RE_SLACK_CHANNEL = re.compile(r"<#(C[A-Z0-9]+)\|[^>]*>")
    # Email address
    _RE_EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    # Phone number (generous pattern — prefer recall over precision)
    # Matches: +7 (495) 123-45-67, 8-800-555-35-35, (123) 456-7890, +1-800-123-4567 etc.
    _RE_PHONE = re.compile(
        r"""
        (?:
            \+?\d{1,3}[\s\-\.]?      # optional country code
            (?:\(\d{2,4}\)[\s\-\.]?) # optional area code in parens
            \d{3}[\s\-\.]\d{2}[\s\-\.]\d{2}  # Russian-style NXX-XX-XX
        |
            \+?\d{1,3}[\s\-\.]?
            \d{3}[\s\-\.]
            \d{3}[\s\-\.]
            \d{4}           # North American style
        |
            8[\s\-]?\d{3}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}  # 8-XXX-XXX-XX-XX
        )
        """,
        re.VERBOSE,
    )

    def __init__(
        self,
        company_name: str,
        seed: int,
        time_shift_seconds: int,
        registry: _CounterRegistry,
        faker_instance: Any,
        nlp_models: list[Any],
    ) -> None:
        self._company_name = company_name
        self._seed = seed
        self._time_shift_seconds = time_shift_seconds
        self._registry = registry
        self._faker = faker_instance
        self._nlp_models = nlp_models

        # Build company-name regex from the replacement target name to detect
        # the real company name patterns (ticketscloud, tickets cloud, tcloud)
        # Note: operator can pass any company name in --company-name; the patterns
        # we detect in raw text are the common variations of "Ticketscloud".
        # We match them case-insensitively and replace with the --company-name value.
        self._re_company = re.compile(
            r"\b(?:ticketscloud|tickets\s+cloud|tcloud)\b",
            re.IGNORECASE,
        )

    def _get_url_hash(self, url: str) -> str:
        """Return an 8-char hex hash for a URL, deterministic per content."""
        return hashlib.md5(url.encode(), usedforsecurity=False).hexdigest()[:8]

    def _replace_slack_users(self, text: str) -> str:
        def _sub(m: re.Match[str]) -> str:
            real_id = m.group(1)
            nn = self._registry.get_user_nn(real_id)
            return f"<@U_FAKE_{nn:02d}>"

        return self._RE_SLACK_USER.sub(_sub, text)

    def _replace_slack_channels(self, text: str) -> str:
        def _sub(m: re.Match[str]) -> str:
            real_id = m.group(1)
            nn = self._registry.get_channel_nn(real_id)
            return f"<#C_FAKE_{nn:02d}|fake-channel>"

        return self._RE_SLACK_CHANNEL.sub(_sub, text)

    def _replace_urls(self, text: str) -> str:
        # Replace Slack-formatted URLs first
        def _sub_slack(m: re.Match[str]) -> str:
            url = m.group(0)[1:-1]  # strip < >
            h = self._get_url_hash(url)
            return f"<https://example.com/{h}>"

        text = self._RE_SLACK_URL.sub(_sub_slack, text)

        # Replace bare URLs
        def _sub_bare(m: re.Match[str]) -> str:
            url = m.group(0)
            h = self._get_url_hash(url)
            return f"https://example.com/{h}"

        return self._RE_BARE_URL.sub(_sub_bare, text)

    def _replace_emails(self, text: str) -> str:
        def _sub(m: re.Match[str]) -> str:
            email = m.group(0)
            nn = self._registry.get_email_nn(email)
            return f"user_{nn:02d}@example.com"

        return self._RE_EMAIL.sub(_sub, text)

    def _replace_phones(self, text: str) -> str:
        def _sub(m: re.Match[str]) -> str:
            real_phone = m.group(0)
            existing = self._registry.get_phone(real_phone)
            if existing is not None:
                return existing
            fake = self._faker.phone_number()
            self._registry.register_phone(real_phone, fake)
            return fake

        return self._RE_PHONE.sub(_sub, text)

    def _replace_company_name(self, text: str) -> str:
        return self._re_company.sub(self._company_name, text)

    def _replace_person_names_spacy(self, text: str) -> str:
        """Use spaCy NER to find PERSON entities and replace them with fake names."""
        if not self._nlp_models:
            return text
        # Collect all PERSON spans from all models, sort by start pos descending
        # to avoid index shifting when replacing
        all_spans: list[tuple[int, int, str]] = []
        for nlp in self._nlp_models:
            try:
                doc = nlp(text)
                for ent in doc.ents:
                    if ent.label_ == "PERSON":
                        all_spans.append((ent.start_char, ent.end_char, ent.text))
            except Exception:
                continue
        if not all_spans:
            return text
        # Remove duplicates, sort by start descending
        seen: set[tuple[int, int]] = set()
        unique: list[tuple[int, int, str]] = []
        for start, end, ent_text in sorted(all_spans, key=lambda x: x[0], reverse=True):
            key = (start, end)
            if key not in seen:
                seen.add(key)
                unique.append((start, end, ent_text))
        # Replace in reverse order to preserve indices
        result = text
        for start, end, ent_text in unique:
            existing = self._registry.get_name(ent_text)
            if existing is None:
                existing = self._faker.name()
                self._registry.register_name(ent_text, existing)
            result = result[:start] + existing + result[end:]
        return result

    def sanitize_text(self, text: str) -> str:
        """Apply all text-level sanitization rules in order."""
        text = self._replace_slack_users(text)
        text = self._replace_slack_channels(text)
        text = self._replace_urls(text)
        text = self._replace_emails(text)
        text = self._replace_phones(text)
        text = self._replace_company_name(text)
        text = self._replace_person_names_spacy(text)
        return text

    def sanitize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Sanitize a single event record, returning a new dict.

        Output is built from an explicit allowlist to prevent production identifiers
        (e.g. source_id encodes real channel ID + timestamp) from passing through.
        Allowed fields: id, raw_text, ts, channel_id, actor, thread_ts.
        """
        # id is an opaque UUID — safe to keep as-is
        out: dict[str, Any] = {"id": record["id"]}

        # Sanitize raw_text
        out["raw_text"] = self.sanitize_text(record["raw_text"])

        # Shift timestamps
        ts_val = int(record["ts"]) - self._time_shift_seconds
        out["ts"] = str(ts_val)

        # Replace channel_id field
        real_channel = str(record["channel_id"])
        nn = self._registry.get_channel_nn(real_channel)
        out["channel_id"] = f"C_FAKE_{nn:02d}"

        # Replace actor field
        real_actor = str(record["actor"])
        nn_actor = self._registry.get_user_nn(real_actor)
        out["actor"] = f"U_FAKE_{nn_actor:02d}"

        # thread_ts is optional — shift if present
        if "thread_ts" in record and record["thread_ts"] is not None:
            thread_ts_val = int(record["thread_ts"]) - self._time_shift_seconds
            out["thread_ts"] = str(thread_ts_val)

        return out


# ---------------------------------------------------------------------------
# Secret detection
# ---------------------------------------------------------------------------


def _check_secrets(text: str, line_num: int) -> list[tuple[int, str, str]]:
    """Return list of (line_num, pattern_name, matched_text) for any secrets found."""
    hits: list[tuple[int, str, str]] = []
    for name, pattern in _SECRET_PATTERNS:
        m = pattern.search(text)
        if m:
            hits.append((line_num, name, m.group(0)))
    return hits


# ---------------------------------------------------------------------------
# NLP model loading (optional)
# ---------------------------------------------------------------------------


def _load_nlp_models(verbose: bool = True) -> list[Any]:
    """Try to load spaCy models. Returns list of loaded models (may be empty)."""
    models: list[Any] = []
    try:
        import spacy
    except ImportError:
        if verbose:
            print(
                "============================================================\n"
                "WARNING: spaCy is not installed.\n"
                "PERSON NAMES IN raw_text WILL NOT BE REDACTED.\n"
                "Install with: uv pip install spacy\n"
                "Then download models: python -m spacy download en_core_web_sm ru_core_news_sm\n"
                "============================================================",
                file=sys.stderr,
            )
        return models

    for model_name in ("en_core_web_sm", "ru_core_news_sm"):
        try:
            nlp = spacy.load(model_name)
            models.append(nlp)
        except OSError:
            if verbose:
                print(
                    "============================================================\n"
                    f"WARNING: spaCy model '{model_name}' is not installed.\n"
                    "PERSON NAMES IN raw_text WILL NOT BE REDACTED.\n"
                    f"Fix: python -m spacy download {model_name}\n"
                    "============================================================",
                    file=sys.stderr,
                )
    return models


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sanitize a production Slack JSONL export into an anonymized bench fixture.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--input", required=True, help="Path to raw JSONL input file")
    parser.add_argument("--output", required=True, help="Path to sanitized JSONL output file")
    parser.add_argument("--company-name", required=True, help="Replacement company name (e.g. Globex)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for faker (default: 42)")
    parser.add_argument(
        "--time-shift-days",
        type=int,
        default=365,
        help="Shift timestamps back by N days (default: 365)",
    )
    parser.add_argument(
        "--mapping-out",
        default=None,
        help="Optional path to write {real -> fake} mapping JSON for operator review",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    output_path = Path(args.output)
    time_shift_seconds = args.time_shift_days * 86400

    # Invalidate any stale output from a previous run before doing any work.
    output_path.unlink(missing_ok=True)
    if args.mapping_out:
        Path(args.mapping_out).unlink(missing_ok=True)

    # Initialize faker with seed for determinism
    try:
        from faker import Faker
    except ImportError:
        print("error: faker not installed — run: uv sync --all-packages --dev", file=sys.stderr)
        return 3

    faker_instance = Faker()
    Faker.seed(args.seed)

    # Load spaCy models (non-fatal if absent)
    nlp_models = _load_nlp_models(verbose=True)

    registry = _CounterRegistry()
    sanitizer = CorpusSanitizer(
        company_name=args.company_name,
        seed=args.seed,
        time_shift_seconds=time_shift_seconds,
        registry=registry,
        faker_instance=faker_instance,
        nlp_models=nlp_models,
    )

    # First pass: read all lines, check for secrets before writing any output
    try:
        raw_text_content = input_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read input file: {exc}", file=sys.stderr)
        return 3

    lines = raw_text_content.splitlines()

    # Validate and collect parsed records in order
    records: list[tuple[int, dict[str, Any]]] = []
    secret_hits: list[tuple[int, str, str]] = []

    for line_num, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue

        # Parse JSON
        try:
            parsed: Any = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"error: line {line_num}: invalid JSON: {exc}", file=sys.stderr)
            return 2

        if not isinstance(parsed, dict):
            print(f"error: line {line_num}: expected JSON object, got {type(parsed).__name__}", file=sys.stderr)
            return 2

        record: dict[str, Any] = cast("dict[str, Any]", parsed)

        # Check required fields
        missing = [f for f in _REQUIRED_FIELDS if f not in record]
        if missing:
            print(f"error: line {line_num}: missing required fields: {missing}", file=sys.stderr)
            return 2

        # Secret detection on full line text
        hits = _check_secrets(line, line_num)
        secret_hits.extend(hits)

        records.append((line_num, record))

    # If any secrets found, report and exit without writing output
    if secret_hits:
        print(
            f"FATAL: {len(secret_hits)} secret pattern(s) detected — aborting. No output written.",
            file=sys.stderr,
        )
        for line_num, pattern_name, matched in secret_hits:
            # Redact the actual secret value in the error message
            redacted = matched[:4] + "***"
            print(f"  line {line_num}: [{pattern_name}] {redacted}", file=sys.stderr)
        return 1

    # Second pass: sanitize and write output
    try:
        with output_path.open("w", encoding="utf-8") as out_fh:
            for _line_num, record in records:
                sanitized = sanitizer.sanitize_record(record)
                out_fh.write(json.dumps(sanitized, ensure_ascii=False) + "\n")
    except OSError as exc:
        print(f"error: cannot write output file: {exc}", file=sys.stderr)
        return 3

    # Write mapping file if requested
    if args.mapping_out:
        mapping = registry.to_mapping()
        try:
            Path(args.mapping_out).write_text(
                json.dumps(mapping, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(
                f"WARNING: mapping file {args.mapping_out} contains the real -> fake bridge for this corpus.\n"
                "Anyone with raw + mapping can de-anonymize the data.\n"
                "Delete it after audit. Never commit.",
                file=sys.stderr,
            )
        except OSError as exc:
            print(f"warn: could not write mapping file: {exc}", file=sys.stderr)

    total_records = len(records)
    print(f"sanitized {total_records} records -> {output_path}", file=sys.stderr)

    # Final summary: spaCy model count
    loaded = len(nlp_models)
    total_expected = 2
    if loaded == 0:
        spacy_note = f"={loaded}/{total_expected} — PERSON NAMES NOT REDACTED IN raw_text"
    else:
        spacy_note = f"={loaded}/{total_expected}"
    print(f"summary: spacy_models_loaded{spacy_note}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
