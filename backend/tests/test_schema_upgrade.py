from sqlalchemy import create_engine, inspect, text

from app.database import upgrade_schema


def test_old_databases_get_the_new_columns_once(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE documents (id VARCHAR(32) PRIMARY KEY, filename VARCHAR(255))"))
        conn.execute(text("CREATE TABLE agent_runs (id VARCHAR(32) PRIMARY KEY, task TEXT)"))
        conn.execute(text("INSERT INTO documents VALUES ('d1', 'old.pdf')"))

    assert upgrade_schema(engine) == ["documents.uploaded_by", "agent_runs.user_id"]
    columns = {c["name"] for c in inspect(engine).get_columns("documents")}
    assert "uploaded_by" in columns
    with engine.connect() as conn:  # existing rows survive
        assert conn.execute(text("SELECT filename, uploaded_by FROM documents")).one() == ("old.pdf", None)

    assert upgrade_schema(engine) == []  # safe to run again


def test_missing_tables_are_ignored(tmp_path):
    assert upgrade_schema(create_engine(f"sqlite:///{tmp_path / 'empty.db'}")) == []
