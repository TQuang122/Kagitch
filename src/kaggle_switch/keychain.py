"""Secure token storage using OS keychain."""
from __future__ import annotations

import sys
from typing import Optional

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

SERVICE_NAME = "kagitch"


def store_token(account_name: str, token: str) -> bool:
    """Store token in OS keychain. Returns True on success."""
    if not KEYRING_AVAILABLE:
        return False
    try:
        keyring.set_password(SERVICE_NAME, account_name, token)
        return True
    except Exception:
        return False


def get_token(account_name: str) -> Optional[str]:
    """Retrieve token from OS keychain. Returns None if not found."""
    if not KEYRING_AVAILABLE:
        return None
    try:
        return keyring.get_password(SERVICE_NAME, account_name)
    except Exception:
        return None


def delete_token(account_name: str) -> bool:
    """Delete token from OS keychain. Returns True on success."""
    if not KEYRING_AVAILABLE:
        return False
    try:
        keyring.delete_password(SERVICE_NAME, account_name)
        return True
    except Exception:
        return False
