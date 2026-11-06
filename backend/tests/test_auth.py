import jwt
import pytest

from app.config import Settings
from app.main import create_app
from tests.conftest import JWT_SECRET, SERVICE_TOKEN


def token(**over):
    claims = {"sub": "user-1", "aud": "authenticated", "exp": 4102444800, "email": "jay@example.com"} | over
    return jwt.encode(claims, JWT_SECRET, algorithm="HS256")


def test_health_is_public(secure_client):
    assert secure_client.get("/api/health").json() == {"ok": True}


def test_me_needs_a_token(secure_client):
    r = secure_client.get("/api/me")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Bearer"


def test_bad_tokens_are_refused(secure_client):
    for bad in ("Bearer nonsense", "Bearer " + token(aud="other"), "Bearer " + token(exp=1), "Basic abc"):
        assert secure_client.get("/api/me", headers={"Authorization": bad}).status_code == 401
    forged = jwt.encode({"sub": "x", "aud": "authenticated", "exp": 4102444800}, "wrong-secret-wrong-secret-wrong-secret", algorithm="HS256")
    assert secure_client.get("/api/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401


def test_user_jwt_and_service_token_both_work(secure_client):
    r = secure_client.get("/api/me", headers={"Authorization": f"Bearer {token()}"})
    assert r.json() == {"id": "user-1", "label": "jay@example.com", "kind": "user"}
    r = secure_client.get("/api/me", headers={"Authorization": f"Bearer {SERVICE_TOKEN}"})
    assert r.json()["kind"] == "service"


def test_auth_disabled_only_in_local():
    with pytest.raises(RuntimeError):
        create_app(Settings(database_url="sqlite://", auth_disabled=True, app_env="production"))


def test_no_auth_configuration_fails_closed():
    with pytest.raises(RuntimeError):
        create_app(Settings(database_url="sqlite://"))


def test_short_service_tokens_are_refused():
    with pytest.raises(RuntimeError):
        create_app(Settings(database_url="sqlite://", service_tokens=["short"]))


def test_swagger_is_local_only(secure_client, client):
    assert secure_client.get("/api/swagger").status_code == 404
    assert client.get("/api/swagger").status_code == 200
