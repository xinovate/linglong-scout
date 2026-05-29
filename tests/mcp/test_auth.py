"""Tests for MCP token authentication middleware."""

from unittest.mock import MagicMock, patch

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from linglong.mcp._auth import (
    TokenAuthMiddleware,
    get_current_token,
    get_current_user_id,
    get_current_username,
)
from linglong.mcp.token import generate_token


async def _mcp_endpoint(request):
    return PlainTextResponse("ok")


async def _health(request):
    return PlainTextResponse("healthy")


def _create_app(token: str = "", redis_url: str = "") -> Starlette:
    """Create a minimal Starlette app with TokenAuthMiddleware."""
    routes = [
        Route("/mcp/scout", _mcp_endpoint),
        Route("/health", _health),
    ]
    app = Starlette(routes=routes)
    app.add_middleware(
        TokenAuthMiddleware, expected_token=token, redis_url=redis_url
    )
    return app


def _find_middleware(app: Starlette) -> TokenAuthMiddleware | None:
    """Walk the Starlette middleware stack to find TokenAuthMiddleware."""
    current = app.middleware_stack
    while hasattr(current, "app"):
        if isinstance(current, TokenAuthMiddleware):
            return current
        current = current.app
    return None


class TestTokenAuthMiddleware:
    """Tests for TokenAuthMiddleware request handling."""

    def test_allows_mcp_path_with_valid_static_token(self):
        token = generate_token("testuser")
        app = _create_app(token=token)
        client = TestClient(app)

        response = client.get(
            "/mcp/scout", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert response.text == "ok"

    def test_rejects_mcp_path_without_token(self):
        app = _create_app(token="some-token")
        client = TestClient(app)

        response = client.get("/mcp/scout")

        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized"}

    def test_rejects_mcp_path_with_invalid_token(self):
        app = _create_app(token="correct-token")
        client = TestClient(app)

        response = client.get(
            "/mcp/scout",
            headers={"Authorization": "Bearer wrong-token"},
        )

        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized"}

    def test_allows_non_mcp_path_without_token(self):
        app = _create_app(token="some-token")
        client = TestClient(app)

        response = client.get("/health")

        assert response.status_code == 200
        assert response.text == "healthy"

    def test_rejects_non_bearer_auth(self):
        app = _create_app(token="some-token")
        client = TestClient(app)

        response = client.get(
            "/mcp/scout",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )

        assert response.status_code == 401
        assert response.json() == {"error": "Unauthorized"}

    def test_valid_token_sets_context_vars(self):
        token = generate_token("alice")
        parsed = {}

        async def capture_context(request):
            parsed["username"] = get_current_username()
            parsed["user_id"] = get_current_user_id()
            parsed["token"] = get_current_token()
            return PlainTextResponse("checked")

        routes = [
            Route("/mcp/scout", capture_context),
            Route("/health", _health),
        ]
        app = Starlette(routes=routes)
        app.add_middleware(TokenAuthMiddleware, expected_token=token)
        client = TestClient(app)

        response = client.get(
            "/mcp/scout", headers={"Authorization": f"Bearer {token}"}
        )

        assert response.status_code == 200
        assert parsed["username"] == "alice"
        assert parsed["token"] == token
        assert parsed["user_id"]

    def test_redis_validation_with_active_token(self):
        token = generate_token("testuser")
        app = _create_app(token="fallback-static", redis_url="redis://localhost:6379")
        client = TestClient(app)

        mock_redis = MagicMock()
        mock_redis.exists.return_value = 1

        mw = _find_middleware(client.app)
        if mw is not None:
            mw._redis = mock_redis
            response = client.get(
                "/mcp/scout", headers={"Authorization": f"Bearer {token}"}
            )
            assert response.status_code == 200
        else:
            # Fallback: directly test _validate_token behavior
            mw_instance = TokenAuthMiddleware(
                lambda r: None,
                expected_token="fallback-static",
                redis_url="redis://localhost:6379",
            )
            mw_instance._redis = mock_redis
            assert mw_instance._validate_token(token) is True
            mock_redis.exists.assert_called_once_with(token)

    def test_redis_validation_with_inactive_token(self):
        token = generate_token("testuser")
        mock_redis = MagicMock()
        mock_redis.exists.return_value = 0

        mw = TokenAuthMiddleware(
            lambda r: None,
            expected_token="fallback-static",
            redis_url="redis://localhost:6379",
        )
        mw._redis = mock_redis

        assert mw._validate_token(token) is False
        mock_redis.exists.assert_called_once_with(token)

    def test_fallback_to_static_when_redis_fails(self):
        static_token = generate_token("testuser")
        mock_redis = MagicMock()
        mock_redis.exists.side_effect = Exception("Connection refused")

        mw = TokenAuthMiddleware(
            lambda r: None,
            expected_token=static_token,
            redis_url="redis://localhost:6379",
        )
        mw._redis = mock_redis

        assert mw._validate_token(static_token) is True

    def test_rejects_empty_authorization_header(self):
        app = _create_app(token="some-token")
        client = TestClient(app)

        response = client.get(
            "/mcp/scout", headers={"Authorization": ""}
        )

        assert response.status_code == 401


class TestContextVarDefaults:
    """Tests for context variable accessor defaults."""

    def test_default_user_id(self):
        assert get_current_user_id() == "default"

    def test_default_username(self):
        assert get_current_username() == "unknown"

    def test_default_token(self):
        assert get_current_token() == ""


class TestValidateTokenUnit:
    """Unit tests for _validate_token covering edge cases."""

    def test_no_redis_no_static_token_rejects(self):
        mw = TokenAuthMiddleware(lambda r: None, expected_token="", redis_url="")
        assert mw._validate_token("any-token") is False

    def test_static_token_matches(self):
        mw = TokenAuthMiddleware(
            lambda r: None, expected_token="my-secret", redis_url=""
        )
        assert mw._validate_token("my-secret") is True

    def test_static_token_mismatch(self):
        mw = TokenAuthMiddleware(
            lambda r: None, expected_token="my-secret", redis_url=""
        )
        assert mw._validate_token("wrong") is False

    def test_redis_get_redis_returns_none_when_no_url(self):
        mw = TokenAuthMiddleware(
            lambda r: None, expected_token="tok", redis_url=""
        )
        assert mw._get_redis() is None

    def test_redis_get_redis_caches_instance(self):
        mock_redis = MagicMock()
        mw = TokenAuthMiddleware(
            lambda r: None, expected_token="tok", redis_url="redis://localhost:6379"
        )
        mw._redis = mock_redis
        result = mw._get_redis()
        assert result is mock_redis
