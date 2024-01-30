import os
from typing import Tuple
import pandas as pd
from sklearn.ensemble import IsolationForest
from const import *


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

    def return_outlier_df(self, df: pd.DataFrame) -> pd.DataFrame:
        dfs = []
        model = IsolationForest(
            n_estimators=150, max_samples="auto", contamination=0.05, max_features=10
        )
        playlists = [
            item for sublist in playlist_group_dict.values() for item in sublist
        ]
        for playlist in playlists:
            df_sub = df[df.playlist_name == playlist][num_features]

            # Fit the model and obtain decision function scores
            model.fit(df_sub)
            scores = model.decision_function(df_sub)

            playlist_df = pd.DataFrame(
                {
                    "index": df_sub.index,
                    "score": scores,
                }
            )
            dfs.append(playlist_df)

            # evaluate if we have a feedback loop for labeled data
            # cm = confusion_matrix(labels, predicted_labels)
            # fpr, tpr, thresholds = roc_curve(labels, -model.decision_function(df[num_features]))
            # roc_auc = auc(fpr, tpr)

        # Concatenate DataFrames into a single DataFrame
        result_df = pd.concat(dfs, ignore_index=True)
        merged_df = pd.merge(
            df[
                [
                    "id",
                    "playlist_name",
                    "track_name",
                    "release_date",
                    "artist_names",
                    "genres",
                    "first_genre",
                    "my_genre",
                    "top",
                    "left",
                ]
            ],
            result_df,
            left_index=True,
            right_on="index",
            how="left",
        )
        merged_df.loc[merged_df.score < 0, "outliers"] = 1
        merged_df.fillna(0, inplace=True)
        return merged_df

    def create_subgenre_maps(self) -> Tuple[dict, dict]:
        gm = self.return_genre_map()
        df = self.load_playlist_data()
        playlist_first_genre_map = (
            df.groupby("playlist_name").first_genre.apply(set).to_dict()
        )
        enoa_sub_genre_map = gm.groupby("sub_genre").first_genre.apply(set).to_dict()
        return playlist_first_genre_map, enoa_sub_genre_map
