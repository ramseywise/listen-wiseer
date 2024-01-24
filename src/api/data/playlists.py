import logger
import numpy as np
import pandas as pd

# from pydantic import BaseModel
from modeling.utils.const import *
from api.spotify_client import *

log = logger.get_logger("app")

spAuth = SpotifyAuth(client_id, client_secret, redirect_uri, token_url)
spApi = SpotifyPlaylistApi()

# from api.data.schema import *

# import data schema to validate playlist data
# data_schema = PlaylistFeaturesSchema()
# data_schema.context = {
#    "artist_schema": ArtistFeaturesSchema(),
#    "audio_schema": AudioFeaturesSchema(),
#    "track_schema": TrackFeaturesSchema(),
# }


class SpotifyPlaylistData:
    """Transforms JSON data from Spotify API to dataframe."""

    track_ids: list
    track_uris: list
    track_names: list
    release_date: list
    artist_ids: list
    artist_names: list

    def __init__(self):
        self.track_ids = []
        self.track_uris = []
        self.track_names = []
        self.release_dates = []
        self.artist_ids = []
        self.artist_names = []

    def return_my_tracks(self, tracks: dict, playlist_id: str, playlist_name: str):
        for i in range(len(tracks)):
            self.track_ids.append(tracks[i]["track"]["id"])
            self.track_uris.append(tracks[i]["track"]["uri"])
            self.track_names.append(tracks[i]["track"]["name"])
            artists = [artist["id"] for artist in tracks[i]["track"]["artists"]]
            self.artist_ids.append(artists)
            artists = [artist["name"] for artist in tracks[i]["track"]["artists"]]
            self.artist_names.append(artists)
            self.release_dates.append(tracks[i]["track"]["album"]["release_date"])

        my_tracks = pd.DataFrame(
            {
                "id": self.track_ids,
                "track_name": self.track_names,
                "release_date": self.release_dates,
                "artist_ids": self.artist_ids,
                "artist_names": self.artist_names,
                "playlist_id": playlist_id,
                "playlist_name": playlist_name,
            }
        )

        # append only new tracks
        my_current_tracks = pd.read_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_tracks.csv",
            index_col=0,
        )
        new_tracks = my_tracks[
            ~my_tracks.id.isin(list(my_current_tracks["id"]))
        ].reset_index(drop=True)
        new_tracks.to_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_tracks.csv",
            mode="a",
            header=False,
        )
        return my_tracks

    def filter_new_audio_features(self, my_tracks: pd.DataFrame) -> pd.DataFrame:
        # append only new tracks and return for audio features
        my_current_audio = pd.read_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/audio_features.csv",
            index_col=0,
        )
        filtered_track_ids = my_tracks[
            ~my_tracks.id.isin(list(my_current_audio["id"]))
        ].reset_index(drop=True)["id"]
        return filtered_track_ids

    ## This starts data transformation
    def append_new_audio_features(self, new_audio_features: pd.DataFrame) -> None:
        new_audio_features[
            "id",
            "danceability",
            "energy",
            "loudness",
            "speechiness",
            "acousticness",
            "instrumentalness",
            "liveness",
            "valence",
            "tempo",
            "duration_ms",
            "time_signature",
            "key",
            "mode",
        ].reset_index(drop=True).to_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/audio_features.csv",
            mode="a",
            header=False,
        )

        return

    def filter_new_artist_features(self, my_tracks: pd.DataFrame) -> list[str]:
        # filter artist ids if already in my_artists
        my_current_artists = pd.read_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_artists.csv",
            index_col=0,
        )
        my_current_artist_ids = list(my_current_artists["id"])
        filtered_artist_ids = set()
        for row in my_tracks.artist_ids:
            filtered_artist_ids.update(
                set(
                    [element for element in row if element not in my_current_artist_ids]
                )
            )
        return filtered_artist_ids

    def append_new_artist_features(self, new_artists: pd.DataFrame) -> None:
        # append new artists
        new_artists.columns = ["artist_id", "popularity", "genre"]
        new_artists.reset_index(drop=True).to_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_artists.csv",
            mode="a",
            header=False,
        )
        return None

    def update_spotify_features(self) -> None:
        """Request Spotify API to return dfs for my playlists."""

        # refresh access token to make new api requests is not inheriting session
        access_token = spAuth.get_access_token()
        headers = {"Authorization": "Bearer {token}".format(token=access_token[0])}
        print(headers)

        log.info(f"Loading Spotify playlists")
        for playlist_id, playlist_name in playlists.items():
            # return my playlists' track features
            tracks = spApi.request_track_features(headers, playlist_id)
            my_tracks = self.return_my_tracks(tracks, playlist_id, playlist_name)

            # update audio features
            filtered_track_ids = self.filter_new_audio_features(my_tracks)
            if len(filtered_track_ids) > 0:
                log.info(f"Updating audio features for {playlist_name}")
                new_audio_features = spApi.request_audio_features(
                    headers, filtered_track_ids
                )
                _ = self.append_new_audio_features(new_audio_features)

            # update artists features
            filtered_artist_ids = self.filter_new_artist_features(my_tracks)
            if len(filtered_track_ids) > 0:
                log.info(f"Updating artists features for {playlist_name}")
                new_artists = spApi.request_artist_features(
                    headers, filtered_artist_ids
                )
                _ = self.append_new_artist_features(new_artists)

        return my_tracks

    def merge_audio_features(self, my_tracks: pd.DataFrame) -> pd.DataFrame:
        audio_features = pd.read_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/audio_features.csv",
            index_col=0,
        )
        df = my_tracks.merge(audio_features, on="id", how="left")
        return df

    def merge_artist_features(headers, df: pd.DataFrame) -> pd.DataFrame:
        my_artists = pd.read_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_artists.csv",
            index_col=0,
        )
        my_artists["genre"].apply(lambda x: x.replace("[]", ""))

        # get artist popularity
        my_artists["popularity"] = pd.to_numeric(
            my_artists["popularity"], errors="coerce"
        )
        popu_avg = []
        for row in df.artist_ids:
            popu_avg.append(my_artists[my_artists.id.isin(row)].popularity.mean())
        df.loc[:, "popularity"] = popu_avg

        # get artist genres for this playlist
        genres = []
        for row in df.artist_ids:
            genre = my_artists[my_artists.id.isin(row)]["genre"].values
            genres.append(genre)

        df.loc[:, "genres"] = genres
        df.loc[:, "genres"] = [", ".join(map(str, l)) for l in df["genres"]]
        # df.loc[:, "first_genre"] = df.genres.str.split(",")[0].replace("[", "").replace("]", "").replace("'", "")
        df["first_genre"] = df["genres"].apply(
            lambda x: x.split(",")[0].replace("[", "").replace("]", "").replace("'", "")
        )
        df.first_genre = df.first_genre.replace("nan", np.nan)
        # search for my genres as categories
        for genre in my_genres:
            df.loc[df["genres"].str.contains(genre), "genre_cat"] = genre
        # artists.genre_cat.replace("", np.nan, inplace=True)

        return df

    def transform_cat_features(self, df: pd.DataFrame) -> pd.DataFrame:
        # Prepare other categorical variables
        df["release_date"] = pd.to_datetime(df["release_date"], format="ISO8601")
        df["year"] = df["release_date"].dt.year

        # map keys/mode to labels
        df["decade"] = df["year"].apply(lambda x: str(x)[:3] + "0s")
        keys = {
            0: "C",
            1: "Db",
            2: "D",
            3: "Eb",
            4: "E",
            5: "F",
            6: "F#",
            7: "G",
            8: "Ab",
            9: "A",
            10: "Bb",
            11: "B",
        }
        df["key"] = pd.to_numeric(df["key"], errors="coerce")
        df["key_labels"] = df["key"].map(keys)
        modes = {0: "Minor", 1: "Major"}
        df["mode"] = pd.to_numeric(df["mode"], errors="coerce")
        df["mode_labels"] = df["mode"].map(modes)
        df["key_mode"] = df["key_labels"] + " " + df["mode_labels"]

        return df

    def update_playlist_data(self, my_tracks: pd.DataFrame) -> pd.DataFrame:
        playlist_df = self.merge_audio_features(my_tracks)
        playlist_df = self.merge_artist_features(playlist_df)
        playlist_df = self.transform_cat_features(playlist_df)
        playlist_df.loc[:, "artist_ids"] = [
            ", ".join(map(str, l)) for l in playlist_df["artist_ids"]
        ]

        # save playlist data
        for _, playlist_name in playlists.items():
            playlist_df = playlist_df[
                playlist_df.playlist_name == playlist_name
            ].drop_duplicates(subset=["id"])
        playlist_df.to_csv(
            f"/Users/wiseer/Documents/github/listen-wiseer/src/data/playlists/{playlist_name}.csv"
        )

        log.info("Playlists updated successfully!")
        # TODO: verify data with schema - should it be final playlists or when requests are made :/
        # TODO: change from csv to DB;
        # TODO: add historical table of playlist tracks with column if track was deleted from the playlist (ie to filter future recommendations)
        # TODO: also tables for liked, recently listened to (API requests)

        return playlist_df
