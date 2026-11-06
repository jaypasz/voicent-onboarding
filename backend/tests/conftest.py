import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings  # noqa: E402
from app.main import create_app  # noqa: E402

JWT_SECRET = "test-jwt-secret-that-is-long-enough-for-hs256"
SERVICE_TOKEN = "service-token-0123456789-abcdef"


@pytest.fixture()
def client():
    """Auth off, in-memory database: the fast path for logic tests."""
    app = create_app(Settings(database_url="sqlite://", auth_disabled=True, app_env="local"))
    with TestClient(app) as c:
        c.app_state = app.state
        yield c


@pytest.fixture()
def secure_client():
    """Real auth: a JWT secret and one service token."""
    app = create_app(Settings(database_url="sqlite://", supabase_jwt_secret=JWT_SECRET, service_tokens=[SERVICE_TOKEN]))
    with TestClient(app) as c:
        c.app_state = app.state
        yield c
