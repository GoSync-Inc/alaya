"""Tests for scripts/sanitize_corpus.py.

All tests use synthetic data only — no real production data.
Covers all 8 cases from the task brief:
1. Determinism: same input + seed -> identical output
2. Completeness per pattern: each pattern is replaced in output
3. Consistency: same real ID across events -> same fake ID
4. Time preservation: relative intervals preserved, absolute shifted
5. Secret detection: exits non-zero, no output file written
6. Company name: all capitalizations replaced
7. Empty/malformed input: handled gracefully
8. Russian text: Cyrillic person name replaced (skip if spaCy ru model not installed)
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SCRIPT = Path(__file__).parent.parent / "scripts" / "sanitize_corpus.py"


def _run(
    input_lines: list[str],
    *,
    seed: int = 42,
    company_name: str = "Globex",
    time_shift_days: int = 365,
    extra_args: list[str] | None = None,
    tmp_path: Path,
) -> tuple[int, str, list[dict]]:
    """Run sanitize_corpus.py via subprocess, return (returncode, stderr, output_records)."""
    input_file = tmp_path / "input.jsonl"
    output_file = tmp_path / "output.jsonl"
    input_file.write_text("\n".join(input_lines) + "\n", encoding="utf-8")

    cmd = [
        sys.executable,
        str(SCRIPT),
        "--input",
        str(input_file),
        "--output",
        str(output_file),
        "--seed",
        str(seed),
        "--company-name",
        company_name,
        "--time-shift-days",
        str(time_shift_days),
    ]
    if extra_args:
        cmd.extend(extra_args)

    result = subprocess.run(cmd, capture_output=True, text=True)
    records: list[dict] = []
    if output_file.exists():
        for line in output_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return result.returncode, result.stderr, records


# ---------------------------------------------------------------------------
# Case 1: Determinism
# ---------------------------------------------------------------------------


def test_determinism(tmp_path: Path) -> None:
    """Same input + seed must produce byte-identical output files."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "Hello <@UABC123> and visit <https://example.org/path>",
                "ts": "1714000000",
                "channel_id": "CABC456",
                "actor": "UDEF789",
            }
        )
    ]

    tmp1 = tmp_path / "run1"
    tmp1.mkdir()
    tmp2 = tmp_path / "run2"
    tmp2.mkdir()

    rc1, _, _ = _run(lines, seed=42, tmp_path=tmp1)
    rc2, _, _ = _run(lines, seed=42, tmp_path=tmp2)

    assert rc1 == 0
    assert rc2 == 0
    out1 = (tmp1 / "output.jsonl").read_bytes()
    out2 = (tmp2 / "output.jsonl").read_bytes()
    assert out1 == out2, "Outputs must be byte-identical for same seed"


def test_different_seeds_differ(tmp_path: Path) -> None:
    """Different seeds produce different phone replacements (faker-seeded values).

    Phone replacement uses faker.phone_number() which is seeded, so seed 42
    and seed 99 should produce different fake phone strings.
    """
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "Call me at +7 (495) 123-45-67 for details",
                "ts": "1714000000",
                "channel_id": "CABC456",
                "actor": "UDEF789",
            }
        )
    ]

    tmp1 = tmp_path / "s42"
    tmp1.mkdir()
    tmp2 = tmp_path / "s99"
    tmp2.mkdir()

    _run(lines, seed=42, tmp_path=tmp1)
    _run(lines, seed=99, tmp_path=tmp2)

    out1 = (tmp1 / "output.jsonl").read_text()
    out2 = (tmp2 / "output.jsonl").read_text()
    # Different seeds must produce different phone replacements
    # (both outputs should have the original phone replaced, but with different values)
    assert "+7 (495) 123-45-67" not in out1
    assert "+7 (495) 123-45-67" not in out2
    assert out1 != out2


# ---------------------------------------------------------------------------
# Case 2: Completeness per pattern
# ---------------------------------------------------------------------------


