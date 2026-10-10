
import os
import shutil
import tempfile

_TMP = tempfile.mkdtemp(prefix="certgen_tests_")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["STORAGE_DIR"] = f"{_TMP}/certificates"
os.environ["PROCESSING_MODE"] = "inline"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state():
    """Fresh tables and empty storage for every test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    shutil.rmtree(settings.storage_dir, ignore_errors=True)
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def db():
    with SessionLocal() as session:
        yield session


def make_recipients(n: int, prefix: str = "User"):
    return [{"name": f"{prefix} {i}", "email": f"{prefix.lower()}{i}@example.com"} for i in range(n)]


@pytest.fixture()
def payload():
    """A valid request body with 3 recipients."""
    return {
        "course_name": "Advanced Python Programming",
        "issued_by": "Acme Academy",
        "issue_date": "2026-10-10",
        "recipients": make_recipients(3),
    }


@pytest.fixture()
def submit(client, payload):
    """Helper: POST a job (optionally overriding body fields) and return the response."""

    def _submit(**overrides):
        body = {**payload, **overrides}
        return client.post("/api/v1/jobs", json=body)

    return _submit
