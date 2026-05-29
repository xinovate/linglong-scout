"""Token utilities for MCP authentication and user identification.

Token format: ll-scout-{username}-{12-char-uuid}
Example: ll-scout-xinovate-a1b2c3d4e5f6
"""

import secrets
import string

_SERVICE_PREFIX = "ll-scout"
_USER_ID_LENGTH = 12
_USER_ID_CHARS = string.ascii_lowercase + string.digits


def generate_token(username: str) -> str:
    """Generate a token with the standard format.

    Args:
        username: User identifier (ASCII alphanumeric).

    Returns:
        Token string like ``ll-scout-xinovate-a1b2c3d4e5f6``.
    """
    user_id = "".join(secrets.choice(_USER_ID_CHARS) for _ in range(_USER_ID_LENGTH))
    return f"{_SERVICE_PREFIX}-{username}-{user_id}"


def parse_token(token: str) -> dict[str, str]:
    """Extract username and user_id from a token.

    Args:
        token: Full token string.

    Returns:
        Dict with ``username`` and ``user_id``. Returns ``{"username": "unknown", "user_id": "default"}``
        if the token does not match the expected format.
    """
    parts = token.split("-")
    if len(parts) >= 4 and parts[0] == "ll" and parts[1] == "scout":
        username = parts[2]
        user_id = "-".join(parts[3:])
        return {"username": username, "user_id": user_id}
    return {"username": "unknown", "user_id": "default"}