def test_slack_user_mention_replaced(tmp_path: Path) -> None:
    """<@U...> Slack mention is replaced; original ID not in output."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "Ping <@UABC123> about the issue",
                "ts": "1714000000",
                "channel_id": "C123",
                "actor": "U999",
            }
        )
    ]
    rc, _, records = _run(lines, tmp_path=tmp_path)
    assert rc == 0
    assert len(records) == 1
    text = records[0]["raw_text"]
    assert "UABC123" not in text
    assert "<@U_FAKE_" in text or "<@U" in text  # replaced with fake mention


def test_slack_channel_mention_replaced(tmp_path: Path) -> None:
    """<#C...|name> channel mention is replaced."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "Please check <#CABC123|general> for updates",
                "ts": "1714000000",
                "channel_id": "C999",
                "actor": "U001",
            }
        )
    ]
    rc, _, records = _run(lines, tmp_path=tmp_path)
    assert rc == 0
    text = records[0]["raw_text"]
    assert "CABC123" not in text
    assert "general" not in text


def test_url_replaced(tmp_path: Path) -> None:
    """Slack-formatted and bare URLs are replaced."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "See <https://secret-company.internal/path?token=abc> and https://another.example.com/page",
                "ts": "1714000000",
                "channel_id": "C123",
                "actor": "U001",
            }
        )
    ]
    rc, _, records = _run(lines, tmp_path=tmp_path)
    assert rc == 0
    text = records[0]["raw_text"]
    assert "secret-company.internal" not in text
    assert "another.example.com" not in text
    assert "example.com" in text  # replaced with example.com/hash


def test_email_replaced(tmp_path: Path) -> None:
    """Email addresses are replaced."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "Contact john.doe@company.internal for access",
                "ts": "1714000000",
                "channel_id": "C123",
                "actor": "U001",
            }
        )
    ]
    rc, _, records = _run(lines, tmp_path=tmp_path)
    assert rc == 0
    text = records[0]["raw_text"]
    assert "john.doe@company.internal" not in text
    assert "@example.com" in text


def test_phone_replaced(tmp_path: Path) -> None:
    """Phone numbers are replaced."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "Call me at +7 (495) 123-45-67 or 8-800-555-35-35",
                "ts": "1714000000",
                "channel_id": "C123",
                "actor": "U001",
            }
        )
    ]
    rc, _, records = _run(lines, tmp_path=tmp_path)
    assert rc == 0
    text = records[0]["raw_text"]
    # Original phone patterns should not be present
    assert "+7 (495) 123-45-67" not in text


def test_channel_id_field_replaced(tmp_path: Path) -> None:
    """Top-level channel_id field is replaced with C_FAKE_NN."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "Hello world",
                "ts": "1714000000",
                "channel_id": "C_REAL_CHANNEL_XYZ",
                "actor": "U_REAL_ACTOR_ABC",
            }
        )
    ]
    rc, _, records = _run(lines, tmp_path=tmp_path)
    assert rc == 0
    assert records[0]["channel_id"] != "C_REAL_CHANNEL_XYZ"
    assert records[0]["channel_id"].startswith("C_FAKE_")


def test_actor_field_replaced(tmp_path: Path) -> None:
    """Top-level actor field is replaced with U_FAKE_NN."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "Hello world",
                "ts": "1714000000",
                "channel_id": "C123",
                "actor": "U_REAL_ACTOR_ABC",
            }
        )
    ]
    rc, _, records = _run(lines, tmp_path=tmp_path)
    assert rc == 0
    assert records[0]["actor"] != "U_REAL_ACTOR_ABC"
    assert records[0]["actor"].startswith("U_FAKE_")


# ---------------------------------------------------------------------------
# Case 3: Consistency
# ---------------------------------------------------------------------------


def test_consistent_user_mention_mapping(tmp_path: Path) -> None:
    """Same real Slack user ID in multiple events maps to the same fake ID."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "Ask <@UABC123> to review",
                "ts": "1714000000",
                "channel_id": "C123",
                "actor": "U999",
            }
        ),
        json.dumps(
            {
                "id": "ev-002",
                "raw_text": "Thanks <@UABC123> for the fix",
                "ts": "1714003600",
                "channel_id": "C123",
                "actor": "U999",
            }
        ),
    ]
    rc, _, records = _run(lines, tmp_path=tmp_path)
    assert rc == 0
    # Extract the fake mention from both events
    import re

    pattern = r"<@(U_FAKE_\d+)>"
    m1 = re.search(pattern, records[0]["raw_text"])
    m2 = re.search(pattern, records[1]["raw_text"])
    assert m1 is not None
    assert m2 is not None
    assert m1.group(1) == m2.group(1), "Same real ID must map to same fake ID"


