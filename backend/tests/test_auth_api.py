from tests.conftest import PASSWORD

AUTH = "/api/v1/auth"


def login(client, email, password=PASSWORD):
    return client.post(f"{AUTH}/login", data={"username": email, "password": password})


def test_first_time_setup_creates_one_admin_only(anon_client):
    assert anon_client.get(f"{AUTH}/status").json() == {"setup_required": True}
    body = {"email": "Boss@Example.com", "name": "Boss", "password": "longpassword"}
    created = anon_client.post(f"{AUTH}/setup", json=body)
    assert created.status_code == 201
    assert created.json()["role"] == "admin" and created.json()["email"] == "boss@example.com"
    assert "password" not in created.text
    assert anon_client.get(f"{AUTH}/status").json() == {"setup_required": False}
    assert anon_client.post(f"{AUTH}/setup", json=body).status_code == 409


def test_setup_needs_the_secret_token_when_one_is_configured(anon_client, test_settings):
    test_settings.setup_token = "s3cret"
    body = {"email": "boss@example.com", "name": "Boss", "password": "longpassword"}
    assert anon_client.post(f"{AUTH}/setup", json=body).status_code == 403
    assert anon_client.post(f"{AUTH}/setup", json=body, headers={"X-Setup-Token": "wrong"}).status_code == 403
    assert anon_client.post(f"{AUTH}/setup", json=body, headers={"X-Setup-Token": "s3cret"}).status_code == 201


def test_setup_validates_input(anon_client):
    assert anon_client.post(f"{AUTH}/setup", json={"email": "nope", "name": "A", "password": "longpassword"}).status_code == 422
    assert anon_client.post(f"{AUTH}/setup", json={"email": "a@b.co", "name": "A", "password": "short"}).status_code == 422


def test_login_returns_a_token_that_works(anon_client, make_client):
    email = make_client("analyst").user_email
    response = login(anon_client, email.upper())  # email is case-insensitive
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer" and body["user"]["role"] == "analyst" and body["expires_in"] > 0
    me = anon_client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.status_code == 200 and me.json()["email"] == email


def test_wrong_password_and_unknown_user_get_the_same_answer(anon_client, make_client):
    email = make_client("viewer").user_email
    wrong = login(anon_client, email, "not-the-password")
    unknown = login(anon_client, "ghost@example.com")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


def test_repeated_failures_lock_the_account_for_a_while(anon_client, make_client, test_settings):
    test_settings.login_max_failures = 3
    email = make_client("viewer").user_email
    for _ in range(3):
        assert login(anon_client, email, "bad-password").status_code == 401
    assert login(anon_client, email, PASSWORD).status_code == 429  # even the right password is refused


def test_logout_revokes_the_token_immediately(make_client):
    user = make_client("viewer")
    assert user.get(f"{AUTH}/me").status_code == 200
    assert user.post(f"{AUTH}/logout").status_code == 204
    assert user.get(f"{AUTH}/me").status_code == 401


def test_disabled_user_cannot_use_an_existing_token(make_client):
    assert make_client("viewer", active=False).get(f"{AUTH}/me").status_code == 401


def test_disabled_user_cannot_log_in(anon_client, make_client, client):
    viewer = make_client("viewer")
    client.patch(f"/api/v1/users/{viewer.user_id}", json={"is_active": False})
    assert login(anon_client, viewer.user_email).status_code == 401


def test_expired_token_is_rejected(anon_client, session_factory):
    from app.services import auth as auth_service

    with session_factory() as db:
        user = auth_service.create_user(db, email="old@example.com", name="Old", password=PASSWORD, role="viewer")
        token, _ = auth_service.issue_token(db, user, ttl_hours=-1)
    assert anon_client.get(f"{AUTH}/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_protected_endpoints_need_a_login_but_health_is_public(anon_client):
    assert anon_client.get("/api/v1/documents").status_code == 401
    assert anon_client.get("/api/v1/agents").status_code == 401
    assert anon_client.post("/api/v1/search", json={"query": "x"}).status_code == 401
    assert anon_client.get(f"{AUTH}/me", headers={"Authorization": "Bearer garbage"}).status_code == 401
    assert anon_client.get("/health").status_code == 200
