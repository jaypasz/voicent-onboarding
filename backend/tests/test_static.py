from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_spa_is_served_and_api_stays_404(tmp_path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<html>app</html>")
    (tmp_path / "secret.txt").write_text("outside the static folder")
    app = create_app(Settings(database_url="sqlite://", auth_disabled=True, app_env="local", static_dir=str(site)))
    with TestClient(app) as c:
        assert "app" in c.get("/c/some-token").text  # client-side route lands on index.html
        assert c.get("/api/nothing").status_code == 404
        for sneaky in ("/%2e%2e/secret.txt", "/..%2fsecret.txt", "/%2e%2e%2fsecret.txt"):
            assert "outside the static folder" not in c.get(sneaky).text