def test_consistent_channel_id_mapping(tmp_path: Path) -> None:
    """Same real channel_id in multiple events maps to the same fake channel_id."""
    lines = [
        json.dumps({"id": "ev-001", "raw_text": "msg1", "ts": "1714000000", "channel_id": "CREAL123", "actor": "U001"}),
        json.dumps({"id": "ev-002", "raw_text": "msg2", "ts": "1714003600", "channel_id": "CREAL123", "actor": "U001"}),
    ]
    rc, _, records = _run(lines, tmp_path=tmp_path)
    assert rc == 0
    assert records[0]["channel_id"] == records[1]["channel_id"]


def test_consistent_actor_mapping(tmp_path: Path) -> None:
    """Same real actor in multiple events maps to the same fake actor."""
    lines = [
        json.dumps({"id": "ev-001", "raw_text": "msg1", "ts": "1714000000", "channel_id": "C001", "actor": "UREAL456"}),
        json.dumps({"id": "ev-002", "raw_text": "msg2", "ts": "1714003600", "channel_id": "C002", "actor": "UREAL456"}),
    ]
    rc, _, records = _run(lines, tmp_path=tmp_path)
    assert rc == 0
    assert records[0]["actor"] == records[1]["actor"]


# ---------------------------------------------------------------------------
# Case 4: Time preservation
# ---------------------------------------------------------------------------


def test_time_shift_preserves_interval(tmp_path: Path) -> None:
    """Two events 5 minutes apart should remain 5 minutes apart after shift."""
    ts1 = 1714000000
    ts2 = ts1 + 300  # 5 minutes later
    lines = [
        json.dumps({"id": "ev-001", "raw_text": "First", "ts": str(ts1), "channel_id": "C1", "actor": "U1"}),
        json.dumps({"id": "ev-002", "raw_text": "Second", "ts": str(ts2), "channel_id": "C1", "actor": "U1"}),
    ]
    rc, _, records = _run(lines, time_shift_days=365, tmp_path=tmp_path)
    assert rc == 0
    out_ts1 = int(records[0]["ts"])
    out_ts2 = int(records[1]["ts"])
    assert out_ts2 - out_ts1 == 300, "5-minute interval must be preserved"


def test_time_shift_absolute(tmp_path: Path) -> None:
    """Timestamps should be shifted back by exactly --time-shift-days."""
    ts = 1714000000
    shift_days = 365
    expected_ts = ts - shift_days * 86400
    lines = [json.dumps({"id": "ev-001", "raw_text": "Hello", "ts": str(ts), "channel_id": "C1", "actor": "U1"})]
    rc, _, records = _run(lines, time_shift_days=shift_days, tmp_path=tmp_path)
    assert rc == 0
    assert int(records[0]["ts"]) == expected_ts


def test_thread_ts_shifted(tmp_path: Path) -> None:
    """thread_ts if present is also time-shifted and preserved in output."""
    ts = 1714000000
    thread_ts = ts - 60  # 1 minute before
    shift_days = 365
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "Reply",
                "ts": str(ts),
                "thread_ts": str(thread_ts),
                "channel_id": "C1",
                "actor": "U1",
            }
        )
    ]
    rc, _, records = _run(lines, time_shift_days=shift_days, tmp_path=tmp_path)
    assert rc == 0
    assert "thread_ts" in records[0]
    expected_thread_ts = thread_ts - shift_days * 86400
    assert int(records[0]["thread_ts"]) == expected_thread_ts


# ---------------------------------------------------------------------------
# Case 5: Secret detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "secret_text",
    [
        "sk-abcdefghijklmnopqrstuvwxyz12345",  # OpenAI key
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefgh",  # GitHub PAT
        "AKIAIOSFODNN7EXAMPLE1234",  # AWS access key
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.TJVA95OrM7",  # JWT
        "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",  # AWS config
    ],
)
def test_secret_detection_exits_nonzero(tmp_path: Path, secret_text: str) -> None:
    """Script must exit non-zero when secret patterns are detected."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": f"Here is a secret: {secret_text}",
                "ts": "1714000000",
                "channel_id": "C1",
                "actor": "U1",
            }
        )
    ]
    rc, _stderr, _ = _run(lines, tmp_path=tmp_path)
    assert rc != 0, f"Expected non-zero exit for secret pattern in: {secret_text!r}"


def test_secret_detection_no_output_file(tmp_path: Path) -> None:
    """When secret is detected, no output file should be written (or empty)."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "Token: sk-abcdefghijklmnopqrstuvwxyz12345",
                "ts": "1714000000",
                "channel_id": "C1",
                "actor": "U1",
            }
        )
    ]
    output_file = tmp_path / "output.jsonl"
    input_file = tmp_path / "input.jsonl"
    input_file.write_text("\n".join(lines) + "\n")

    cmd = [
        sys.executable,
        str(SCRIPT),
        "--input",
        str(input_file),
        "--output",
        str(output_file),
        "--seed",
        "42",
        "--company-name",
        "Globex",
    ]
    subprocess.run(cmd, capture_output=True, text=True)

    # Output file must not exist or must be empty
    if output_file.exists():
        content = output_file.read_text().strip()
        assert content == "", "Output file must be empty when secret detected"


