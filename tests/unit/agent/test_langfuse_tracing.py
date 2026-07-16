from __future__ import annotations

from unittest.mock import MagicMock, patch


@patch("utils.langfuse_tracing.settings")
def test_handler_none_when_disabled(mock_settings: MagicMock) -> None:
    mock_settings.enable_langfuse = False
    mock_settings.langfuse_public_key = "pk-test"
    from utils.langfuse_tracing import get_langfuse_handler

    assert get_langfuse_handler() is None


@patch("utils.langfuse_tracing.settings")
def test_handler_none_when_no_public_key(mock_settings: MagicMock) -> None:
    mock_settings.enable_langfuse = True
    mock_settings.langfuse_public_key = ""
    from utils.langfuse_tracing import get_langfuse_handler

    assert get_langfuse_handler() is None


@patch("utils.langfuse_tracing.CallbackHandler")
@patch("utils.langfuse_tracing.settings")
def test_handler_created_when_enabled(mock_settings: MagicMock, mock_cb: MagicMock) -> None:
    mock_settings.enable_langfuse = True
    mock_settings.langfuse_public_key = "pk-lf-test"
    mock_settings.langfuse_secret_key = "sk-lf-test"
    mock_settings.langfuse_host = "http://localhost:3000"
    from utils.langfuse_tracing import get_langfuse_handler

    handler = get_langfuse_handler(session_id="test-session", user_id="user-1")
    mock_cb.assert_called_once_with(
        public_key="pk-lf-test",
        secret_key="sk-lf-test",
        host="http://localhost:3000",
        session_id="test-session",
        user_id="user-1",
        trace_name="listen-wiseer",
    )
    assert handler is not None
