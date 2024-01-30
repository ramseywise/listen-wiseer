import logger
import numpy as np
import pandas as pd

# from pydantic import BaseModel
from const import *
from api.spotify_client import *

log = logger.get_logger("app")

spAuth = SpotifyAuth(client_id, client_secret, redirect_uri, token_url)
spApi = SpotifyPlaylistApi()

# TODO: add schema to validate playlist df
# from api.data.schema import *


# import data schema to validate playlist data
# data_schema = PlaylistFeaturesSchema()
# data_schema.context = {
#    "artist_schema": ArtistFeaturesSchema(),
#    "audio_schema": AudioFeaturesSchema(),
#    "track_schema": TrackFeaturesSchema(),
# }


class SpotifyTrackFeatures:
    """Transforms JSON data from Spotify API to dataframe."""

    def __init__(self) -> pd.DataFrame:
        self.my_tracks = pd.DataFrame(
            columns=[
                "id",
                "track_name",
                "release_date",
                "artist_ids",
                "artist_names",
                "playlist_id",
                "playlist_name",
            ]
        )

    @staticmethod
    def load_artefact(table: str) -> pd.DataFrame:
        df = pd.read_csv(
            f"/Users/wiseer/Documents/github/listen-wiseer/src/data/api/{table}.csv",
            index_col=0,
        )
        return df

    def return_my_tracks(
        self, tracks: dict, playlist_id: str, playlist_name: str
    ) -> pd.DataFrame:
        for track in tracks:
            self.my_tracks.loc[len(self.my_tracks)] = {
                "id": track["track"]["id"],
                "track_name": track["track"]["name"],
                "artist_ids": [artist["id"] for artist in track["track"]["artists"]],
                "artist_names": [
                    artist["name"] for artist in track["track"]["artists"]
                ],
                "release_date": track["track"]["album"]["release_date"],
                "playlist_id": playlist_id,
                "playlist_name": playlist_name,
            }

        #tracks_df = self.load_artefact("tracks")
        # new_tracks = self.my_tracks[~self.my_tracks.id.isin(set(tracks_df["id"]))]
        self.my_tracks.to_csv(
            f"/Users/wiseer/Documents/github/listen-wiseer/src/data/api/tracks.csv",
            header=False,
        )
        return self.my_tracks

    def filter_new_audio_features(self) -> list[str]:
        audio_features_df = self.load_artefact("audio_features")
        filtered_ids = [
            x for x in self.my_tracks["id"] if x not in list(audio_features_df["id"])
        ]
        return filtered_ids

    def filter_new_artist_features(self) -> list[str]:
        # filter artist ids if already in my_artists
        my_current_artists = self.load_artefact("artists")
        filtered_artist_ids = set()
        for row in self.my_tracks["artist_ids"]:
            filtered_artist_ids.update(
                [x for x in row if x not in list(my_current_artists["artist_id"])]
            )
        return filtered_artist_ids

    def update_spotify_features(self) -> None:
        """Request Spotify API to return dfs for my playlists."""

        # refresh access token to make new api requests is not inheriting session
        access_token = spAuth.get_access_token()
        headers = {"Authorization": "Bearer {token}".format(token=access_token[0])}
        print(headers)

        log.info(f"Loading Spotify playlists")
        for playlist_id, playlist_name in playlists.items():
            tracks = spApi.request_track_features(headers, playlist_id)
            self.return_my_tracks(tracks, playlist_id, playlist_name)

        # update audio features
        filtered_ids = self.filter_new_audio_features()
        if len(filtered_ids) > 0:
            log.info(f"Updating audio features")
            new_audio_features = spApi.request_audio_features(headers, filtered_ids)
            new_audio_features = new_audio_features.loc[
                :, audio_features_list
            ].reset_index(drop=True)
            new_audio_features.to_csv(
                f"/Users/wiseer/Documents/github/listen-wiseer/src/data/api/audio_features.csv",
                mode="a",
                header=False,
            )
            # TODO: assert that len(audio_features) = len(my_tracks)

        # update artists features
        filtered_artist_ids = self.filter_new_artist_features()
        if len(filtered_artist_ids) > 0:
            log.info(f"Updating artists features")
            print(filtered_artist_ids)
            new_artists = spApi.request_artist_features(headers, filtered_artist_ids)
            new_artists.columns = ["artist_id", "popularity", "genre"]
            new_artists = new_artists.reset_index(drop=True)
            new_artists.to_csv(
                f"/Users/wiseer/Documents/github/listen-wiseer/src/data/api/artists.csv",
                mode="a",
                header=False,
            )
        return None

    def merge_audio_features(
        self, playlist_df: pd.DataFrame, audio_features_df: pd.DataFrame
    ) -> pd.DataFrame:
        df = playlist_df.merge(audio_features_df, on="id", how="left")
        return df

    def merge_artist_features(
        headers, df: pd.DataFrame, my_artists: pd.DataFrame
    ) -> pd.DataFrame:
        my_artists["genre"].apply(lambda x: x.replace("[]", ""))

        # get artist popularity
        my_artists["popularity"] = pd.to_numeric(
            my_artists["popularity"], errors="coerce"
        )
        popu_avg = []
        for row in df.artist_ids:
            popu_avg.append(
                my_artists[my_artists.artist_id.isin(row)].popularity.mean()
            )
        df.loc[:, "popularity"] = popu_avg

        # get artist genres for this playlist
        genres = []
        for row in df.artist_ids:
            genre = my_artists[my_artists.artist_id.isin(row)]["genre"].values
            genres.append(genre)

        df.loc[:, "genres"] = genres
        df.loc[:, "genres"] = [", ".join(map(str, l)) for l in df["genres"]]
        df["first_genre"] = df["genres"].apply(
            lambda x: x.split(",")[0].replace("[", "").replace("]", "").replace("'", "")
        )
        df["first_genre"] = df["first_genre"].replace("nan", np.nan)

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

    def update_playlist_data(self) -> None:
        log.info(f"Preparing Spotify playlists")
        audio_features_df = self.load_artefact("audio_features")
        my_artists = self.load_artefact("artists")
        # save playlist data
        for _, playlist_name in playlists.items():
            playlist_df = self.my_tracks[
                self.my_tracks["playlist_name"] == playlist_name
            ]
            playlist_df = self.merge_audio_features(playlist_df, audio_features_df)
            playlist_df = self.merge_artist_features(playlist_df, my_artists)
            playlist_df = self.transform_cat_features(playlist_df)
            playlist_df.loc[:, "artist_ids"] = [
                ", ".join(map(str, l)) for l in playlist_df["artist_ids"]
            ]
            playlist_df.to_csv(
                f"/Users/wiseer/Documents/github/listen-wiseer/src/data/playlists/{playlist_name}.csv"
            )

        log.info("Playlists updated successfully!")
        # TODO: verify data with schema - should it be final playlists or when requests are made :/
        # TODO: change from csv to DB;
        # TODO: add historical table of playlist tracks with column if track was deleted from the playlist (ie to filter future recommendations)
        # TODO: also tables for liked, recently listened to (API requests)

        return None