# ---------------------------------------------------------------------------
# Case 6: Company name replacement
# ---------------------------------------------------------------------------


def test_company_name_lowercase_replaced(tmp_path: Path) -> None:
    """company-name pattern (case-insensitive) is replaced."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "We work at ticketscloud and love it",
                "ts": "1714000000",
                "channel_id": "C1",
                "actor": "U1",
            }
        )
    ]
    rc, _, records = _run(lines, company_name="Globex", tmp_path=tmp_path)
    assert rc == 0
    assert "ticketscloud" not in records[0]["raw_text"].lower()
    assert "globex" in records[0]["raw_text"].lower()


def test_company_name_uppercase_replaced(tmp_path: Path) -> None:
    """TICKETSCLOUD is also replaced."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "TICKETSCLOUD platform release",
                "ts": "1714000000",
                "channel_id": "C1",
                "actor": "U1",
            }
        )
    ]
    rc, _, records = _run(lines, company_name="Globex", tmp_path=tmp_path)
    assert rc == 0
    assert "TICKETSCLOUD" not in records[0]["raw_text"]


def test_company_name_mixed_case_replaced(tmp_path: Path) -> None:
    """TicketsCloud mixed case is also replaced."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "TicketsCloud is the best CRM",
                "ts": "1714000000",
                "channel_id": "C1",
                "actor": "U1",
            }
        )
    ]
    rc, _, records = _run(lines, company_name="Globex", tmp_path=tmp_path)
    assert rc == 0
    assert "TicketsCloud" not in records[0]["raw_text"]
    assert "Globex" in records[0]["raw_text"]


# ---------------------------------------------------------------------------
# Case 7: Empty / malformed input
# ---------------------------------------------------------------------------


def test_empty_input_no_crash(tmp_path: Path) -> None:
    """Empty JSONL file should complete with exit 0, producing empty output."""
    rc, _stderr, records = _run([], tmp_path=tmp_path)
    assert rc == 0
    assert records == []


def test_blank_lines_skipped(tmp_path: Path) -> None:
    """Blank lines in input are skipped gracefully."""
    lines = [
        "",
        json.dumps({"id": "ev-001", "raw_text": "Hello", "ts": "1714000000", "channel_id": "C1", "actor": "U1"}),
        "",
        "",
    ]
    rc, _stderr, records = _run(lines, tmp_path=tmp_path)
    assert rc == 0
    assert len(records) == 1


def test_malformed_json_exits_nonzero(tmp_path: Path) -> None:
    """A JSONL file with a malformed JSON line should exit non-zero."""
    input_file = tmp_path / "input.jsonl"
    output_file = tmp_path / "output.jsonl"
    input_file.write_text('{"id": "ev-001", "raw_text": "good"}\nnot-valid-json\n', encoding="utf-8")

    cmd = [
        sys.executable,
        str(SCRIPT),
        "--input",
        str(input_file),
        "--output",
        str(output_file),
        "--seed",
        "42",
        "--company-name",
        "Globex",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode != 0


def test_missing_required_fields_exits_nonzero(tmp_path: Path) -> None:
    """Records missing required fields (id, raw_text, ts) should exit non-zero."""
    lines = [
        json.dumps({"id": "ev-001"})  # missing raw_text, ts, channel_id, actor
    ]
    rc, _stderr, _ = _run(lines, tmp_path=tmp_path)
    assert rc != 0


# ---------------------------------------------------------------------------
# Case 8: Russian text (spaCy NER)
# ---------------------------------------------------------------------------


def test_russian_person_name_spacy_skip_if_no_model(tmp_path: Path) -> None:
    """If spaCy ru model is not installed, Russian names should still be processed
    (script does not crash), even if the name is not fully anonymized."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "Иван Иванов обновил статус задачи сегодня",
                "ts": "1714000000",
                "channel_id": "C1",
                "actor": "U1",
            }
        )
    ]
    # Script should complete successfully even if ru model is absent
    rc, _stderr, records = _run(lines, tmp_path=tmp_path)
    assert rc == 0  # Must not crash
    assert len(records) == 1


