import pytest

from app.services.chunking import chunk_pages, split_text
from app.services.extract import PageText


def test_short_text_is_one_chunk():
    assert split_text("Hello world.", 900, 150) == ["Hello world."]


def test_paragraphs_are_packed_together():
    text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
    assert split_text(text, 900, 150) == [text]


def test_paragraphs_split_when_size_exceeded():
    paragraph = "word " * 60  # ~300 chars
    text = "\n\n".join([paragraph.strip()] * 4)
    chunks = split_text(text, 700, 100)
    assert len(chunks) == 2
    assert all(len(c) <= 700 for c in chunks)


def test_long_paragraph_is_cut_with_overlap_and_never_exceeds_size():
    text = " ".join(f"w{i}" for i in range(1000))
    chunks = split_text(text, 300, 60)
    assert len(chunks) > 3
    assert all(len(c) <= 300 for c in chunks)
    # overlap: the start of each chunk repeats words from the end of the previous one
    first_words_of_second = chunks[1].split()[:3]
    assert all(word in chunks[0] for word in first_words_of_second)


def test_no_text_is_lost():
    text = " ".join(f"w{i}" for i in range(500))
    chunks = split_text(text, 250, 50)
    joined = " ".join(chunks)
    for i in range(500):
        assert f"w{i}" in joined


def test_chunks_keep_page_numbers_and_global_index():
    pages = [PageText(1, "Alpha page text."), PageText(2, "Beta page text.")]
    chunks = chunk_pages(pages, 900, 150)
    assert [(c.chunk_index, c.page_number) for c in chunks] == [(0, 1), (1, 2)]


def test_invalid_settings_rejected():
    with pytest.raises(ValueError):
        split_text("abc", 100, 100)
