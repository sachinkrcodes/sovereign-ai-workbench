# Sovereign AI Workbench

Document question answering that runs on your own computer, for teams that cannot send confidential files to an online AI service.

- **Status:** in progress
- **Live:** Not live. Runs on my laptop. A Terraform file for one AWS server is written and checked in CI but never applied.
- **Built:** November 2026
- **Keywords:** Python, FastAPI, React, Ollama, Llama 3.2, RAG, hybrid search, SQLAlchemy, SQLite, pytest, Docker, GitHub Actions, Terraform

## Highlights

- Built a service where you upload PDF, Word or text files, ask a question, and get an answer with the file name and page numbers.
- Ran the language model (Llama 3.2 3B) and the embedding model (nomic-embed-text) on the laptop through Ollama, so no document text goes to an outside service.
- Combined BM25 keyword ranking with vector similarity using reciprocal rank fusion. Keyword search still works when Ollama is off.
- Added four agents: Researcher (several searches for one question), Summarizer (one-page brief), Comparer (sentence diff of two documents), Checklist (lists the must and should sentences).
- Added three roles (viewer, analyst, admin) and an audit log where each row holds the hash of the previous row. A verify endpoint reports the first edited or deleted row.
- Tested with [FILL: N pytest tests, all passing. Run `pytest -q` in backend and copy the real count]. GitHub Actions runs them on every push.
- Measured [FILL: copy the result lines from backend/eval/results.md, for example how many of the 20 sample questions found the right page and the median seconds per answer]

## Screenshots

![Answer with citations](docs/screenshots/01-ask-with-citations.png)

Answer to "Which valve is closed first before maintenance?" with the file and page it came from.

![Checklist result](docs/screenshots/02-checklist.png)

Checklist agent listing the must and should sentences of the sample procedure, with page numbers.

![Comparer result](docs/screenshots/03-compare.png)

Comparer agent showing what changed between version 1 and version 2 of the sample procedure.

![Admin page](docs/screenshots/04-admin.png)

Admin page with usage numbers and the audit log check.

## Tech

- Python 3.12 and FastAPI: the backend API.
- SQLite and SQLAlchemy: users, documents, passages, vectors and the audit log. Postgres also works.
- Ollama with Llama 3.2 3B and nomic-embed-text: runs both models locally.
- NumPy: compares vectors in memory.
- React 18 and Vite: the web app.
- pytest and GitHub Actions: tests, web build and Docker image builds on every push.

## Run it

- Needs: Python 3.12, Node 20, Ollama
- Tested on: Windows 11

```bash
ollama pull nomic-embed-text
ollama pull llama3.2:3b
git clone https://github.com/sachinkrcodes/sovereign-ai-workbench.git
cd sovereign-ai-workbench/backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload
```

In a second terminal:

```bash
cd sovereign-ai-workbench/web
npm install
npm run dev
```

Open `http://localhost:5173`, create the admin account, then click Load sample documents on the Documents page. The sample files are fictional and live in `web/public/samples`.

To score the system on 20 sample questions, run `python -m eval.run_eval --answers` in `backend`. It writes `backend/eval/results.md`.

## Hardest problem

- Problem: the Researcher agent answered "I could not find this in the uploaded documents" even though its own search had returned the right passage.
- Tried: a stricter prompt about when to say "not found". The 3B model refused more often.
- Fixed by: a check in code. If the answer is "not found" but passages were retrieved, one more call answers from those passages, and the run records it as a step.
- Learned: a small model does not reliably follow a stricter prompt, so the check has to be in code.

## Limits and next

- Not done: scanned PDFs are rejected because there is no OCR.
- Not done: not deployed. The Terraform file has not been applied.
- Not done: the accuracy script uses 20 questions on 5 passages. It shows the pipeline works but says little about large document sets.
- Not done: no load test. Vector search runs in memory, which suits thousands of passages.
- Next: test on a larger real document set, then move vector search to pgvector.

## Author

Sachin Kumar | [GitHub](https://github.com/sachinkrcodes) | [LinkedIn](https://www.linkedin.com/in/sachinkrcodes) | sachinkrcodes@gmail.com

MIT License. See [LICENSE](LICENSE).
