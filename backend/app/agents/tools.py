"""The tools an agent may call. Each tool is small, read-only and has a strict input check.

Governance idea: an agent can only use the tools listed in its own definition
(see registry.py). Anything else is denied and logged."""

import ast
import operator
from dataclasses import dataclass, field
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Document
from app.services import retrieval
from app.services.embeddings import Embedder


class ToolError(Exception):
    """A tool was called with bad input or could not do its job. Message is shown to the model."""


@dataclass
class ToolContext:
    db: Session
    embedder: Embedder


@dataclass
class ToolResult:
    text: str
    sources: list[dict] = field(default_factory=list)  # [{"filename": str, "page": int | None}]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict
    handler: Callable[[ToolContext, dict], ToolResult]

    def spec(self) -> dict:
        """The format Ollama expects in the `tools` list."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _as_int(value, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


# ---------------- search_documents ----------------
def _search_documents(ctx: ToolContext, args: dict) -> ToolResult:
    query = str(args.get("query", "")).strip()
    if not query:
        raise ToolError("'query' is required.")
    top_k = _as_int(args.get("top_k"), default=4, low=1, high=8)
    hits, _mode = retrieval.search(ctx.db, ctx.embedder, query, top_k)
    if not hits:
        return ToolResult("No matching passages found.")
    lines, sources = [], []
    for hit in hits:
        page = hit.page_number if hit.page_number is not None else "-"
        lines.append(f"[{hit.filename}, p.{page}] {hit.text[:700]}")
        sources.append({"filename": hit.filename, "page": hit.page_number})
    return ToolResult("\n\n".join(lines), sources)


# ---------------- list_documents ----------------
def _list_documents(ctx: ToolContext, args: dict) -> ToolResult:
    documents = ctx.db.scalars(select(Document).order_by(Document.created_at).limit(50)).all()
    if not documents:
        return ToolResult("No documents have been uploaded yet.")
    lines = [
        f"- {d.filename} (id {d.id}, {d.page_count if d.page_count is not None else '?'} pages, "
        f"{d.chunk_count} passages)"
        for d in documents
    ]
    return ToolResult("\n".join(lines))


# ---------------- get_document_text ----------------
def _get_document_text(ctx: ToolContext, args: dict) -> ToolResult:
    reference = str(args.get("document", "")).strip()
    if not reference:
        raise ToolError("'document' (file name or id) is required.")
    max_chars = _as_int(args.get("max_chars"), default=2500, low=500, high=2500)

    document = ctx.db.get(Document, reference)
    if document is None:
        wanted = reference.lower()
        for candidate in ctx.db.scalars(select(Document)).all():
            if candidate.filename.lower() == wanted:
                document = candidate
                break
    if document is None:
        raise ToolError(f"Document '{reference}' not found. Call list_documents to see file names.")

    chunks = ctx.db.scalars(
        select(Chunk).where(Chunk.document_id == document.id).order_by(Chunk.chunk_index)
    ).all()
    parts, sources, used = [], [], 0
    for chunk in chunks:
        page = chunk.page_number if chunk.page_number is not None else "-"
        piece = f"[{document.filename}, p.{page}] {chunk.text}"
        if used + len(piece) > max_chars:
            parts.append("... (truncated)")
            break
        parts.append(piece)
        used += len(piece)
        source = {"filename": document.filename, "page": chunk.page_number}
        if source not in sources:
            sources.append(source)
    return ToolResult("\n\n".join(parts) or "This document has no text.", sources)


# ---------------- calculator ----------------
_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def safe_eval(expression: str) -> float | int:
    """Evaluate plain arithmetic only. No names, no function calls, nothing else."""
    if len(expression) > 100:
        raise ToolError("Expression is too long.")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ToolError("Invalid arithmetic expression.") from exc

    def evaluate(node):
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ToolError("Exponent is too large.")
            return _BINARY[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](evaluate(node.operand))
        raise ToolError("Only basic arithmetic (+ - * / // % **) is allowed.")

    try:
        return evaluate(tree)
    except ZeroDivisionError as exc:
        raise ToolError("Division by zero.") from exc
    except (OverflowError, ValueError) as exc:
        raise ToolError("Result is out of range.") from exc


def _calculator(ctx: ToolContext, args: dict) -> ToolResult:
    expression = str(args.get("expression", "")).strip()
    if not expression:
        raise ToolError("'expression' is required.")
    result = safe_eval(expression)
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return ToolResult(f"{expression} = {result}")


TOOLS: dict[str, Tool] = {
    tool.name: tool
    for tool in [
        Tool(
            name="search_documents",
            description="Search all uploaded documents and return the most relevant passages "
            "with file name and page number.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for"},
                    "top_k": {"type": "integer", "description": "How many passages (1-8)"},
                },
                "required": ["query"],
            },
            handler=_search_documents,
        ),
        Tool(
            name="list_documents",
            description="List the uploaded documents (file name, id, pages).",
            parameters={"type": "object", "properties": {}},
            handler=_list_documents,
        ),
        Tool(
            name="get_document_text",
            description="Read the text of one document, in order. Use a file name from list_documents.",
            parameters={
                "type": "object",
                "properties": {
                    "document": {"type": "string", "description": "File name or document id"},
                    "max_chars": {"type": "integer", "description": "Max characters (500-2500)"},
                },
                "required": ["document"],
            },
            handler=_get_document_text,
        ),
        Tool(
            name="calculator",
            description="Calculate an arithmetic expression such as (40 * 0.25) + 3.",
            parameters={
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
            handler=_calculator,
        ),
    ]
}
