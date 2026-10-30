"""Track identities → Navidrome song ids, for anything that turns a track list into a
Navidrome playlist (archive copy, ``local_playlists`` migration).

``song_ids_for`` is the only caller of ``library.match`` here — keep it that way so a change
in the matcher's API is a one-place fix.
"""

from collections.abc import Sequence

from library.match import MatchCache, match_tracks
from sources.schemas import TrackRef
from sources.subsonic import SubsonicClient


async def song_ids_for(
    client: SubsonicClient, refs: Sequence[TrackRef], *, cache: MatchCache | None = None
) -> tuple[list[str], list[int]]:
    """Matched song ids in input order (repeats dropped) + indexes of the refs that missed."""
    results = await match_tracks(client, refs, cache=cache)
    matched = list(dict.fromkeys(r.song_id for r in results if r is not None))
    return matched, [n for n, r in enumerate(results) if r is None]
