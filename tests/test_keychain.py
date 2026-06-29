"""Tests for keychain module."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from kaggle_switch import keychain


@pytest.fixture(autouse=True)
def reset_keyring_flag():
    """Reset KEYRING_AVAILABLE to True before each test."""
    original = keychain.KEYRING_AVAILABLE
    keychain.KEYRING_AVAILABLE = True
    yield
    keychain.KEYRING_AVAILABLE = original


class TestStoreToken:
    @patch("kaggle_switch.keychain.keyring")
    def test_store_returns_true_on_success(self, mock_kring):
        assert keychain.store_token("work", "KGAT_abc123") is True
        mock_kring.set_password.assert_called_once_with("kagitch", "work", "KGAT_abc123")

    @patch("kaggle_switch.keychain.keyring")
    def test_store_returns_false_on_exception(self, mock_kring):
        mock_kring.set_password.side_effect = RuntimeError("no keyring")
        assert keychain.store_token("work", "KGAT_abc123") is False

    def test_store_returns_false_when_keyring_unavailable(self):
        keychain.KEYRING_AVAILABLE = False
        assert keychain.store_token("work", "KGAT_abc123") is False


class TestGetToken:
    @patch("kaggle_switch.keychain.keyring")
    def test_get_returns_token(self, mock_kring):
        mock_kring.get_password.return_value = "KGAT_abc123"
        assert keychain.get_token("work") == "KGAT_abc123"
        mock_kring.get_password.assert_called_once_with("kagitch", "work")

    @patch("kaggle_switch.keychain.keyring")
    def test_get_returns_none_when_not_found(self, mock_kring):
        mock_kring.get_password.return_value = None
        assert keychain.get_token("nonexistent") is None

    @patch("kaggle_switch.keychain.keyring")
    def test_get_returns_none_on_exception(self, mock_kring):
        mock_kring.get_password.side_effect = RuntimeError("no keyring")
        assert keychain.get_token("work") is None

    def test_get_returns_none_when_keyring_unavailable(self):
        keychain.KEYRING_AVAILABLE = False
        assert keychain.get_token("work") is None


class TestDeleteToken:
    @patch("kaggle_switch.keychain.keyring")
    def test_delete_returns_true_on_success(self, mock_kring):
        assert keychain.delete_token("work") is True
        mock_kring.delete_password.assert_called_once_with("kagitch", "work")

    @patch("kaggle_switch.keychain.keyring")
    def test_delete_returns_false_on_exception(self, mock_kring):
        mock_kring.delete_password.side_effect = RuntimeError("no keyring")
        assert keychain.delete_token("work") is False

    def test_delete_returns_false_when_keyring_unavailable(self):
        keychain.KEYRING_AVAILABLE = False
        assert keychain.delete_token("work") is False
