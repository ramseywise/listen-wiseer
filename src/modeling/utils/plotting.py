import os
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from sklearn.manifold import TSNE
from modeling.utils.const import *
import warnings

warnings.filterwarnings("ignore", category=UserWarning)


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


def boxplot_playlist_by_decade(df):
    # NOTE: should subplots be done on a loop?
    # plot scatter sublots
    fig, axes = plt.subplots(nrows=2, ncols=2, figsize=(14, 8))
    axes = axes.flatten()

    for i, (k, v) in enumerate(playlist_group_dict.items()):
        data = df[df.playlist_name.isin(v)]
        sns.boxplot(
            x="decade",
            y="popularity",
            hue="playlist_name",
            data=data[["playlist_name", "decade", "popularity"]].dropna(),
            order=[x for x in order if x in set(df.decade)],
            ax=axes[i],
        )
        axes[i].set_title(f"{k} popularity by decade")
    plt.tight_layout()
    plt.suptitle("Decade Popularity by Playlist Group")


def plot_playlist_artist_popularity(df):
    fig, axes = plt.subplots(nrows=2, ncols=2, figsize=(14, 6))
    axes = axes.flatten()

    for i, (k, v) in enumerate(playlist_group_dict.items()):
        data = df[df.playlist_name.isin(v)]
        songs = pd.DataFrame(
            data[["artist_names", "popularity"]]
            .groupby("artist_names")["popularity"]
            .mean()
        ).reset_index()
        sns.barplot(
            x="popularity",
            y="artist_names",
            hue="popularity",
            legend=False,
            data=songs.sample(20).sort_values(by="popularity"),
            palette=sns.color_palette("viridis", n_colors=30),
            ax=axes[i],
        )
        axes[i].set_title(f"{k} artists popularity")
    plt.tight_layout()
    # plt.suptitle("Artist Popularity by Playlist Group")


# def plot_barplot(df, x, y):
#     songs = pd.DataFrame(
#         df[[x, y]].sort_values(by=x, ascending=False).groupby(y)[x].mean()
#     ).reset_index()
#     plt.figure(figsize=(12, 10))
#     sns.barplot(
#         x=x,
#         y=y,
#         hue=y,
#         legend=False,
#         data=songs.sample(30).sort_values(by=x),
#         palette=sns.color_palette("viridis", n_colors=30),
#     )
#     plt.title("Average Popularity by Artist")


# def plot_genres_by_playlist(df, playlists):
#     plt.figure(figsize=(10, 12))
#     # not really any crossover with bachata
#     for playlist_name in playlists:
#         df_counts = (
#             df[df.playlist_name == playlist_name]
#             .groupby(["first_genre"])
#             .size()
#             .reset_index(name="Count")
#         )
#         sns.barplot(x="Count", y="first_genre", data=df_counts, orient="h")


def plot_my_genre_by_playlist_group(df, playlist_group_dict, order=None):
    fig, axes = plt.subplots(nrows=2, ncols=2, figsize=(14, 8))
    axes = axes.flatten()

    df_counts = pd.DataFrame(
        df.groupby(["playlist_name", "my_genre"]).sub_genre.value_counts()
    ).reset_index()

    for i, (group, playlists) in enumerate(playlist_group_dict.items()):
        palette = dict(zip(playlists, sns.color_palette()))
        plot_df = df_counts[df_counts["playlist_name"].isin(playlists)]

        sns.barplot(
            x="count",
            y="my_genre",
            data=plot_df,
            hue="playlist_name",
            palette=palette,
            orient="h",
            ax=axes[i],
        )
        handles, labels = axes[i].get_legend_handles_labels()
        axes[i].legend(handles[: len(playlists)], labels[: len(playlists)])
        axes[i].set_title(f"{group} playlist genres")
    plt.tight_layout()
    plt.suptitle("My Genres by Playlist Group")


def plot_enao_new_genres(data, new_genres, group):
    # sub_genres = set(data.sub_genre.values)
    new_data = data[data.first_genre.isin(new_genres)]
    new_data_first_genre = new_data.first_genre.values

    # plot new genres
    plt.figure(figsize=(14, 10))
    sns.scatterplot(data=new_data, x="top", y="left", color="gray", s=200)
    for label, xi, yi in zip(new_data_first_genre, new_data.top, new_data.left):
        plt.annotate(
            label, (xi, yi), textcoords="offset points", xytext=(0, 5), ha="center"
        )

    # plot my genres
    sns.scatterplot(
        data=data,
        x="top",
        y="left",
        hue=group,
        # legend=None,
    )
    # Shade the area around each group
    hue_palette = sns.color_palette("husl", n_colors=len(data[group].unique()))
    for category in data[group].unique():
        group_data = data[data[group] == category]

        # Get the index of the current category in the unique hue values
        hue_index = data[group].unique().tolist().index(category)
        if hue_index < len(hue_palette):
            hue_color = hue_palette[hue_index]
            sns.kdeplot(
                x=group_data["top"],
                y=group_data["left"],
                color=hue_color,
                fill=True,
                levels=2,
                alpha=0.3,
            )
    plt.title("New genres by ENOA coordinates")


