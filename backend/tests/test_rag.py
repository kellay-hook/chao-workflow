from __future__ import annotations

from app.services.rag import chunk_text, parse_document


def test_chunk_text_short_input():
    chunks = chunk_text("hello world", 100, 10)
    assert chunks == ["hello world"]


def test_chunk_text_splits_long_input():
    text = " ".join(["word"] * 5000)
    chunks = chunk_text(text, 100, 20)
    assert len(chunks) > 1
    assert all(chunk.strip() for chunk in chunks)


def test_parse_csv_to_markdown_table():
    data = b"name,score\nAda,10\nBob,20\n"
    sections = parse_document("scores.csv", data)
    assert sections
    assert "| name | score |" in sections[0].text
    assert sections[0].metadata["row_start"] == 2


def test_parse_markdown():
    sections = parse_document("notes.md", b"# Title\n\nBody")
    assert sections[0].text.startswith("# Title")
