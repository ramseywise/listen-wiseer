import numpy as np
import pandas as pd

# from pydantic import BaseModel
from modeling.utils.const import *
from api.data.schema import *

# import data schema to validate playlist data
# data_schema = PlaylistFeaturesSchema()
# data_schema.context = {
#    "artist_schema": ArtistFeaturesSchema(),
#    "audio_schema": AudioFeaturesSchema(),
#    "track_schema": TrackFeaturesSchema(),
# }


class SpotifyPlaylistData:
    """Transforms JSON data from Spotify API to dataframe."""

    def __init__(self) -> None:
        super().__init__()

    track_ids: list
    track_uris: list
    track_names: list
    release_date: list
    artist_ids: list
    artist_names: list
    new_tracks: pd.DataFrame

    def __init__(self):
        self.track_ids = []
        self.track_uris = []
        self.track_names = []
        self.release_dates = []
        self.artist_ids = []
        self.artist_names = []
        self.new_tracks = []

    def return_my_tracks(
        self, tracks, playlist_id: str, playlist_name: str
    ):
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
        my_current_audio = pd.read_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_tracks.csv",
            index_col=0,
        )
        new_tracks = my_tracks[
            ~my_tracks.id.isin(list(my_current_audio["id"]))
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

    def filter_new_artist_features(self, headers, my_tracks):
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





    ## This starts data transformation
    def merge_new_features(
        self,
        new_tracks: pd.DataFrame,
        my_artists: pd.DataFrame,
        audio_features: pd.DataFrame,
    ) -> pd.DataFrame:
        audio_features[
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

        df = self.new_tracks.merge(audio_features, on="id", how="left")

        return df

        def merge_artist_features(headers, df):
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
                lambda x: x.split(",")[0]
                .replace("[", "")
                .replace("]", "")
                .replace("'", "")
            )
            df.first_genre = df.first_genre.replace("nan", np.nan)
            # search for my genres as categories
            for genre in my_genres:
                df.loc[df["genres"].str.contains(genre), "genre_cat"] = genre
            # artists.genre_cat.replace("", np.nan, inplace=True)

            return df

    def transform_cat_features():
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

    def return_full_playlist_df(headers, playlist_id, playlist_name):
        df = return_track_features(headers, playlist_id, playlist_name)
        df = merge_artist_features(headers, df)

        # save playlist data
        df.loc[:, "artist_ids"] = [", ".join(map(str, l)) for l in df["artist_ids"]]
        df = df[df.playlist_name == playlist_name].drop_duplicates(subset=["id"])
        df.to_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/playlists/"
            + playlist_name
            + ".csv"
        )

        return df
