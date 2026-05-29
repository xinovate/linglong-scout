"""Token utilities for MCP authentication and user identification.

Token format: ll-scout:{username}:{18-char-uuid}
Example: ll-scout:xinovate:a1b2c3d4e5f6g7h8i9
"""

import secrets
import string

_SERVICE_PREFIX = "ll-scout"
_USER_ID_LENGTH = 18
_USER_ID_CHARS = string.ascii_lowercase + string.digits


def generate_token(username: str) -> str:
    """Generate a token with the standard format.

    Args:
        username: User identifier (ASCII alphanumeric).

    Returns:
        Token string like ``ll-scout:xinovate:a1b2c3d4e5f6g7h8i9``.
    """
    user_id = "".join(secrets.choice(_USER_ID_CHARS) for _ in range(_USER_ID_LENGTH))
    return f"{_SERVICE_PREFIX}:{username}:{user_id}"


def parse_token(token: str) -> dict[str, str]:
    """Extract username and user_id from a token.

    Args:
        token: Full token string.

    Returns:
        Dict with ``username`` and ``user_id``. Returns ``{"username": "unknown", "user_id": "default"}``
        if the token does not match the expected format.
    """
    if token.startswith(f"{_SERVICE_PREFIX}:"):
        remainder = token[len(_SERVICE_PREFIX) + 1:]
        parts = remainder.split(":")
        if len(parts) == 2 and parts[0] and parts[1]:
            return {"username": parts[0], "user_id": parts[1]}
    return {"username": "unknown", "user_id": "default"}
