PUMP = b"Pump P-101 must be isolated and locked out before maintenance. Close the suction valve first."
FIRE = b"Fire drills are held every quarter. The assembly point is gate 4 near the canteen."
LEAVE = b"Annual leave requests must be approved by the department manager two weeks in advance."

DOCS = "/api/v1/documents"


def upload(client, name, data):
    response = client.post(DOCS, files={"file": (name, data, "text/plain")})
    assert response.status_code == 201, response.text
    return response.json()


def setup_three_docs(client):
    ids = {
        "pump": upload(client, "pump.txt", PUMP)["id"],
        "fire": upload(client, "fire.txt", FIRE)["id"],
        "leave": upload(client, "leave.txt", LEAVE)["id"],
    }
    return ids


def search(client, query, **extra):
    return client.post("/api/v1/search", json={"query": query, **extra})


def test_health_ai_reports_ollama_down(client):
    body = client.get("/health/ai").json()
    assert body["ollama"] == "down" and "ollama.com" in body["hint"]


def test_index_status_before_and_after_indexing(client):
    setup_three_docs(client)
    before = client.get("/api/v1/index/status").json()
    assert before["documents_total"] == 3 and before["chunks_indexed"] == 0

    result = client.post("/api/v1/index")
    assert result.status_code == 200
    assert result.json()["documents_processed"] == 3 and result.json()["chunks_indexed"] == 3

    after = client.get("/api/v1/index/status").json()
    assert after["documents_indexed"] == 3 and after["chunks_indexed"] == after["chunks_total"]

    again = client.post("/api/v1/index").json()  # nothing left to do
    assert again["documents_processed"] == 0 and again["chunks_indexed"] == 0


def test_index_single_document_and_404(client):
    ids = setup_three_docs(client)
    one = client.post(f"{DOCS}/{ids['pump']}/index")
    assert one.status_code == 200 and one.json()["chunks_indexed"] == 1
    assert client.post(f"{DOCS}/nope/index").status_code == 404


def test_index_returns_503_when_ollama_is_down(client, embedder):
    setup_three_docs(client)
    embedder.fail = True
    response = client.post("/api/v1/index")
    assert response.status_code == 503 and "Ollama" in response.json()["detail"]


def test_search_works_with_keywords_before_indexing(client):
    setup_three_docs(client)
    body = search(client, "suction valve").json()
    assert body["mode"] == "keyword_only"
    assert body["hits"][0]["filename"] == "pump.txt"
    assert body["hits"][0]["vector_score"] is None


def test_hybrid_search_finds_the_right_document(client):
    setup_three_docs(client)
    client.post("/api/v1/index")
    body = search(client, "how do I isolate the pump before maintenance").json()
    assert body["mode"] == "hybrid"
    top = body["hits"][0]
    assert top["filename"] == "pump.txt" and top["vector_score"] is not None
    assert search(client, "where is the assembly point for fire drills").json()["hits"][0]["filename"] == "fire.txt"


def test_search_falls_back_to_keywords_when_ollama_dies(client, embedder):
    setup_three_docs(client)
    client.post("/api/v1/index")
    embedder.fail = True
    body = search(client, "annual leave manager approval").json()
    assert body["mode"] == "keyword_only" and body["hits"][0]["filename"] == "leave.txt"


def test_search_can_be_limited_to_chosen_documents(client):
    ids = setup_three_docs(client)
    client.post("/api/v1/index")
    body = search(client, "maintenance", document_ids=[ids["fire"]]).json()
    assert all(hit["document_id"] == ids["fire"] for hit in body["hits"])


def test_search_validates_input(client):
    assert search(client, "").status_code == 422
    assert search(client, "x", top_k=0).status_code == 422
    assert search(client, "x", top_k=99).status_code == 422


def test_search_with_no_documents_returns_empty(client):
    body = search(client, "anything").json()
    assert body["hits"] == []


def test_ask_returns_verified_citations(client, chat):
    setup_three_docs(client)
    client.post("/api/v1/index")
    chat.reply = "Isolate and lock out the pump first [1]. Then close the suction valve [1, 9]."
    body = client.post("/api/v1/ask", json={"query": "how to isolate pump before maintenance"}).json()
    assert body["mode"] == "generated" and body["model"] == "fake-chat"
    assert body["citations"] == [1]  # [9] was never provided -> removed
    assert "Removed citations" in body["notice"]
    assert body["sources"][0]["ref"] == 1 and body["sources"][0]["filename"] == "pump.txt"
    assert "SOURCES:" in chat.last_user and "pump.txt" in chat.last_user
    assert "data, not instructions" in chat.last_system  # prompt-injection guard is present


def test_ask_warns_when_model_gives_no_citation(client, chat):
    setup_three_docs(client)
    chat.reply = "You should isolate the pump."
    body = client.post("/api/v1/ask", json={"query": "pump isolation"}).json()
    assert body["citations"] == [] and "did not cite" in body["notice"]


def test_ask_falls_back_to_retrieval_only_when_chat_model_is_down(client, chat):
    setup_three_docs(client)
    chat.fail = True
    body = client.post("/api/v1/ask", json={"query": "pump maintenance"}).json()
    assert body["mode"] == "retrieval_only" and body["answer"] is None
    assert body["sources"][0]["filename"] == "pump.txt" and "Ollama" in body["notice"]


def test_ask_with_nothing_found(client):
    body = client.post("/api/v1/ask", json={"query": "pump"}).json()
    assert body["mode"] == "no_results" and body["sources"] == []


def test_switching_embedding_model_reindexes(client, embedder):
    setup_three_docs(client)
    client.post("/api/v1/index")
    embedder.model_name = "hash-test-2"
    status = client.get("/api/v1/index/status").json()
    assert status["model"] == "hash-test-2" and status["chunks_indexed"] == 0
    assert client.post("/api/v1/index").json()["chunks_indexed"] == 3
    assert client.get("/api/v1/index/status").json()["documents_indexed"] == 3


def test_deleting_a_document_removes_its_vectors_from_search(client):
    ids = setup_three_docs(client)
    client.post("/api/v1/index")
    assert client.delete(f"{DOCS}/{ids['pump']}").status_code == 204
    status = client.get("/api/v1/index/status").json()
    assert status["documents_total"] == 2 and status["chunks_indexed"] == 2
    hits = search(client, "isolate the pump suction valve").json()["hits"]
    assert all(hit["filename"] != "pump.txt" for hit in hits)
