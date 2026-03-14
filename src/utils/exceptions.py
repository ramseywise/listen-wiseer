"""Exception hierarchy for listen-wiseer.

All application-level exceptions inherit from ``ListenWiseerError`` so callers
can catch either the base class or a specific subclass as needed.
"""


class ListenWiseerError(Exception):
    """Base exception for all listen-wiseer errors."""


class ConfigurationError(ListenWiseerError):
    """Missing or invalid environment configuration."""


class SpotifyClientError(ListenWiseerError):
    """Spotify API request failures."""


class SpotifyAuthError(SpotifyClientError):
    """OAuth token exchange or refresh failures."""


class DataLoadError(ListenWiseerError):
    """Failure loading or parsing local data files."""
