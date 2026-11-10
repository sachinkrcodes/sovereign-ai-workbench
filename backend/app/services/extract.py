"""Turn an uploaded file into clean text, page by page.

Supported: PDF, DOCX, TXT, MD. Every failure becomes an ExtractionError with a message
that is safe to show to the user."""

import io
import re
from dataclasses import dataclass

MAX_PDF_PAGES = 1000


class ExtractionError(Exception):
    """The file is readable as an upload but we could not get usable text from it."""


@dataclass(frozen=True)
class PageText:
    page_number: int | None  # None for formats without pages (docx, txt, md)
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    pages: list[PageText]
    page_count: int | None


def clean_text(text: str) -> str:
    text = text.replace("\x00", "")  # Postgres cannot store NUL characters
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sniff_matches(ext: str, data: bytes) -> bool:
    """Check the file's real content matches its extension (blocks renamed files)."""
    if ext == "pdf":
        return b"%PDF-" in data[:1024]
    if ext == "docx":
        return data[:4] == b"PK\x03\x04"
    if ext in ("txt", "md"):
        return b"\x00" not in data[:8192]
    return False


def extract_document(ext: str, data: bytes) -> ExtractedDocument:
    if ext == "pdf":
        return _extract_pdf(data)
    if ext == "docx":
        return _extract_docx(data)
    if ext in ("txt", "md"):
        return _extract_plain(data)
    raise ExtractionError(f"Unsupported file type: {ext}")


def _extract_pdf(data: bytes) -> ExtractedDocument:
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ExtractionError("This PDF is password protected.")
        total = len(reader.pages)
        if total > MAX_PDF_PAGES:
            raise ExtractionError(f"PDF has {total} pages; the limit is {MAX_PDF_PAGES}.")
        pages: list[PageText] = []
        for number, page in enumerate(reader.pages, start=1):
            text = clean_text(page.extract_text() or "")
            if text:
                pages.append(PageText(number, text))
    except ExtractionError:
        raise
    except Exception as exc:  # corrupt file, unsupported encryption, parser bug...
        raise ExtractionError("Could not read this PDF. It may be corrupted or encrypted.") from exc

    if not pages:
        raise ExtractionError(
            "No selectable text found in this PDF (it may be a scan). OCR is not supported yet."
        )
    return ExtractedDocument(pages=pages, page_count=total)


def _extract_docx(data: bytes) -> ExtractedDocument:
    from docx import Document as DocxDocument
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        doc = DocxDocument(io.BytesIO(data))
        parts: list[str] = []
        # Walk the body in order so tables stay in the right place between paragraphs.
        for child in doc.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                text = Paragraph(child, doc).text.strip()
                if text:
                    parts.append(text)
            elif tag == "tbl":
                for row in Table(child, doc).rows:
                    cells: list[str] = []
                    for cell in row.cells:
                        value = cell.text.strip()
                        if value and (not cells or cells[-1] != value):  # skip merged-cell repeats
                            cells.append(value)
                    if cells:
                        parts.append(" | ".join(cells))
    except Exception as exc:
        raise ExtractionError("Could not read this DOCX file. It may be corrupted.") from exc

    text = clean_text("\n\n".join(parts))
    if not text:
        raise ExtractionError("This DOCX file contains no text.")
    return ExtractedDocument(pages=[PageText(None, text)], page_count=None)


def _extract_plain(data: bytes) -> ExtractedDocument:
    text = clean_text(data.decode("utf-8-sig", errors="replace"))
    if not text:
        raise ExtractionError("This file contains no text.")
    return ExtractedDocument(pages=[PageText(None, text)], page_count=None)