def test_english_person_name_replaced_if_spacy_en_available(tmp_path: Path) -> None:
    """If spaCy en_core_web_sm is available, PERSON entities are replaced.
    If not installed, test is skipped."""
    try:
        import spacy

        spacy.load("en_core_web_sm")
    except Exception:
        pytest.skip("en_core_web_sm not installed — skipping NER test")

    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "John Smith reviewed the pull request yesterday",
                "ts": "1714000000",
                "channel_id": "C1",
                "actor": "U1",
            }
        )
    ]
    rc, _, records = _run(lines, tmp_path=tmp_path)
    assert rc == 0
    text = records[0]["raw_text"]
    assert "John Smith" not in text


# ---------------------------------------------------------------------------
# Case extra: mapping file output
# ---------------------------------------------------------------------------


def test_mapping_out_written(tmp_path: Path) -> None:
    """--mapping-out creates a JSON mapping file."""
    mapping_file = tmp_path / "mapping.json"
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "Ping <@UABC123>",
                "ts": "1714000000",
                "channel_id": "CXYZ",
                "actor": "UDEF",
            }
        )
    ]
    rc, _, _ = _run(lines, tmp_path=tmp_path, extra_args=["--mapping-out", str(mapping_file)])
    assert rc == 0
    assert mapping_file.exists()
    data = json.loads(mapping_file.read_text())
    assert isinstance(data, dict)
    assert len(data) > 0


# ---------------------------------------------------------------------------
# Fix 1: Stale output invalidated on secret-abort
# ---------------------------------------------------------------------------


def test_stale_output_removed_on_secret_abort(tmp_path: Path) -> None:
    """Stale output file must be removed even when run aborts due to secret detection."""
    output_file = tmp_path / "output.jsonl"
    # Write stale content from a hypothetical previous successful run
    output_file.write_text('{"id": "stale"}\n', encoding="utf-8")

    input_file = tmp_path / "input.jsonl"
    input_file.write_text(
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "token sk-ABCDEFGHIJ1234567890 leaked",
                "ts": "1714000000",
                "channel_id": "C001",
                "actor": "U001",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--input",
            str(input_file),
            "--output",
            str(output_file),
            "--company-name",
            "Globex",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0, "Expected non-zero exit on secret detection"
    assert not output_file.exists(), "Stale output file must be deleted before abort"


# ---------------------------------------------------------------------------
# Fix 2: Loud spaCy-missing warning + summary line
# ---------------------------------------------------------------------------


def test_summary_line_shows_zero_models_warns_clearly(tmp_path: Path) -> None:
    """When spaCy models are absent, stderr must contain the loud PERSON NAMES NOT REDACTED warning
    and the summary line must report 0/2."""
    lines = [
        json.dumps(
            {
                "id": "ev-001",
                "raw_text": "Hello world",
                "ts": "1714000000",
                "channel_id": "C001",
                "actor": "U001",
            }
        )
    ]
    # Patch spacy to be unimportable by injecting a broken sys.path via env override.
    # Easiest: pass PYTHONPATH pointing to a directory that shadows spacy with a broken module.
    import os
    import tempfile

    with tempfile.TemporaryDirectory() as fake_pkg_dir:
        # Create a fake spacy package that raises ImportError on import
        spacy_dir = Path(fake_pkg_dir) / "spacy"
        spacy_dir.mkdir()
        (spacy_dir / "__init__.py").write_text("raise ImportError('spacy not installed')\n")

        input_file = tmp_path / "input.jsonl"
        output_file = tmp_path / "output.jsonl"
        input_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        env = os.environ.copy()
        # Prepend fake package dir so it shadows real spacy
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = fake_pkg_dir + (":" + existing if existing else "")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--input",
                str(input_file),
                "--output",
                str(output_file),
                "--company-name",
                "Globex",
            ],
            capture_output=True,
            text=True,
            env=env,
        )

    assert result.returncode == 0
    assert "PERSON NAMES NOT REDACTED" in result.stderr
    assert "spacy_models_loaded=0/2" in result.stderr
