import os
from typing import Tuple
import pandas as pd
from scipy.spatial.distance import pdist, squareform
from analysis.data import *

eda = LoadPlaylistData()


class GenreMappingENOA:
    """Performs EDA analysis on spotify playlist data."""

    def __init__(self) -> None:
        # load artefacts
        self.enoa_data = eda.enoa_data

    @staticmethod
    def return_genre_map() -> pd.DataFrame:
        gm = pd.read_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/genres/genre_map.csv",
            index_col=0,
        )
        gm.sort_values(
            ["gen_4", "gen_8", "my_genre", "sub_genre", "first_genre"]
        ).reset_index(drop=True).to_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/genres/genre_map.csv"
        )
        return gm

    # This is before genre_mapping, could reduce this using enoa
    def return_new_genres(self) -> list:
        new_genres = list(
            pd.DataFrame(
                self.enoa_data[self.enoa_data.gen_4.isnull()]
                .drop_duplicates(["artist_names"])  # genre is mapped by artist
                .groupby("playlist_name")["first_genre"]
                .value_counts()
            )
            .reset_index()
            .first_genre
        )
        return new_genres

    def return_new_genres_df(self) -> pd.DataFrame:
        # define enoa sub_genre coordinates
        genre_groups = self.enoa_data.groupby("sub_genre")[["top", "left"]].agg(
            {"min", "max"}
        )
        genre_groups.columns = genre_groups.columns.map("_".join)
        genre_groups.reset_index(inplace=True)
        self.enoa_data["enoa_subgenre_matches"] = self.enoa_data.apply(
            lambda row: self.find_group(genre_groups, row), axis=1
        )
        # get new genre matches to review
        new_genres_df = self.enoa_data[
            self.enoa_data.first_genre.isin(self.new_genres)
        ][
            [
                "playlist_name",
                "artist_names",
                "gen_4",
                "gen_8",
                "my_genre",
                "sub_genre",
                "first_genre",
                "enoa_subgenre_matches",
                "top",
                "left",
            ]
        ]
        new_genres_df.drop(
            ["gen_4", "gen_8", "my_genre", "sub_genre"], axis=1, inplace=True
        )
        return new_genres_df

    #    def create_subgenre_maps(self) -> Tuple[dict, dict]:
    #        gm = self.return_genre_map()
    #        playlist_first_genre_map = (
    #            self.df.groupby("playlist_name").first_genre.apply(set).to_dict()
    #        )
    #        enoa_sub_genre_map = gm.groupby("sub_genre").first_genre.apply(set).to_dict()
    #        return playlist_first_genre_map, enoa_sub_genre_map

    def calculate_first_genre_distances(self, vars: list[str]) -> pd.DataFrame:
        X = self.df.groupby("first_genre")[
            vars
        ].mean()  # ["top", "left"] or num_features
        distances = pdist(X.values, metric="euclidean")
        dist_matrix = squareform(distances)
        dm = pd.DataFrame(dist_matrix)
        dm.index = X.index
        dm.columns = X.index
        # sns.heatmap(dm)
        # # convert distance matrix to cosine similarity matrix
        # similarity_matrix = 1 / (1 + dm)
        # cosine_similarity_matrix = similarity_matrix @ similarity_matrix.T
        # cosine_similarity_matrix = abs(round(1 - cosine_similarity_matrix, 2))
        # sns.heatmap(cosine_similarity_matrix)
        return dm


#    def append_best_playlist_match(
#        self,
#        new_genres_df: pd.DataFrame,
#        playlist_first_genre_map: dict,
#        dm: pd.DataFrame,
#    ) -> pd.DataFrame:
#        best_playlist_match = []
#        for ind, row in new_genres_df.iterrows():
#            # Loop best match by playlist
#            playlist_row = []
#            for k, v in playlist_first_genre_map.items():
#                if row["playlist_name"] == k:
#                    new_genre = (
#                        [row["first_genre"]]
#                        if not isinstance(row["first_genre"], list)
#                        else row["first_genre"]
#                    )
#                    matched = dm[dm.columns.isin(v)]
#                    best_match = (
#                        matched[new_genre].sort_values(by=new_genre).index.tolist()
#                    )
#            playlist_row.append(best_match)
#            best_playlist_match.append(playlist_row)
#        # Assign the entire list to the DataFrame column
#        new_genres_df["best_playlist_match"] = best_playlist_match
#        new_genres_df.loc[:, "best_playlist_match"] = [
#            ", ".join(map(str, l)) for l in new_genres_df["best_playlist_match"]
#        ]
#        return new_genres_df
#
#    # return potential subgenre matches based on enoa coordinates
#    def find_group(self, genre_groups: pd.DataFrame, row) -> list:
#        conditions = (
#            (genre_groups["top_min"] <= row["top"])
#            & (row["top"] <= genre_groups["top_max"])
#            & (genre_groups["left_min"] <= row["left"])
#            & (row["left"] <= genre_groups["left_max"])
#        )
#        matched_groups = genre_groups["sub_genre"].where(conditions)
#        return matched_groups.dropna().tolist()

