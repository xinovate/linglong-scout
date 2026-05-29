"""Tests for token generation and parsing."""

import re

from linglong.mcp.token import generate_token, parse_token


class TestGenerateToken:
    def test_standard_format(self):
        token = generate_token("xinovate")
        assert token.startswith("ll-scout:xinovate:")

    def test_user_id_is_18_chars(self):
        token = generate_token("alice")
        user_id = token.split(":")[-1]
        assert len(user_id) == 18
        assert re.match(r"^[a-z0-9]{18}$", user_id)

    def test_different_tokens_each_call(self):
        t1 = generate_token("test")
        t2 = generate_token("test")
        assert t1 != t2

    def test_chinese_username(self):
        token = generate_token("wangxin")
        assert "ll-scout:wangxin:" in token


class TestParseToken:
    def test_standard_token(self):
        result = parse_token("ll-scout:xinovate:a1b2c3d4e5f6g7h8i9")
        assert result["username"] == "xinovate"
        assert result["user_id"] == "a1b2c3d4e5f6g7h8i9"

    def test_chinese_named_token(self):
        result = parse_token("ll-scout:wangxin:abc123def456ghj789")
        assert result["username"] == "wangxin"
        assert result["user_id"] == "abc123def456ghj789"

    def test_old_hyphen_format_returns_default(self):
        result = parse_token("ll-scout-xinovate-a1b2c3d4e5f6")
        assert result["username"] == "unknown"
        assert result["user_id"] == "default"

    def test_garbage_returns_default(self):
        result = parse_token("random-string")
        assert result["username"] == "unknown"
        assert result["user_id"] == "default"

    def test_missing_field_returns_default(self):
        result = parse_token("ll-scout:xinovate")
        assert result["username"] == "unknown"
        assert result["user_id"] == "default"
