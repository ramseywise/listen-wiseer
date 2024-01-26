import os
import pandas as pd
from modeling.utils.const import *


class LoadPlaylistData:
    """Loads and merges playlist data with ENOA."""

    def return_genre_map(self) -> pd.DataFrame:
        gm = pd.read_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/genres/genre_map.csv",
            index_col=0,
        )
        gm = gm.sort_values(
            ["gen_4", "gen_8", "my_genre", "sub_genre", "first_genre"]
        ).reset_index(drop=True)
        gm.to_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/genres/genre_map.csv"
        )
        return gm

    def load_playlist_data(self) -> pd.DataFrame:
        folder_path = "/Users/wiseer/Documents/github/listen-wiseer/src/data/playlists"
        playlists = os.listdir(folder_path)
        csv_files = [file for file in playlists if file.endswith(".csv")]

        # concat dfs
        concatenated_df = pd.DataFrame()
        for csv_file in csv_files:
            file_path = os.path.join(folder_path, csv_file)
            df = pd.read_csv(file_path, index_col=0)
            concatenated_df = pd.concat([concatenated_df, df], ignore_index=True)
        df = concatenated_df.copy()
        return df

    def return_enoa_data(self) -> pd.DataFrame:
        # first merge my genre mappping
        gm = self.return_genre_map()
        df = self.load_playlist_data()
        mapped_df = df.merge(gm, on="first_genre", how="left")

        # merge with enoa genre coordinates
        enoa_xy = pd.read_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/genres/genre_xy.csv",
            index_col=0,
        )
        mapped_df = mapped_df.rename(columns={"genre": "first_genre"})
        enoa_data = mapped_df.merge(enoa_xy, on="first_genre")
        enoa_data.to_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/enoa.csv",
        )
        return enoa_data
