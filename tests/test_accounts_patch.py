"""Tests for _patch_oauth_success_page in accounts.py.

Covers the monkey-patch of KaggleOAuth.OAuthCallbackHandler._handle_oauth_callback
to serve a branded success page instead of the default kagglesdk page.
"""
from __future__ import annotations

import sys
import unittest.mock
from unittest.mock import MagicMock, patch


# We test the patch under two conditions: kagglesdk available and unavailable.
# Both must be tested because the function handles ImportError gracefully.


def _make_mock_kagglesdk():
    """Build a fake kagglesdk module that _patch_oauth_success_page can import from."""
    import types

    class MockOAuthCallbackHandler:
        @staticmethod
        def _handle_oauth_callback(self):
            pass

        def __init__(self):
            self.path = "/callback?code=abc123&state=teststate"
            self._oauth_state = MagicMock()
            self._oauth_state.state = "teststate"
            self._on_success_called = None

        def send_response(self, code):
            self.sent_code = code

        def send_header(self, name, value):
            pass

        def end_headers(self):
            pass

        def _on_success(self, code):
            self._on_success_called = code

        @property
        def wfile(self):
            return self._wfile

        @wfile.setter
        def wfile(self, val):
            pass

    # We need wfile to be a writable BytesIO-like object
    import io

    class HandlerWithFile(MockOAuthCallbackHandler):
        def __init__(self):
            super().__init__()
            self._wfile = io.BytesIO()

    kaggle_oauth = types.ModuleType("kaggle_oauth")
    kaggle_oauth.KaggleOAuth = MagicMock()
    kaggle_oauth.KaggleOAuth.OAuthCallbackHandler = MockOAuthCallbackHandler

    kaggle = types.ModuleType("kagglesdk")
    kaggle.kaggle_oauth = kaggle_oauth

    return kaggle, HandlerWithFile


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPatchUnavailable:
    """When kagglesdk is not installed the function should silently pass."""

    def test_import_error_swallowed(self):
        from kaggle_switch.commands.accounts import _patch_oauth_success_page

        # Ensure kagglesdk is truly not importable
        with patch.dict(sys.modules, {"kagglesdk": None}):
            # Should not raise
            _patch_oauth_success_page()
            # If we got here without exception, success.


class TestPatchApplied:
    """When kagglesdk IS available, the patch is applied correctly."""

    def test_patch_replaces_handler(self):
        """The callback handler is replaced with the custom patched version."""
        mock_module, _ = _make_mock_kagglesdk()
        orig = mock_module.kaggle_oauth.KaggleOAuth.OAuthCallbackHandler._handle_oauth_callback

        with patch.dict(sys.modules, {"kagglesdk": mock_module, "kagglesdk.kaggle_oauth": mock_module.kaggle_oauth}):
            from kaggle_switch.commands.accounts import _patch_oauth_success_page

            _patch_oauth_success_page()

        replaced = mock_module.kaggle_oauth.KaggleOAuth.OAuthCallbackHandler._handle_oauth_callback
        assert replaced != orig, "Handler should have been replaced"

    def test_success_path(self):
        """Valid code + matching state -> 200, success HTML, _on_success called."""
        mock_module, Handler = _make_mock_kagglesdk()
        with patch.dict(sys.modules, {"kagglesdk": mock_module, "kagglesdk.kaggle_oauth": mock_module.kaggle_oauth}):
            from kaggle_switch.commands.accounts import _patch_oauth_success_page

            _patch_oauth_success_page()
            handler = Handler()
            handler._handle_oauth_callback()

        assert handler.sent_code == 200
        body = handler._wfile.getvalue()
        assert b"Authentication Successful" in body
        assert handler._on_success_called == "abc123"

    def test_invalid_state(self):
        """code present but state mismatch -> 200 but 'Invalid state' HTML, no _on_success."""
        mock_module, Handler = _make_mock_kagglesdk()
        with patch.dict(sys.modules, {"kagglesdk": mock_module, "kagglesdk.kaggle_oauth": mock_module.kaggle_oauth}):
            from kaggle_switch.commands.accounts import _patch_oauth_success_page

            _patch_oauth_success_page()
            handler = Handler()
            handler._oauth_state.state = "different"
            handler._handle_oauth_callback()

        assert handler.sent_code == 200
        body = handler._wfile.getvalue()
        assert b"Invalid state" in body
        assert handler._on_success_called is None

    def test_missing_params_returns_400(self):
        """No 'code' or 'state' in query -> 400, failure HTML."""
        mock_module, Handler = _make_mock_kagglesdk()
        with patch.dict(sys.modules, {"kagglesdk": mock_module, "kagglesdk.kaggle_oauth": mock_module.kaggle_oauth}):
            from kaggle_switch.commands.accounts import _patch_oauth_success_page

            _patch_oauth_success_page()
            handler = Handler()
            handler.path = "/callback?foo=bar"
            handler._handle_oauth_callback()

        assert handler.sent_code == 400
        body = handler._wfile.getvalue()
        assert b"Invalid callback parameters" in body
        assert handler._on_success_called is None


class TestPatchGuard:
    """The co_code guard prevents re-applying an identical patch."""

    def test_identical_co_code_skips_patch(self):
        """If bytecode is identical, the handler is NOT replaced again."""
        mock_module, _ = _make_mock_kagglesdk()
        OCC = mock_module.kaggle_oauth.KaggleOAuth.OAuthCallbackHandler

        # Apply once
        with patch.dict(sys.modules, {"kagglesdk": mock_module, "kagglesdk.kaggle_oauth": mock_module.kaggle_oauth}):
            from kaggle_switch.commands.accounts import _patch_oauth_success_page

            _patch_oauth_success_page()
            first_patch = OCC._handle_oauth_callback

            # Apply again — identical co_code should skip
            _patch_oauth_success_page()
            second_patch = OCC._handle_oauth_callback

        assert first_patch is second_patch, "Should not re-patch when co_code is identical"
