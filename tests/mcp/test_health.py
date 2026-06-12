"""Tests for /health endpoint via HealthMiddleware."""

from unittest.mock import patch

from starlette.testclient import TestClient


def _create_app():
    """Create the HTTP app with mocked stores."""
    with patch("linglong.mcp.tools.init_stores"):
        from linglong.mcp.server import create_http_app

        return create_http_app()


def test_health_returns_ok():
    app = _create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_no_auth_required():
    """Health endpoint should return 200 without Authorization header."""
    app = _create_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
