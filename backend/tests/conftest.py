import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models, security  # noqa: F401  (models registers the tables)
from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import app as fastapi_app
from app.services import auth as auth_service
from app.services.embeddings import get_embedder
from app.services.llm import get_chat
from app.services.storage import LocalStorage, get_storage
from tests.fakes import FakeChat, HashEmbedder

PASSWORD = "password123"


@pytest.fixture(autouse=True)
def fast_password_hashing(monkeypatch):
    """Real scrypt is deliberately slow; use a cheap setting so the test suite stays fast."""
    monkeypatch.setattr(security, "SCRYPT_N", 2**10)


@pytest.fixture()
def storage(tmp_path):
    return LocalStorage(tmp_path / "uploads")


@pytest.fixture()
def embedder():
    return HashEmbedder()


@pytest.fixture()
def chat():
    return FakeChat()


@pytest.fixture()
def test_settings(tmp_path):
    return Settings(
        database_url="sqlite://",
        storage_dir=tmp_path / "uploads",
        max_upload_mb=1,
        ollama_base_url="http://127.0.0.1:9",  # nothing listens here -> "Ollama is down"
    )


@pytest.fixture()
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def app_env(session_factory, storage, embedder, chat, test_settings):
    """Wires the app to a throw-away in-memory database, a temp upload folder and fake AI."""

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = override_db
    fastapi_app.dependency_overrides[get_storage] = lambda: storage
    fastapi_app.dependency_overrides[get_embedder] = lambda: embedder
    fastapi_app.dependency_overrides[get_chat] = lambda: chat
    fastapi_app.dependency_overrides[get_settings] = lambda: test_settings
    yield session_factory
    fastapi_app.dependency_overrides.clear()


@pytest.fixture()
def make_client(app_env):
    """Create a user with the given role and return a client that is logged in as them."""
    counter = {"n": 0}

    def factory(role: str = "admin", active: bool = True) -> TestClient:
        counter["n"] += 1
        email = f"{role}{counter['n']}@example.com"
        with app_env() as db:
            user = auth_service.create_user(db, email=email, name=f"Test {role}", password=PASSWORD, role=role)
            token, _ = auth_service.issue_token(db, user, 12)
            if not active:
                user.is_active = False
                db.commit()
            user_id = user.id
        http = TestClient(fastapi_app, headers={"Authorization": f"Bearer {token}"})
        http.user_email, http.user_id = email, user_id
        return http

    return factory


@pytest.fixture()
def client(make_client):
    """Logged in as an admin, so tests written before roles existed keep working."""
    return make_client("admin")


@pytest.fixture()
def anon_client(app_env):
    """Not logged in."""
    # Not used as a context manager on purpose: skips the startup hook that touches the real DB.
    return TestClient(fastapi_app)
