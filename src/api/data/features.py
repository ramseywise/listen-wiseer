

        def get_artist_ids(self):
            return [artist["artist_ids"] for artist in self.artists]

        def get_artist_names(self):
            return [artist["artist_names"] for artist in self.artists]

        def extract_artist_info(self, tracks) -> pd.DataFrame:
            artist_ids = [track.get_artist_ids() for track in tracks]
            artist_names = [track.get_artist_names() for track in tracks]
            return artist_ids, artist_names


    class ArtistFeatures:
        def __init__(self):
            self.filtered_artist_ids

        def filter_track_ids(self, tracks: pd.DataFrame) -> pd.DataFrame:
            my_current_artists = pd.read_csv(
                "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_artists.csv",
                index_col=0,
            )
            my_current_artist_ids = list(my_current_artists["id"])

            # filter artist ids if already in my_artists
            filtered_artist_ids = set()
            for row in tracks.artist_ids:
                filtered_artist_ids.update(
                    set(
                        [
                            element
                            for element in row
                            if element not in my_current_artist_ids
                        ]
                    )
                )
                return filtered_artist_ids

        def get_new_artist_data(self, headers: dict) -> pd.DataFrame:
            genres = {}
            popularity = {}
            if len(self.filtered_artist_ids) > 0:
                for artist_id in self.filtered_artist_ids:
                    for _ in range(len(artist_id)):
                        r = self._request_artist_info(headers, artist_id)
                        # sometimes queries too often and drops requests
                        if "error" in request.args:
                            continue
                        else:
                            genres.update({artist_id: r["genres"]})
                            popularity.update({artist_id: str(r["popularity"])})

            # append new artists to my_artists
            my_new_artists = pd.DataFrame([popularity, genres]).T.reset_index()
            my_new_artists.columns = ["artist_id", "popularity", "genre"]
            my_new_artists.reset_index(drop=True).to_csv(
                "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_artists.csv",
                mode="a",
                header=False,
            )
            return my_new_artists

    log.info("Preparing dataset")

    class DataTransformation:
        def __init__(self):
            self.filtered_track_ids

        def merge_audio_features(self, tracks: pd.DataFrame) -> pd.DataFrame:
            data = pd.read_csv(
                "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/audio_features.csv",
                index_col=0,
            )
            df = tracks.merge(data, on="id", how="left")
            return df

        def transform_release_year(df: pd.DataFrame) -> pd.DataFrame:
            df["release_date"] = pd.to_datetime(df["release_date"], format="ISO8601")
            df["year"] = df["release_date"].dt.year
            df["decade"] = df["year"].apply(lambda x: str(x)[:3] + "0s")
            return df

        def map_keys_to_labels(df: pd.DataFrame) -> pd.DataFrame:
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
            return df

        def map_mode_to_labels(df: pd.DataFrame) -> pd.DataFrame:
            modes = {0: "Minor", 1: "Major"}
            df["mode"] = pd.to_numeric(df["mode"], errors="coerce")
            df["mode_labels"] = df["mode"].map(modes)
            df["key_mode"] = df["key_labels"] + " " + df["mode_labels"]
            return df

        def merge_artist_features(
            self, df: pd.DataFrame, playlist_name: str
        ) -> pd.DataFrame:
            my_artists = pd.read_csv(
                "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_artists.csv",
                index_col=0,
            )

            # get artist popularity
            my_artists["popularity"] = pd.to_numeric(
                my_artists["popularity"], errors="coerce"
            )
            popu_avg = []
            for row in df.artist_ids:
                popu_avg.append(my_artists[my_artists.id.isin(row)].popularity.mean())
            df.loc[:, "popularity"] = popu_avg

            # get artist genres for this playlist
            df["genre"].apply(lambda x: x.replace("[]", ""))
            genres = []
            for row in df.artist_ids:
                genre = my_artists[my_artists.id.isin(row)]["genre"].values
                genres.append(genre)
            df.loc[:, "genres"] = genres
            df.loc[:, "genres"] = [", ".join(map(str, l)) for l in df["genres"]]
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

            # save playlist data
            df.loc[:, "artist_ids"] = [", ".join(map(str, l)) for l in df["artist_ids"]]
            df = df[df.playlist_name == playlist_name].drop_duplicates(subset=["id"])
            df.to_csv(
                "/Users/wiseer/Documents/github/listen-wiseer/src/data/playlists/"
                + playlist_name
                + ".csv"
            )
            return df
