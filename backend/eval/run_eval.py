"""Measures retrieval accuracy and answer speed on the sample documents.

Run from the backend folder:
    python -m eval.run_eval              retrieval only (needs Ollama for the meaning search, falls back to keywords)
    python -m eval.run_eval --answers    also asks the local model each question and times it
Writes eval/results.md with the numbers."""

import argparse
import hashlib
import json
import platform
import statistics
import time
from datetime import date
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401  (registers the tables)
from app.config import get_settings
from app.database import Base
from app.models import Chunk, Document
from app.services import indexing, rag, retrieval
from app.services.chunking import chunk_pages
from app.services.embeddings import OllamaEmbedder
from app.services.errors import EmbeddingUnavailable, LLMUnavailable
from app.services.extract import extract_document
from app.services.llm import OllamaChat

HERE = Path(__file__).parent
SAMPLES = HERE.parent.parent / "web" / "public" / "samples"
EVAL_FILES = ["pump-station-procedure-v1.pdf", "emergency-response-plan.pdf"]


def build_database(settings):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    for name in EVAL_FILES:
        data = (SAMPLES / name).read_bytes()
        extracted = extract_document("pdf", data)
        pieces = chunk_pages(extracted.pages, settings.chunk_size, settings.chunk_overlap)
        db.add(
            Document(
                filename=name, file_type="pdf", size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                storage_key=name, page_count=extracted.page_count, char_count=sum(len(p.text) for p in pieces),
                chunk_count=len(pieces),
                chunks=[Chunk(chunk_index=p.chunk_index, page_number=p.page_number, text=p.text, char_count=len(p.text)) for p in pieces],
            )
        )
    db.commit()
    return db


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--answers", action="store_true", help="also time the local model's answers")
    args = parser.parse_args()

    settings = get_settings()
    questions = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))
    db = build_database(settings)
    embedder = OllamaEmbedder(
        settings.ollama_base_url, settings.embedding_model, settings.embedding_doc_prefix,
        settings.embedding_query_prefix, settings.ai_timeout_seconds, settings.embed_batch_size,
    )
    try:
        for document_id in indexing.documents_needing_index(db, embedder.model_name):
            indexing.index_document(db, embedder, document_id, settings.embed_batch_size)
        search_mode = "hybrid (keywords + meaning)"
    except EmbeddingUnavailable as exc:
        search_mode = "keywords only (Ollama not reachable: " + str(exc)[:60] + ")"
    print("Search mode:", search_mode)

    in_scope = [q for q in questions if q["file"]]
    ranks, rows = [], []
    for q in in_scope:
        hits, _ = retrieval.search(db, embedder, q["question"], 5)
        rank = next((i for i, h in enumerate(hits, 1) if h.filename == q["file"] and h.page_number == q["page"]), None)
        ranks.append(rank)
        rows.append((q["question"], f'{q["file"]} p.{q["page"]}', rank or "not in top 5"))
    total = len(in_scope)
    at = lambda k: sum(1 for r in ranks if r and r <= k)  # noqa: E731
    lines = [
        f"# Evaluation results ({date.today().isoformat()})", "",
        f"- Machine: {platform.platform()}, {platform.processor() or 'unknown CPU'}",
        f"- Documents: {', '.join(EVAL_FILES)} (sample files in web/public/samples)",
        f"- Search mode: {search_mode}",
        f"- Questions: {total} in scope, {len(questions) - total} out of scope", "",
        "## Retrieval: is the right file and page among the top results?", "",
        f"- Passages in the test corpus: {db.query(Chunk).count()} (small, so top 5 would always be true)",
        f"- Top 1: {at(1)} of {total}", f"- Top 3: {at(3)} of {total}", "",
        "| Question | Expected | Rank found |", "|---|---|---|",
    ] + [f"| {a} | {b} | {c} |" for a, b, c in rows]
    print(f"Retrieval: top1 {at(1)}/{total}, top3 {at(3)}/{total}")

    if args.answers:
        chat = OllamaChat(settings.ollama_base_url, settings.chat_model, settings.ai_timeout_seconds, settings.chat_context_tokens)
        try:
            chat.generate_with_usage("Reply with OK.", "OK")  # load the model first so it is not counted
            correct, cited, refused, times, detail = 0, 0, 0, [], []
            for q in questions:
                hits, _ = retrieval.search(db, embedder, q["question"], 5)
                started = time.perf_counter()
                answer, _usage = chat.generate_with_usage(rag.SYSTEM_PROMPT, rag.build_user_prompt(q["question"], hits))
                seconds = time.perf_counter() - started
                times.append(seconds)
                if q["file"]:
                    ok = any(k in answer.lower() for k in q["keywords"])
                    correct += ok
                    cited += bool(rag.extract_citations(answer, len(hits))[0])
                else:
                    ok = rag.NOT_FOUND_TEXT.lower() in answer.lower()
                    refused += ok
                detail.append((q["question"], "yes" if ok else "no", f"{seconds:.1f}"))
                print(f"{'ok ' if ok else 'BAD'} {seconds:5.1f}s  {q['question']}")
        except LLMUnavailable as exc:
            raise SystemExit(f"Cannot run answers: {exc}")
        out_scope = len(questions) - total
        lines += [
            "", f"## Answers from {settings.chat_model}", "",
            f"- Correct (expected fact appears): {correct} of {total}",
            f"- With at least one citation: {cited} of {total}",
            f"- Refused when the documents had no answer: {refused} of {out_scope}",
            f"- Time per answer: median {statistics.median(times):.1f} s, slowest {max(times):.1f} s",
            "", "| Question | Correct | Seconds |", "|---|---|---|",
        ] + [f"| {a} | {b} | {c} |" for a, b, c in detail]
        print(f"Answers: correct {correct}/{total}, cited {cited}/{total}, refused {refused}/{out_scope}, median {statistics.median(times):.1f}s")

    (HERE / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Wrote", HERE / "results.md")


if __name__ == "__main__":
    main()
