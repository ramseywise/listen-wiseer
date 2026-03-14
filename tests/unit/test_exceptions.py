"""Unit tests for the internal_models exception hierarchy."""

from utils.exceptions import (
    ConfigurationError,
    DataLoadError,
    ListenWiseerError,
    SpotifyAuthError,
    SpotifyClientError,
)


def test_listen_wiseer_error_is_exception() -> None:
    assert issubclass(ListenWiseerError, Exception)


def test_configuration_error_inherits_base() -> None:
    assert issubclass(ConfigurationError, ListenWiseerError)


def test_spotify_client_error_inherits_base() -> None:
    assert issubclass(SpotifyClientError, ListenWiseerError)


def test_spotify_auth_error_inherits_spotify_client_error() -> None:
    assert issubclass(SpotifyAuthError, SpotifyClientError)


def test_spotify_auth_error_inherits_base() -> None:
    assert issubclass(SpotifyAuthError, ListenWiseerError)


def test_data_load_error_inherits_base() -> None:
    assert issubclass(DataLoadError, ListenWiseerError)


def test_listen_wiseer_error_can_be_raised() -> None:
    import pytest

    with pytest.raises(ListenWiseerError):
        raise ListenWiseerError("test")


def test_spotify_auth_error_caught_as_spotify_client_error() -> None:
    import pytest

    with pytest.raises(SpotifyClientError):
        raise SpotifyAuthError("token exchange failed")


def test_spotify_auth_error_caught_as_base() -> None:
    import pytest

    with pytest.raises(ListenWiseerError):
        raise SpotifyAuthError("token exchange failed")


def test_data_load_error_caught_as_base() -> None:
    import pytest

    with pytest.raises(ListenWiseerError):
        raise DataLoadError("file not found")