#    def append_best_enoa_match(
#        self,
#        new_genres_df: pd.DataFrame,
#        playlist_first_genre_map: dict,
#        enoa_sub_genre_map: dict,
#        dm: pd.DataFrame,
#    ) -> pd.DataFrame:
#        best_enoa_match = []
#        for ind, row in new_genres_df.iterrows():
#            # Loop best match by playlist
#            playlist_row = []
#            for k, v in playlist_first_genre_map.items():
#                if row["playlist_name"] == k:
#                    new_genre = (
#                        [row["first_genre"]]
#                        if not isinstance(row["first_genre"], list)
#                        else row["first_genre"]
#                    )
#                    # Map enoa sub_genre matches to first genres for that playlist
#                    if len(row["enoa_subgenre_matches"]) > 0:
#                        for sub_genre in row["enoa_subgenre_matches"]:
#                            enoa_first_genres = enoa_sub_genre_map.get(sub_genre)
#                            matched = dm[dm.columns.isin(enoa_first_genres)]
#                            best_match = (
#                                matched[new_genre]
#                                .sort_values(by=new_genre)
#                                .index.tolist()
#                            )
#            # TODO: filter playlist matches or maybe expand coordintes to catch more?
#            playlist_row.append(best_match)
#            best_enoa_match.append(playlist_row)
#        # Assign the entire list to the DataFrame column
#        new_genres_df["best_enoa_match"] = best_enoa_match
#        new_genres_df.loc[:, "best_enoa_match"] = [
#            ", ".join(map(str, l)) for l in new_genres_df["best_enoa_match"]
#        ]
#        return new_genres_df


#    def return_best_genre_matches(self) -> None:
#        # TODO: this really needs to be refactored for storing artefacts grrrr
#        # Calculate enoa distance
#        dm = self.calculate_first_genre_distances(self.enoa_data, ["top", "left"])
#        new_genres_df = self.return_new_genres_df(self.enoa_data)
#
#        # append best matches
#        # TODO: see if you can avoid loading df and save this somewhere else
#        playlist_first_genre_map, enoa_sub_genre_map = self.create_subgenre_maps(
#            df, gm
#        )
#        new_genres_df = self.append_best_playlist_match(
#            new_genres_df, playlist_first_genre_map, dm
#        )
#        new_genres_df = self.append_best_enoa_match(
#            new_genres_df, playlist_first_genre_map, enoa_sub_genre_map, dm
#        )
#        # save data to review
#        new_genres_df.to_csv(
#            "/Users/wiseer/Documents/github/listen-wiseer/src/data/genres/genre_map_review.csv"
#        )  # TODO: add date?
#        return None


#    def identify_outliers(self, df, playlists):
#        # NOTE: This function needs to be refactored!
#        outliers = set()
#        for i, playlist_name in enumerate(playlists):
#            # get outliers
#            df_sub = df[df.playlist_name == playlist_name].copy()
#            df_sub = df_sub.loc[:, num_features]
#
#            # OPTION 1: z-score filter: z-score < 3
#            lim = np.abs((df_sub - df_sub.mean()) / df_sub.std(ddof=0)) < 3
#
#            ## OPTION 2: quantile filter: discard 1% upper / lower values
#            # lim = np.logical_and(
#            #    df_sub < df_sub.quantile(0.99, numeric_only=False),
#            #    df_sub > df_sub.quantile(0.01, numeric_only=False),
#            # )
#
#            ## OPTION 3: iqr filter: within 2.22 IQR (equiv. to z-score < 3)
#            # iqr = df_sub.quantile(0.75, numeric_only=False) - df_sub.quantile(
#            #    0.25, numeric_only=False
#            # )
#            # lim = np.abs((df_sub - df_sub.median()) / iqr) < 2.22
#
#            df_sub = df_sub.where(lim, np.nan)
#            outliers.update(list(df_sub[df_sub.isnull().any(axis=1)].index))
#
#        df.loc[df.index.isin(outliers), "outliers"] = 1
#        df.outliers.fillna(0, inplace=True)
#        return df

#### Spotify Playlist EDA

## 5 | Outliers
# TODO: add method for flagging songs that don't belong in playlist; for now, send as csv for review
# df = identify_outliers(df, playlists)
# outliers_df = pd.DataFrame(
#     df[df.outliers == 1]
#     .groupby("playlist")[["id", "track_name", "artist_names", "genres"]]
#     .value_counts()
#     .reset_index()
#     .drop("count", axis=1)
# ).to_csv(f"analysis/{group}/outlier_df.csv")
#
# data = return_enoa_outliers(df)
# plot_enoa_outliers(data, playlists)
# plt.savefig(f"analysis/{group}/6_enoa_outliers.png")

## 4 | Dimensionality Reduction
# TODO: add method for splitting convulated playlist into two --> which later will be used to create new playlist and remove songs from old
# playlist = playlists[0]
# data = calculate_tsne(df, playlist)
# plot_tsne(data, playlist)
# plt.savefig(f"analysis/{group}/{playlist}/tsne_scatterplot.png")
#
# plot_tsne_groupy_by_genres(data)
# plt.savefig(f"analysis/{group}/{playlist}/tsne_by_genre.png")
#
# plot_pairplot(data, hue="tsne")
# plt.savefig(f"analysis/{group}/{playlist}/tsne_pairplot.png")

#    ### Save analysis to pdf
#    subprocess.run(
#        ["jupyter", "nbconvert", "--to", "html", "--no-input", "notebooks/eda.ipynb"]
#    )
#
#    # Convert HTML to PDF
#    current_date_str = datetime.now().strftime("%Y-%m-%d")
#    html_file_path = f"notebooks/eda.html"
#    pdf_output_path = f"analysis/output/eda_{current_date_str}.pdf"
#    pdfkit.from_file(html_file_path, pdf_output_path)
#    print(f"PDF file has been created: {pdf_output_path}")
