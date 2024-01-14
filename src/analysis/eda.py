import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.manifold import TSNE
from modeling.const import *
import warnings

warnings.filterwarnings("ignore", category=UserWarning)


def load_playlist_data():
    # Specify the folder containing CSV files
    folder_path = "/Users/wiseer/Documents/github/listen-wiseer/src/data/playlists"
    playlists = os.listdir(folder_path)

    # Get a list of all CSV files in the folder
    csv_files = [file for file in playlists if file.endswith(".csv")]

    # Initialize an empty DataFrame to store the concatenated data
    concatenated_df = pd.DataFrame()

    # Loop through each CSV file and concatenate its data to the DataFrame
    for csv_file in csv_files:
        playlist_name = csv_file.split(".csv")[0]
        file_path = os.path.join(folder_path, csv_file)
        df = pd.read_csv(file_path, index_col=0)
        df["playlist"] = playlist_name
        concatenated_df = pd.concat([concatenated_df, df], ignore_index=True)
    df = concatenated_df.copy()

    return df


def boxplot_playlist_by_decade(df):
    order = [
        "1920s",
        "1930s",
        "1940s",
        "1950s",
        "1960s",
        "1970s",
        "1980s",
        "1990s",
        "2000s",
        "2010s",
        "2020s",
    ]

    sns.boxplot(
        x="decade",
        y="popularity",
        hue="playlist",
        data=df[["playlist", "decade", "popularity"]].dropna(),
        order=[x for x in order if x in set(df.decade)],
    )


def plot_pairplot(df, hue):
    sns.pairplot(
        df.drop_duplicates(subset=["track_name"]).reset_index(drop=True)[
            [
                "danceability",
                "energy",
                "loudness",
                "speechiness",
                "acousticness",
                "instrumentalness",
                "liveness",
                "valence",
                "tempo",
                "popularity",
                hue,
            ]
        ],
        hue=hue,
    )


def plot_barplot(df, x, y):
    songs = pd.DataFrame(
        df[[x, y]].sort_values(by=x, ascending=False).groupby(y)[x].mean()
    ).reset_index()
    plt.figure(figsize=(12, 10))
    sns.barplot(
        x=x,
        y=y,
        hue=y,
        legend=False,
        data=songs.sample(30).sort_values(by=x),
        palette=sns.color_palette("viridis", n_colors=30),
    )
    plt.title("Average Popularity by Artist")


def plot_genres_by_playlist(df, playlists):
    plt.figure(figsize=(10, 12))
    # not really any crossover with bachata
    for playlist in playlists:
        df_counts = (
            df[df.playlist == playlist]
            .groupby(["first_genre"])
            .size()
            .reset_index(name="Count")
        )
        sns.barplot(x="Count", y="first_genre", data=df_counts, orient="h")


def plot_pairplot_by_first_genre(df, playlists, group):
    for playlist in playlists:
        top_genres = set()
        data = df[df.playlist == playlist]
        top_genres.update(list(data.first_genre.value_counts()[:10].index))
        plot_pairplot(data, hue="first_genre")
        plt.savefig(f"analysis/{group}/{playlist}/pairplot_by_genre.png")


def identify_outliers(df, playlists):
    outliers = set()
    for i, playlist in enumerate(playlists):
        # get outliers
        df_sub = df[df.playlist == playlist].copy()
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


def return_enoa_outliers(df):
    # load genre coordinates
    gm = pd.read_csv(
        "/Users/wiseer/Documents/github/listen-wiseer/src/data/genres/genre_xy.csv",
        index_col=0,
    )
    # merge genre coordinates
    data = df.rename(columns={"genre": "first_genre"})
    data = data.merge(gm, on="first_genre")
    return data


def plot_enoa_outliers(data, playlists):
    if len(playlists) < 4:
        fig, axes = plt.subplots(nrows=1, ncols=3, figsize=(12, 4))
        axes = axes.flatten()
    else:
        fig, axes = plt.subplots(nrows=2, ncols=3, figsize=(12, 6))
        axes = axes.flatten()

    for i, playlist in enumerate(playlists):
        sns.scatterplot(
            x="top",
            y="left",
            hue="outliers",
            data=data[data["playlist"] == playlist].copy(),
            ax=axes[i],
        )
        axes[i].set_title(f"{playlist} genre outliers")
        plt.tight_layout()


