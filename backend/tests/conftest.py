import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (registers tables)
from app.config import Settings, get_settings
from app.database import Base, get_db
from app.main import app as fastapi_app
from app.services.embeddings import get_embedder
from app.services.llm import get_chat
from app.services.storage import LocalStorage, get_storage
from tests.fakes import FakeChat, HashEmbedder


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
def client(tmp_path, storage, embedder, chat):
    """A test client wired to a throw-away in-memory database, a temp upload folder and fake AI."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = override_db
    fastapi_app.dependency_overrides[get_storage] = lambda: storage
    fastapi_app.dependency_overrides[get_embedder] = lambda: embedder
    fastapi_app.dependency_overrides[get_chat] = lambda: chat
    fastapi_app.dependency_overrides[get_settings] = lambda: Settings(
        database_url="sqlite://",
        storage_dir=tmp_path / "uploads",
        max_upload_mb=1,
        ollama_base_url="http://127.0.0.1:9",  # nothing listens here -> "Ollama is down"
    )
    # Not used as a context manager on purpose: skips the startup hook that touches the real DB.
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()