# def plot_enoa_outliers(data, playlists):
#     if len(playlists) < 4:
#         fig, axes = plt.subplots(nrows=1, ncols=3, figsize=(12, 4))
#         axes = axes.flatten()
#     else:
#         fig, axes = plt.subplots(nrows=2, ncols=3, figsize=(12, 6))
#         axes = axes.flatten()
#
#     for i, playlist in enumerate(playlists):
#         sns.scatterplot(
#             x="top",
#             y="left",
#             hue="outliers",
#             data=data[data["playlist"] == playlist].copy(),
#             ax=axes[i],
#         )
#         axes[i].set_title(f"{playlist} genre outliers")
#         plt.tight_layout()


def plot_enoa_area(genre_groups):
    plt.figure(figsize=(16, 14))
    colors = sns.color_palette("husl", n_colors=len(genre_groups))

    for idx, (index, row) in enumerate(genre_groups.iterrows()):
        color = colors[idx]

        # Plot rectangles for the shaded area
        rect = Rectangle(
            (row["top_min"], row["left_min"]),
            row["top_max"] - row["top_min"],
            row["left_max"] - row["left_min"],
            edgecolor=color,
            facecolor=color,
            alpha=0.3,
        )
        plt.gca().add_patch(rect)

        # Plot the minimum and maximum values
        plt.scatter(
            row["top_min"],
            row["left_min"],
            label=f"{index} Min",
            color=color,
            marker="o",
            s=50,
        )
        plt.scatter(
            row["top_max"],
            row["left_max"],
            label=f"{index} Max",
            color=color,
            marker="o",
            s=50,
        )

        # Annotate with the group index
        plt.annotate(
            index,
            (
                (row["top_min"] + row["top_max"]) / 2,
                (row["left_min"] + row["left_max"]) / 2,
            ),
            color=color,
            ha="center",
            va="center",
            fontsize=30,
            fontweight="bold",
        )
    plt.xlabel("Top")
    plt.ylabel("Left")
    plt.title("My genres by ENOA coordinates")


def plot_new_genres(genre_groups, data, new_genres, hue):
    plt.figure(figsize=(16, 14))
    colors = sns.color_palette("husl", n_colors=len(genre_groups))
    genre_groups.reset_index(inplace=True)
    for idx, (index, row) in enumerate(genre_groups.iterrows()):
        color = colors[idx]
        # Plot rectangles for the shaded area
        rect = Rectangle(
            (row["top_min"], row["left_min"]),
            row["top_max"] - row["top_min"],
            row["left_max"] - row["left_min"],
            edgecolor=color,
            facecolor=color,
            alpha=0.3,
        )
        plt.gca().add_patch(rect)
        # Plot the minimum and maximum values
        plt.scatter(
            row["top_min"],
            row["left_min"],
            label=f"{index} Min",
            color=color,
            marker="o",
            s=50,
        )
        plt.scatter(
            row["top_max"],
            row["left_max"],
            label=f"{index} Max",
            color=color,
            marker="o",
            s=50,
        )
        # Annotate with the group index
        plt.annotate(
            row[hue],
            (
                (row["top_min"] + row["top_max"]) / 2,
                (row["left_min"] + row["left_max"]) / 2,
            ),
            color=color,
            ha="center",
            va="center",
            fontsize=30,
            fontweight="bold",
        )

    # plot new genres
    new_data = data[data.first_genre.isin(new_genres)]
    new_data_first_genre = new_data.first_genre.values

    sns.scatterplot(data=new_data, x="top", y="left", color="gray", s=200)
    for label, xi, yi in zip(new_data_first_genre, new_data.top, new_data.left):
        plt.annotate(
            label, (xi, yi), textcoords="offset points", xytext=(0, 5), ha="center"
        )
    plt.legend().set_visible(False)
    plt.show()


# def calculate_tsne(df, playlist):
#     data = df[df["playlist"] == playlist].copy()
#     data.dropna(subset=num_features, inplace=True)
#     tsne = TSNE(n_components=2, random_state=0)
#     X_tsne = tsne.fit_transform(data[num_features])
#
#     # group
#     data["X_tsne"] = X_tsne[:, 0]
#     data["y_tsne"] = X_tsne[:, 1]
#     data.loc[data["X_tsne"] < 0, "tsne"] = 1
#     data.loc[data["X_tsne"] >= 0, "tsne"] = 2
#     return data
#
#
# def plot_tsne(data, playlist):
#     sns.scatterplot(x="X_tsne", y="y_tsne", hue="tsne", data=data, palette="viridis")
#     plt.title(f"{playlist} t-SNE Plot")
#     return plt.show()
#     # plt.savefig(f"analysis/{group}/{playlist}/pairplot_by_genre.png")
#     # TODO: update these if we want to save it here
#
#
# def plot_tsne_groupy_by_genres(data):
#     plt.figure(figsize=(10, 8))
#     df_counts = (
#         data[data.X_tsne < 0].groupby(["first_genre"]).size().reset_index(name="Count")
#     )
#     sns.barplot(x="Count", y="first_genre", data=df_counts, orient="h")
#     df_counts = (
#         data[data.X_tsne >= 0].groupby(["first_genre"]).size().reset_index(name="Count")
#     )
#     sns.barplot(x="Count", y="first_genre", data=df_counts, orient="h")
#     return plt.show()


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
