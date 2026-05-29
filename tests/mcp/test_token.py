"""Tests for token generation and parsing."""

import re

from linglong.mcp.token import generate_token, parse_token


class TestGenerateToken:
    def test_standard_format(self):
        token = generate_token("xinovate")
        assert token.startswith("ll-scout-xinovate-")

    def test_user_id_is_12_chars(self):
        token = generate_token("alice")
        user_id = token.split("-")[-1]
        assert len(user_id) == 12
        assert re.match(r"^[a-z0-9]{12}$", user_id)

    def test_different_tokens_each_call(self):
        t1 = generate_token("test")
        t2 = generate_token("test")
        assert t1 != t2

    def test_chinese_username(self):
        token = generate_token("wangxin")
        assert "ll-scout-wangxin-" in token


class TestParseToken:
    def test_standard_token(self):
        result = parse_token("ll-scout-xinovate-a1b2c3d4e5f6")
        assert result["username"] == "xinovate"
        assert result["user_id"] == "a1b2c3d4e5f6"

    def test_chinese_named_token(self):
        result = parse_token("ll-scout-wangxin-abc123def456")
        assert result["username"] == "wangxin"
        assert result["user_id"] == "abc123def456"

    def test_old_format_returns_default(self):
        result = parse_token("linglong-ingest-7kXm9pR2")
        assert result["username"] == "unknown"
        assert result["user_id"] == "default"

    def test_garbage_returns_default(self):
        result = parse_token("random-string")
        assert result["username"] == "unknown"
        assert result["user_id"] == "default"
