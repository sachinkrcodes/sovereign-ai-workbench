import pytest

from app.services.extract import ExtractionError, clean_text, extract_document, sniff_matches
from tests.helpers import make_docx, make_pdf


def test_pdf_pages_and_page_numbers():
    doc = extract_document("pdf", make_pdf(["Refinery safety manual", "Pump shutdown procedure"]))
    assert doc.page_count == 2
    assert [p.page_number for p in doc.pages] == [1, 2]
    assert "Refinery safety manual" in doc.pages[0].text
    assert "Pump shutdown procedure" in doc.pages[1].text


def test_pdf_without_text_is_rejected_with_clear_message():
    with pytest.raises(ExtractionError, match="OCR"):
        extract_document("pdf", make_pdf([""]))


def test_corrupt_pdf_is_rejected():
    with pytest.raises(ExtractionError):
        extract_document("pdf", b"%PDF-1.4 this is not really a pdf")


def test_docx_paragraphs_and_tables_in_order():
    data = make_docx(["Intro paragraph", "Closing paragraph"], [["Valve", "Status"], ["V-101", "Open"]])
    doc = extract_document("docx", data)
    text = doc.pages[0].text
    assert doc.page_count is None
    assert "Intro paragraph" in text and "Closing paragraph" in text
    assert "Valve | Status" in text and "V-101 | Open" in text


def test_corrupt_docx_is_rejected():
    with pytest.raises(ExtractionError):
        extract_document("docx", b"PK\x03\x04 broken")


def test_plain_text_handles_bom_and_bad_bytes():
    doc = extract_document("txt", b"\xef\xbb\xbfHello \xff world")
    assert doc.pages[0].text.startswith("Hello")


def test_empty_text_file_is_rejected():
    with pytest.raises(ExtractionError):
        extract_document("txt", b"   \n\n  ")


def test_clean_text_removes_nul_and_collapses_blank_lines():
    assert clean_text("a\x00b\r\n\n\n\n\nc  \n") == "ab\n\nc"


def test_sniffing_blocks_renamed_files():
    assert sniff_matches("pdf", make_pdf(["x"]))
    assert not sniff_matches("pdf", b"just some text")
    assert not sniff_matches("docx", b"%PDF-1.4")
    assert not sniff_matches("txt", b"binary\x00data")
