"""Bridge exception types.

These are the daemon's own error types; ``BridgeError`` is separate and lives
in ``bridge_client.py``.
"""

from __future__ import annotations


class MissingEnvError(Exception):
    """A required environment variable is missing or wrong-shaped.

    Carries a stable error ``code`` an LLM operator can branch on, and a
    human-readable ``remediation`` pointing at the operations doc.
    """

    def __init__(self, code: str, message: str, remediation: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.remediation = remediation

    def to_payload(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
        }


class DiscordNotReadyError(Exception):
    """The Discord WebSocket is not in a state where an interaction call would
    succeed (no session_id available). Distinct from MissingEnvError so the
    Flask layer can return 503 with a structured retryable-error envelope.
    """

    code = "DISCORD_NOT_READY"
    remediation = (
        "Wait for the bridge's reconnect loop to re-establish the gateway "
        "session. Check GET /health for discord_ready=true; the daemon will "
        "back off and retry automatically unless DISCORD_RECONNECT_FAILED was "
        "emitted (terminal auth failure — operator must rotate the token)."
    )

    def __init__(self, detail: str) -> None:
        super().__init__(f"Discord client not ready: {detail}")
        self.detail = detail
