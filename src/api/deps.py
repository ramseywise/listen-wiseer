"""Request dependencies shared by every router (process-wide clients live on ``app.state``)."""

from typing import Annotated, Protocol

import duckdb
from fastapi import Depends, Request

from sources.subsonic import SubsonicClient


def get_subsonic(request: Request) -> SubsonicClient:
    return request.app.state.subsonic


Subsonic = Annotated[SubsonicClient, Depends(get_subsonic)]


class DbConnect(Protocol):
    """``etl.db.get_connection`` or a test stand-in over a tmp file."""

    def __call__(self, read_only: bool = False) -> duckdb.DuckDBPyConnection: ...


def get_db_connect(request: Request) -> DbConnect:
    return request.app.state.db_connect


# DuckDB is single-writer across processes: open per request (in a worker thread), close fast.
Db = Annotated[DbConnect, Depends(get_db_connect)]