def calculate_tsne(df, playlist):
    data = df[df["playlist"] == playlist].copy()
    data.dropna(subset=num_features, inplace=True)
    tsne = TSNE(n_components=2, random_state=0)
    X_tsne = tsne.fit_transform(data[num_features])

    # group
    data["X_tsne"] = X_tsne[:, 0]
    data["y_tsne"] = X_tsne[:, 1]
    data.loc[data["X_tsne"] < 0, "tsne"] = 1
    data.loc[data["X_tsne"] >= 0, "tsne"] = 2
    return data


def plot_tsne(data, playlist):
    sns.scatterplot(x="X_tsne", y="y_tsne", hue="tsne", data=data, palette="viridis")
    plt.title(f"{playlist} t-SNE Plot")
    return plt.show()


def plot_tsne_groupy_by_genres(data):
    plt.figure(figsize=(10, 8))
    df_counts = (
        data[data.X_tsne < 0].groupby(["first_genre"]).size().reset_index(name="Count")
    )
    sns.barplot(x="Count", y="first_genre", data=df_counts, orient="h")
    df_counts = (
        data[data.X_tsne >= 0].groupby(["first_genre"]).size().reset_index(name="Count")
    )
    sns.barplot(x="Count", y="first_genre", data=df_counts, orient="h")
    return plt.show()


# def calculate_genre_distances(df):
#     matrix = pd.read_csv(
#         "/Users/wiseer/Documents/github/listen-wiseer/src/data/genres/genre_matrix.csv",
#         index_col=0,
#     )
#
#     matrix = matrix[matrix.index.isin(set(df.first_genre))]
#     matrix = matrix[list(matrix.index)]
#     matrix = matrix.fillna(0)
#     return matrix
#
#
# def convert_to_similarity_matrix(matrix):
#     # Step 1: Convert distance matrix to similarity matrix
#     similarity_matrix = 1 / (1 + matrix)
#
#     # Step 2: Normalize similarity matrix (optional, but recommended)
#     normalized_similarity_matrix = (
#         similarity_matrix / np.linalg.norm(similarity_matrix, axis=1)[:, np.newaxis]
#     )
#     # Step 3: Compute cosine similarity matrix
#     cosine_similarity_matrix = (
#         normalized_similarity_matrix @ normalized_similarity_matrix.T
#     )
#     cosine_similarity_matrix = abs(round(1 - cosine_similarity_matrix, 2))
#     return cosine_similarity_matrix


### plot scatter sublots
# fig, axes = plt.subplots(nrows=1, ncols=3, figsize=(12, 4))
# axes = axes.flatten()
#
# for i, playlist in enumerate(["zoukini", "kizombamama", "¡zapatos! ¡zapatos!"]):
#     sns.scatterplot(
#         x="energy",
#         y="valence",
#         hue="mode_labels",
#         data=df[df["playlist_name"] == playlist],
#         ax=axes[i],
#     )
#     axes[i].set_title(f"{playlist} feature interactions")
#     plt.tight_layout()

# tracks = []
# for i, playlist in enumerate(["zoukini", "kizombamama", "¡zapatos! ¡zapatos!"]):
#     tracks.append(
#         df[((df.playlist == playlist) & (df.instrumentalness > 0.01))].track_name.values
#     )
# tracks


# sns.lmplot(x="Loudness", y="Energy", hue="faves", data=df[features])


### plot dendrogram
# from scipy.cluster import hierarchy
# from scipy.spatial.distance import squareform
#
# linkage_matrix = hierarchy.linkage(
#     squareform(cosine_similarity_matrix), method="average"
# )
# dendrogram = hierarchy.dendrogram(
#     linkage_matrix,
#     labels=cosine_similarity_matrix.index,
#     orientation="left",
#     color_threshold=0.5,
# )
