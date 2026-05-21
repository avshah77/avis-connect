"""Credential encryption using Fernet symmetric encryption."""
from __future__ import annotations

import os
from cryptography.fernet import Fernet


def _fernet() -> Fernet:
    key = os.getenv("CONNECT_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("CONNECT_ENCRYPTION_KEY not set in environment")
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    return _fernet().decrypt(value.encode()).decode()


def generate_key() -> str:
    """Utility — run once to generate a key for .env."""
    return Fernet.generate_key().decode()
