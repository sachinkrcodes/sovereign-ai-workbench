DOCS = "/api/v1/documents"


def upload(client, name="pump.txt", data=b"Pump P-101 must be isolated before maintenance."):
    assert client.post(DOCS, files={"file": (name, data, "text/plain")}).status_code == 201


def ask(client, query="pump isolation"):
    return client.post("/api/v1/ask", json={"query": query})


def test_each_answer_is_counted_in_tokens(client, chat):
    upload(client)
    chat.reply = "Isolate it first [1]."
    assert ask(client).status_code == 200
    me = client.get("/api/v1/usage/me").json()
    assert me["today_tokens"] == 120 and me["total_requests"] == 1 and me["total_tokens"] == 120
    assert me["daily_limit"] is None and me["remaining_today"] is None  # admins are unlimited


def test_a_viewer_is_stopped_when_the_daily_limit_is_reached(client, make_client, test_settings):
    upload(client)
    test_settings.daily_token_limit = 100
    viewer = make_client("viewer")
    assert ask(viewer).status_code == 200  # uses 120 tokens, now over the limit
    blocked = ask(viewer)
    assert blocked.status_code == 429 and "limit" in blocked.json()["detail"]
    assert viewer.get("/api/v1/usage/me").json()["remaining_today"] == 0

    assert ask(client).status_code == 200  # admins are not limited
    events = client.get("/api/v1/audit", params={"action": "usage.limit_reached"}).json()
    assert events["total"] == 1 and events["items"][0]["status"] == "denied"


def test_agent_runs_add_up_every_model_call(client, chat):
    chat.tool_turns = [
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "list_documents", "arguments": {}}}]},
        {"role": "assistant", "content": "No documents yet."},
    ]
    assert client.post("/api/v1/agents/researcher/run", json={"task": "what documents exist?"}).status_code == 200
    summary = client.get("/api/v1/usage/summary").json()
    assert summary["by_kind"] == [{"kind": "agent_run", "requests": 1, "total_tokens": 120}]


def test_admin_summary_shows_cost_story_per_user_and_day(client, make_client, chat):
    upload(client)
    viewer = make_client("viewer")
    ask(viewer)
    ask(client)
    summary = client.get("/api/v1/usage/summary", params={"days": 7}).json()
    assert summary["requests"] == 2 and summary["total_tokens"] == 240
    assert summary["prompt_tokens"] == 200 and summary["completion_tokens"] == 40
    assert summary["actual_cost_usd"] == 0.0
    assert abs(summary["equivalent_cloud_cost_usd"] - 0.000054) < 1e-9
    assert {u["email"] for u in summary["by_user"]} == {client.user_email, viewer.user_email}
    assert len(summary["by_day"]) == 1 and summary["by_day"][0]["requests"] == 2


def test_nothing_is_counted_when_the_ai_engine_is_down(client, chat):
    upload(client)
    chat.fail = True
    assert ask(client).json()["mode"] == "retrieval_only"
    assert client.get("/api/v1/usage/me").json()["total_requests"] == 0
