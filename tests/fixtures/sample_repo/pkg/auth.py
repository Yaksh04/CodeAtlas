"""Authentication helpers (fixture for retrieval tests)."""


def validate_token(token: str) -> bool:
    """Check that a JWT token is well formed and not expired."""
    return token.count(".") == 2


def getUserById(user_id: int):
    """Look a user up by primary key."""
    return {"id": user_id}


class HTTPAuthMiddleware:
    """Reject requests that carry no valid credentials."""

    def process_request(self, request):
        token = request.headers.get("Authorization", "")
        return validate_token(token)
