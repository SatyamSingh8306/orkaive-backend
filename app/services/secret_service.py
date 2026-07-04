"""Secret resolution service.

For sensitive headers (Authorization, API keys), tools should reference
a secret by name (`authSecretRef`) instead of putting the value directly
in the tool config. This service resolves the reference at execution time.

In production, back this with Vault / AWS Secrets Manager / GCP Secret
Manager. For now, loads from environment variables:

    ORKAIVE_SECRET_<REF_NAME> = "Header-Name: value"

Example:
    ORKAIVE_SECRET_OPENAI=Authorization: Bearer sk-xxx
"""

from __future__ import annotations

import os
from typing import Optional


class SecretService:
    """Resolves auth secret references to HTTP headers."""

    def __init__(self) -> None:
        self._secrets: dict[str, dict[str, str]] = {}
        self._load_from_env()

    def _load_from_env(self) -> None:
        """Load secrets from ORKAIVE_SECRET_* env vars.

        Format per var: ``Header-Name: value`` (single header).
        """
        for key, value in os.environ.items():
            if not key.startswith("ORKAIVE_SECRET_"):
                continue
            ref_name = key[len("ORKAIVE_SECRET_"):].lower()
            if ":" not in value:
                continue
            header_name, header_value = value.split(":", 1)
            self._secrets[ref_name] = {
                header_name.strip(): header_value.strip()
            }

    def resolve_headers(self, secret_ref: str) -> dict[str, str]:
        """Resolve a secret reference to HTTP headers.

        Args:
            secret_ref: Name of the secret (e.g. ``"openai"``).

        Returns:
            Copy of the stored headers dict.

        Raises:
            KeyError: If the secret is not registered.
        """
        if secret_ref not in self._secrets:
            raise KeyError(f"Secret not found: {secret_ref}")
        return dict(self._secrets[secret_ref])

    def register_secret(self, ref: str, headers: dict[str, str]) -> None:
        """Programmatically register a secret (admin-only)."""
        self._secrets[ref] = dict(headers)


_secret_service: Optional[SecretService] = None


def get_secret_service() -> SecretService:
    """Lazy singleton accessor."""
    global _secret_service
    if _secret_service is None:
        _secret_service = SecretService()
    return _secret_service
