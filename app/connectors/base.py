"""Base connector interface — all connector plugins must inherit this."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
    """
    Every connector plugin must:
      - Set a class-level `name` str (used as registry key, e.g. "netsuite")
      - Implement `execute()`
      - Optionally override `health_check()`
    """

    name: str  # registry key — must be unique across all plugins

    @abstractmethod
    def execute(
        self,
        operation: str,
        endpoint: str,
        method: str,
        payload: dict[str, Any],
        credentials: dict[str, str],
    ) -> dict:
        """
        Execute one operation against the external system.

        Args:
            operation:   Logical name (e.g. "create_so") — for logging/routing.
            endpoint:    Relative path ("/salesorder") or full URL.
            method:      HTTP verb — GET, POST, PATCH, DELETE.
            payload:     Business payload in the target system's expected format.
            credentials: Decrypted key→value dict from the credential vault.

        Returns:
            Parsed response dict from the external system.

        Raises:
            Any exception on failure — the engine catches, logs, and marks the
            push_log row as "error".
        """
        ...

    def health_check(self, credentials: dict[str, str]) -> bool:
        """Liveness probe. Override to verify the external system is reachable."""
        return True
