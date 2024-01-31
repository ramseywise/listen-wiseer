import numpy as np
import pandas as pd
from const import *
from scipy.spatial.distance import pdist, squareform


# genre mapping functions
def calculate_first_genre_distances(df: pd.DataFrame, vars: list[str]) -> pd.DataFrame:
    X = df.groupby("first_genre")[vars].mean()  # ["top", "left"] or num_features
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


def return_genre_map() -> pd.DataFrame:
    gm = pd.read_csv(
        "/Users/wiseer/Documents/github/listen-wiseer/src/data/genres/genre_map.csv",
        index_col=0,
    )
    gm.sort_values(
        ["gen_4", "gen_6", "gen_8", "my_genre", "sub_genre", "first_genre"]
    ).reset_index(drop=True).to_csv(
        "/Users/wiseer/Documents/github/listen-wiseer/src/data/genres/genre_map.csv"
    )
    return gm


# return potential subgenre matches based on enoa coordinates
def find_group(genre_groups: pd.DataFrame, row) -> list:
    conditions = (
        (genre_groups["top_min"] <= row["top"])
        & (row["top"] <= genre_groups["top_max"])
        & (genre_groups["left_min"] <= row["left"])
        & (row["left"] <= genre_groups["left_max"])
    )
    matched_groups = genre_groups["sub_genre"].where(conditions)
    return matched_groups.dropna().tolist()


def return_new_genres_df(df: pd.DataFrame) -> pd.DataFrame:
    new_genres_list = set(df[df.gen_4.isnull()]["first_genre"])
    # define enoa sub_genre coordinates
    genre_groups = df.groupby("sub_genre")[["top", "left"]].agg({"min", "max"})
    genre_groups.columns = genre_groups.columns.map("_".join)
    genre_groups.reset_index(inplace=True)
    df["enoa_subgenre_matches"] = df.apply(
        lambda row: find_group(genre_groups, row), axis=1
    )
    # get new genre matches to review
    new_genres_df = df[df.first_genre.isin(new_genres_list)][
        [
            "playlist_name",
            "artist_names",
            "gen_4",
            "gen_6",
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
        ["gen_4", "gen_6", "gen_8", "my_genre", "sub_genre"], axis=1, inplace=True
    )
    return new_genres_df


def append_best_playlist_match(
    new_genres_df: pd.DataFrame,
    playlist_first_genre_map: dict,
    dm: pd.DataFrame,
) -> pd.DataFrame:
    best_playlist_match = []
    for ind, row in new_genres_df.iterrows():
        # Loop best match by playlist
        playlist_row = []
        for k, v in playlist_first_genre_map.items():
            if row["playlist_name"] == k:
                new_genre = (
                    [row["first_genre"]]
                    if not isinstance(row["first_genre"], list)
                    else row["first_genre"]
                )
                matched = dm[dm.columns.isin(v)]
                best_match = matched[new_genre].sort_values(by=new_genre).index.tolist()
        playlist_row.append(best_match)
        best_playlist_match.append(playlist_row)
    # Assign the entire list to the DataFrame column
    new_genres_df["best_playlist_match"] = best_playlist_match
    new_genres_df.loc[:, "best_playlist_match"] = [
        ", ".join(map(str, l)) for l in new_genres_df["best_playlist_match"]
    ]
    return new_genres_df


def append_best_enoa_match(
    new_genres_df: pd.DataFrame,
    playlist_first_genre_map: dict,
    enoa_sub_genre_map: dict,
    dm: pd.DataFrame,
) -> pd.DataFrame:
    best_enoa_match = []
    for ind, row in new_genres_df.iterrows():
        # Loop best match by playlist
        playlist_row = []
        for k, v in playlist_first_genre_map.items():
            if row["playlist_name"] == k:
                new_genre = (
                    [row["first_genre"]]
                    if not isinstance(row["first_genre"], list)
                    else row["first_genre"]
                )
                # Map enoa sub_genre matches to first genres for that playlist
                if len(row["enoa_subgenre_matches"]) > 0:
                    for sub_genre in row["enoa_subgenre_matches"]:
                        enoa_first_genres = enoa_sub_genre_map.get(sub_genre)
                        matched = dm[dm.columns.isin(enoa_first_genres)]
                        best_match = (
                            matched[new_genre].sort_values(by=new_genre).index.tolist()
                        )
        # TODO: filter playlist matches or maybe expand coordintes to catch more?
        playlist_row.append(best_match)
        best_enoa_match.append(playlist_row)
    # Assign the entire list to the DataFrame column
    new_genres_df["best_enoa_match"] = best_enoa_match
    new_genres_df.loc[:, "best_enoa_match"] = [
        ", ".join(map(str, l)) for l in new_genres_df["best_enoa_match"]
    ]
    return new_genres_df


def return_best_genre_matches(
    df: pd.DataFrame, playlist_first_genre_map: dict, enoa_sub_genre_map: dict) -> None:
    # Calculate enoa distance
    dm = calculate_first_genre_distances(df, ["top", "left"])
    new_genres_df = return_new_genres_df(df)

    # append best matches
    # TODO: see if you can avoid loading df and save this somewhere else
    new_genres_df = append_best_playlist_match(
        new_genres_df, playlist_first_genre_map, dm
    )
    new_genres_df = append_best_enoa_match(
        new_genres_df, playlist_first_genre_map, enoa_sub_genre_map, dm
    )
    # save data to review
    new_genres_df.to_csv(
        "/Users/wiseer/Documents/github/listen-wiseer/src/data/genres/genre_map_review.csv"
    )  # TODO: add date?
    return None


def identify_outliers(df, playlists):
    outliers = set()
    for i, playlist_name in enumerate(playlists):
        # get outliers
        df_sub = df[df.playlist_name == playlist_name].copy()
        df_sub = df_sub.loc[:, num_features]

        # OPTION 1: z-score filter: z-score < 3
        lim = np.abs((df_sub - df_sub.mean()) / df_sub.std(ddof=0)) < 3

        ## OPTION 2: quantile filter: discard 1% upper / lower values
        # lim = np.logical_and(
        #    df_sub < df_sub.quantile(0.99, numeric_only=False),
        #    df_sub > df_sub.quantile(0.01, numeric_only=False),
        # )

        ## OPTION 3: iqr filter: within 2.22 IQR (equiv. to z-score < 3)
        # iqr = df_sub.quantile(0.75, numeric_only=False) - df_sub.quantile(
        #    0.25, numeric_only=False
        # )
        # lim = np.abs((df_sub - df_sub.median()) / iqr) < 2.22

        df_sub = df_sub.where(lim, np.nan)
        outliers.update(list(df_sub[df_sub.isnull().any(axis=1)].index))

    df.loc[df.index.isin(outliers), "outliers"] = 1
    df.outliers.fillna(0, inplace=True)
    return df
