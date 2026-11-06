from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import cli, models as m
from app.config import Settings
from app.db import make_engine


def test_seed_creates_org_member_and_presets_and_is_safe_to_rerun(tmp_path):
    url = f"sqlite:///{tmp_path / 's.db'}"
    s = Settings(database_url=url, auth_disabled=True, app_env="local")
    lines: list[str] = []
    org_id = cli.seed(s, "Voicent", "voicent", "user-123", "jay@example.com", out=lines.append)
    again = cli.seed(s, "Voicent", "voicent", "user-123", "jay@example.com", out=lines.append)
    assert org_id == again
    with sessionmaker(make_engine(url))() as db:
        assert db.query(m.Org).count() == 1 and db.query(m.OrgMember).count() == 1
        assert db.query(m.Template).count() == 4
    assert "Presets added: none" in lines[-1]


def test_a_seeded_user_can_use_the_api(tmp_path):
    import jwt
    from fastapi.testclient import TestClient

    from app.main import create_app
    from tests.conftest import JWT_SECRET

    url = f"sqlite:///{tmp_path / 's.db'}"
    cli.seed(Settings(database_url=url, auth_disabled=True, app_env="local"), "Voicent", "voicent", "user-123", out=lambda *_: None)
    app = create_app(Settings(database_url=url, supabase_jwt_secret=JWT_SECRET))
    tok = jwt.encode({"sub": "user-123", "aud": "authenticated", "exp": 4102444800}, JWT_SECRET, algorithm="HS256")
    with TestClient(app) as c:
        r = c.get("/api/templates", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200 and {t["slug"] for t in r.json()} == {"trades", "agency", "msp", "blank"}


def test_presets_command_refuses_an_unknown_org(tmp_path):
    import pytest

    with pytest.raises(SystemExit):
        cli.presets(Settings(database_url=f"sqlite:///{tmp_path / 'x.db'}", auth_disabled=True, app_env="local"), "nope", out=lambda *_: None)
