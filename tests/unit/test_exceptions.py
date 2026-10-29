"""Unit tests for the internal_models exception hierarchy."""

from utils.exceptions import (
    ConfigurationError,
    DataLoadError,
    ListenWiseerError,
    SourceError,
)


def test_listen_wiseer_error_is_exception() -> None:
    assert issubclass(ListenWiseerError, Exception)


def test_configuration_error_inherits_base() -> None:
    assert issubclass(ConfigurationError, ListenWiseerError)


def test_source_error_inherits_base() -> None:
    assert issubclass(SourceError, ListenWiseerError)


def test_data_load_error_inherits_base() -> None:
    assert issubclass(DataLoadError, ListenWiseerError)


def test_listen_wiseer_error_can_be_raised() -> None:
    import pytest

    with pytest.raises(ListenWiseerError):
        raise ListenWiseerError("test")


def test_source_error_caught_as_base() -> None:
    import pytest

    with pytest.raises(ListenWiseerError):
        raise SourceError("musicbrainz 503")


def test_data_load_error_caught_as_base() -> None:
    import pytest

    with pytest.raises(ListenWiseerError):
        raise DataLoadError("file not found")
