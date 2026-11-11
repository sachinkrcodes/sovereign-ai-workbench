from sqlalchemy import delete, update

from app.models import AuditEvent
from tests.conftest import PASSWORD

AUDIT = "/api/v1/audit"


def upload(client, name="a.txt", data=b"Some text for the audit test."):
    response = client.post("/api/v1/documents", files={"file": (name, data, "text/plain")})
    assert response.status_code == 201
    return response.json()


def test_actions_are_recorded_with_who_and_what(client):
    document = upload(client, "report.txt")
    client.delete(f"/api/v1/documents/{document['id']}")
    events = client.get(AUDIT).json()["items"]
    actions = [e["action"] for e in events]
    assert "document.upload" in actions and "document.delete" in actions
    uploaded = next(e for e in events if e["action"] == "document.upload")
    assert uploaded["user_email"] == client.user_email
    assert uploaded["resource_id"] == document["id"] and uploaded["detail"]["filename"] == "report.txt"
    assert uploaded["request_id"] and uploaded["ip"]


def test_logins_and_failures_are_recorded(anon_client, client):
    anon_client.post("/api/v1/auth/login", data={"username": client.user_email, "password": PASSWORD})
    anon_client.post("/api/v1/auth/login", data={"username": client.user_email, "password": "bad-password"})
    failed = client.get(AUDIT, params={"action": "auth.login", "status": "failed"}).json()
    ok = client.get(AUDIT, params={"action": "auth.login", "status": "success"}).json()
    assert failed["total"] == 1 and ok["total"] == 1
    assert "password" not in str(failed)  # passwords never reach the log


def test_search_questions_and_agent_runs_are_logged_with_clipped_text(client, chat):
    client.post("/api/v1/ask", json={"query": "q" * 500})
    chat.tool_turns = [{"role": "assistant", "content": "done"}]
    client.post("/api/v1/agents/researcher/run", json={"task": "tell me about pumps"})
    ask = client.get(AUDIT, params={"action": "qa.ask"}).json()["items"][0]
    assert len(ask["detail"]["query"]) <= 200
    run = client.get(AUDIT, params={"action": "agent.run"}).json()["items"][0]
    assert run["detail"]["agent"] == "researcher" and run["detail"]["denied_tool_calls"] == 0


def test_filtering_and_paging(client):
    for number in range(3):
        upload(client, f"f{number}.txt", f"unique text {number}".encode())
    page = client.get(AUDIT, params={"action": "document.upload", "limit": 2}).json()
    assert page["total"] == 3 and len(page["items"]) == 2
    assert page["items"][0]["id"] > page["items"][1]["id"]  # newest first
    mine = client.get(AUDIT, params={"user_email": client.user_email.upper()}).json()
    assert mine["total"] >= 3


def test_an_untouched_log_verifies(client):
    for number in range(3):
        upload(client, f"f{number}.txt", f"unique text {number}".encode())
    result = client.get(f"{AUDIT}/verify").json()
    assert result["valid"] is True and result["events_checked"] >= 3 and result["head_hash"]


def test_editing_a_row_in_the_database_is_detected(client, session_factory):
    for number in range(3):
        upload(client, f"f{number}.txt", f"unique text {number}".encode())
    with session_factory() as db:
        db.execute(update(AuditEvent).where(AuditEvent.id == 2).values(detail={"filename": "tampered.txt"}))
        db.commit()
    result = client.get(f"{AUDIT}/verify").json()
    assert result["valid"] is False and result["first_invalid_id"] == 2


def test_deleting_a_row_from_the_middle_is_detected(client, session_factory):
    for number in range(3):
        upload(client, f"f{number}.txt", f"unique text {number}".encode())
    with session_factory() as db:
        db.execute(delete(AuditEvent).where(AuditEvent.id == 2))
        db.commit()
    assert client.get(f"{AUDIT}/verify").json()["valid"] is False
