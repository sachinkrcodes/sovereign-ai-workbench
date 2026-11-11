from tests.conftest import PASSWORD

DOCS = "/api/v1/documents"
USERS = "/api/v1/users"
TEXT = ("a.txt", b"Pump P-101 must be isolated before maintenance.", "text/plain")


def upload(client, name="a.txt", data=TEXT[1]):
    response = client.post(DOCS, files={"file": (name, data, "text/plain")})
    assert response.status_code == 201, response.text
    return response.json()


def test_viewer_can_read_and_ask_but_not_change_anything(client, make_client):
    document = upload(client)
    viewer = make_client("viewer")
    assert viewer.get(DOCS).status_code == 200
    assert viewer.get(f"{DOCS}/{document['id']}").status_code == 200
    assert viewer.post("/api/v1/search", json={"query": "pump"}).status_code == 200
    assert viewer.post("/api/v1/ask", json={"query": "pump"}).status_code == 200
    assert viewer.get("/api/v1/agents").status_code == 200

    assert viewer.post(DOCS, files={"file": TEXT}).status_code == 403
    assert viewer.delete(f"{DOCS}/{document['id']}").status_code == 403
    assert viewer.post("/api/v1/index").status_code == 403
    assert viewer.post("/api/v1/agents/researcher/run", json={"task": "tell me about pumps"}).status_code == 403


def test_analyst_can_manage_documents_and_run_agents(make_client, chat):
    analyst = make_client("analyst")
    document = upload(analyst)
    assert document["uploaded_by"] == analyst.user_id
    assert analyst.post("/api/v1/index").status_code == 200
    chat.tool_turns = [{"role": "assistant", "content": "ok"}]
    assert analyst.post("/api/v1/agents/researcher/run", json={"task": "tell me about pumps"}).status_code == 200
    assert analyst.delete(f"{DOCS}/{document['id']}").status_code == 204


def test_admin_only_areas_are_closed_to_everyone_else(make_client):
    for role in ("viewer", "analyst"):
        user = make_client(role)
        assert user.get(USERS).status_code == 403
        assert user.get("/api/v1/audit").status_code == 403
        assert user.get("/api/v1/audit/verify").status_code == 403
        assert user.get("/api/v1/usage/summary").status_code == 403


def test_refused_attempts_are_written_to_the_audit_log(client, make_client):
    viewer = make_client("viewer")
    assert viewer.post(DOCS, files={"file": TEXT}).status_code == 403
    events = client.get("/api/v1/audit", params={"action": "access.denied"}).json()
    assert events["total"] == 1
    event = events["items"][0]
    assert event["status"] == "denied" and event["user_email"] == viewer.user_email
    assert event["detail"]["needs"] == "analyst" and event["detail"]["path"] == DOCS


def test_admin_can_create_list_and_change_users(client, anon_client):
    body = {"email": "new@example.com", "name": "New", "password": "initialpass1", "role": "analyst"}
    created = client.post(USERS, json=body)
    assert created.status_code == 201 and created.json()["role"] == "analyst"
    assert client.post(USERS, json=body).status_code == 409
    emails = [u["email"] for u in client.get(USERS).json()]
    assert "new@example.com" in emails

    user_id = created.json()["id"]
    assert client.patch(f"{USERS}/{user_id}", json={"role": "viewer"}).json()["role"] == "viewer"
    assert client.patch(f"{USERS}/nope", json={"role": "viewer"}).status_code == 404
    assert client.patch(f"{USERS}/{user_id}", json={"role": "boss"}).status_code == 422


def test_changing_a_password_ends_existing_sessions(client, anon_client):
    body = {"email": "p@example.com", "name": "P", "password": "initialpass1", "role": "viewer"}
    user_id = client.post(USERS, json=body).json()["id"]
    token = anon_client.post("/api/v1/auth/login", data={"username": "p@example.com", "password": "initialpass1"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert anon_client.get("/api/v1/auth/me", headers=headers).status_code == 200

    client.patch(f"{USERS}/{user_id}", json={"password": "brandnewpass2"})
    assert anon_client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert anon_client.post("/api/v1/auth/login", data={"username": "p@example.com", "password": "initialpass1"}).status_code == 401
    assert anon_client.post("/api/v1/auth/login", data={"username": "p@example.com", "password": "brandnewpass2"}).status_code == 200


def test_deactivating_a_user_ends_their_session(client, make_client):
    viewer = make_client("viewer")
    assert viewer.get("/api/v1/auth/me").status_code == 200
    client.patch(f"{USERS}/{viewer.user_id}", json={"is_active": False})
    assert viewer.get("/api/v1/auth/me").status_code == 401


def test_the_last_active_admin_cannot_be_removed(client):
    assert client.patch(f"{USERS}/{client.user_id}", json={"role": "viewer"}).status_code == 409
    assert client.patch(f"{USERS}/{client.user_id}", json={"is_active": False}).status_code == 409
    client.post(USERS, json={"email": "second@example.com", "name": "S", "password": "initialpass1", "role": "admin"})
    assert client.patch(f"{USERS}/{client.user_id}", json={"role": "viewer"}).status_code == 200


def test_agent_runs_are_private_to_their_owner_and_visible_to_admins(client, make_client, chat):
    owner, other = make_client("analyst"), make_client("analyst")
    chat.tool_turns = [{"role": "assistant", "content": "done"}]
    run_id = owner.post("/api/v1/agents/researcher/run", json={"task": "tell me about pumps"}).json()["id"]

    assert owner.get("/api/v1/agents/runs").json()["total"] == 1
    assert other.get("/api/v1/agents/runs").json()["total"] == 0
    assert other.get(f"/api/v1/agents/runs/{run_id}").status_code == 404
    assert owner.get(f"/api/v1/agents/runs/{run_id}").status_code == 200
    assert client.get("/api/v1/agents/runs").json()["total"] == 1
    assert client.get(f"/api/v1/agents/runs/{run_id}").status_code == 200
