DOCS = "/api/v1/documents"
AGENTS = "/api/v1/agents"

PUMP = b"Pump P-101 must be isolated and locked out before maintenance. Close the suction valve first."
FIRE = b"Fire drills are held every quarter. The assembly point is gate 4 near the canteen."


def upload(client, name, data):
    response = client.post(DOCS, files={"file": (name, data, "text/plain")})
    assert response.status_code == 201, response.text
    return response.json()


def tool_call(name, **arguments):
    return {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": name, "arguments": arguments}}]}


def final(text):
    return {"role": "assistant", "content": text}


def run(client, agent, task="Tell me about the pump procedure"):
    return client.post(f"{AGENTS}/{agent}/run", json={"task": task})


def test_list_agents_shows_permissions(client):
    agents = {a["name"]: a for a in client.get(AGENTS).json()}
    assert set(agents) == {"librarian", "researcher", "analyst"}
    assert agents["librarian"]["allowed_tools"] == ["list_documents"]
    assert "calculator" in agents["analyst"]["allowed_tools"]


def test_unknown_agent_and_bad_task(client):
    assert run(client, "ghost").status_code == 404
    assert client.post(f"{AGENTS}/researcher/run", json={"task": "hi"}).status_code == 422


def test_researcher_searches_then_answers_with_sources(client, chat):
    upload(client, "pump.txt", PUMP)
    upload(client, "fire.txt", FIRE)
    chat.tool_turns = [
        tool_call("search_documents", query="isolate pump maintenance"),
        final("Isolate and lock out the pump first [pump.txt, p.-]."),
    ]
    body = run(client, "researcher").json()
    assert body["status"] == "completed" and body["model"] == "fake-chat"
    assert body["steps"][0]["tool"] == "search_documents" and body["steps"][0]["status"] == "ok"
    assert "pump.txt" in body["steps"][0]["output_preview"]
    assert body["sources"][0] == {"filename": "pump.txt", "page": None}
    assert "lock out" in body["answer"]


def test_librarian_is_denied_a_tool_outside_its_permissions(client, chat):
    upload(client, "pump.txt", PUMP)
    chat.tool_turns = [tool_call("search_documents", query="pump"), final("I cannot search.")]
    body = run(client, "librarian", "What do the documents say about pumps?").json()
    assert body["steps"][0]["status"] == "denied"
    assert body["sources"] == []


def test_analyst_reads_a_document_by_name_and_calculates(client, chat):
    upload(client, "pump.txt", PUMP)
    chat.tool_turns = [
        tool_call("get_document_text", document="PUMP.TXT"),
        tool_call("calculator", expression="12 * 3"),
        final("Done [pump.txt, p.-]. Total is 36."),
    ]
    body = run(client, "analyst", "Read the pump file and multiply 12 by 3").json()
    assert [s["status"] for s in body["steps"]] == ["ok", "ok"]
    assert "12 * 3 = 36" in body["steps"][1]["output_preview"]
    assert body["sources"] == [{"filename": "pump.txt", "page": None}]


def test_tool_error_for_missing_document_is_handled(client, chat):
    chat.tool_turns = [tool_call("get_document_text", document="missing.pdf"), final("Not found.")]
    body = run(client, "analyst", "Read missing.pdf please").json()
    assert body["steps"][0]["status"] == "error" and "not found" in body["steps"][0]["output_preview"]


def test_step_limit_returns_a_best_effort_answer(client, chat):
    chat.tool_turns = [tool_call("list_documents")] * 4 + [final("Partial answer")]
    body = run(client, "researcher").json()
    assert body["status"] == "step_limit" and len(body["steps"]) == 4
    assert body["answer"] == "Partial answer"


def test_failed_run_returns_503_but_is_still_recorded(client, chat):
    chat.fail = True
    response = run(client, "researcher")
    assert response.status_code == 503 and "Ollama" in response.json()["detail"]
    runs = client.get(f"{AGENTS}/runs").json()
    assert runs["total"] == 1 and runs["items"][0]["status"] == "failed"
    assert runs["items"][0]["error"]


def test_run_history_is_an_audit_trail(client, chat):
    chat.tool_turns = [final("one")]
    first = run(client, "researcher", "First question here").json()
    chat.tool_turns = [final("two")]
    run(client, "librarian", "Second question here")

    everything = client.get(f"{AGENTS}/runs").json()
    assert everything["total"] == 2 and everything["items"][0]["agent"] == "librarian"  # newest first
    only_researcher = client.get(f"{AGENTS}/runs", params={"agent": "researcher"}).json()
    assert only_researcher["total"] == 1

    detail = client.get(f"{AGENTS}/runs/{first['id']}").json()
    assert detail["task"] == "First question here" and detail["answer"] == "one"
    assert client.get(f"{AGENTS}/runs/doesnotexist").status_code == 404
