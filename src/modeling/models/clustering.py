import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from scipy.cluster.hierarchy import dendrogram, linkage
from sklearn.manifold import TSNE
from sklearn.decomposition import PCA
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler
from sklearn.cluster import KMeans, SpectralClustering
from sklearn.metrics import silhouette_score, calinski_harabasz_score
from yellowbrick.cluster import KElbowVisualizer
from yellowbrick.cluster import SilhouetteVisualizer
from const import *


def plot_genres_dendrogram(df):
    # group songs by genre
    df = df[~df.genres.isnull()]
    genres = df.groupby("genres")[num_features].mean()
    linkage_matrix = linkage(genres[num_features], "ward")

    # plot figure
    plt.figure(figsize=(14, 8))
    dendrogram(linkage_matrix, truncate_mode="lastp", p=20)
    return plt.show()


def select_pca_n_components(X):
    pca = PCA().fit(X)  # TODO: fit to pipeline
    y = np.cumsum(pca.explained_variance_ratio_)

    # Plot the explained variance ratio and cumulative explained variance
    explained_variance_ratio = pca.explained_variance_ratio_
    cumulative_explained_variance = np.cumsum(explained_variance_ratio)

    # Plot explained variance ratio
    plt.figure(figsize=(10, 4))

    plt.subplot(1, 2, 1)
    plt.bar(
        range(1, len(explained_variance_ratio) + 1),
        explained_variance_ratio,
        alpha=0.8,
        align="center",
    )
    plt.xlabel("Number of Components")
    plt.ylabel("Explained Variance Ratio")
    plt.title("Explained Variance Ratio per Component")

    # Plot cumulative explained variance
    plt.subplot(1, 2, 2)
    plt.plot(
        range(1, len(cumulative_explained_variance) + 1),
        cumulative_explained_variance,
        marker="o",
    )
    plt.xlabel("Number of Components")
    plt.ylabel("Cumulative Variance")
    plt.title("Cumulative Explained Variance by Components")
    plt.axhline(y=0.99, color="r", linestyle="-")
    plt.axhline(y=0.95, color="r", linestyle="-")

    n_components = (
        len(cumulative_explained_variance[cumulative_explained_variance < 0.99]) + 1
    )
    plt.axvline(x=n_components, color="r", linestyle="--")
    plt.tight_layout()
    plt.show()

    return n_components


def plot_elbow_method(X):
    model = KMeans(random_state=42, n_init=10)
    elbow = KElbowVisualizer(model, k=(2, 20))
    elbow.fit(X)

    print(f"Recommended number of clusters: {elbow.elbow_value_}")

    # Compute silhouette score
    labels = elbow.labels_
    silhouette_avg = silhouette_score(X, labels)
    print(f"Silhouette Score: {silhouette_avg}")

    elbow.show()
    return elbow.elbow_value_


def plot_sihloette_scores(X):
    fig, ax = plt.subplots(3, 2, figsize=(15, 8))
    for i in [2, 3, 4, 5, 6, 7]:
        km = KMeans(
            n_clusters=i, init="k-means++", n_init=10, max_iter=100, random_state=42
        )
        q, mod = divmod(i, 2)
        silhouette = SilhouetteVisualizer(km, colors="yellowbrick", ax=ax[q - 1][mod])
        silhouette.fit(X)


def plot_tsne(X, n_components, labels, model_name):
    tsne = TSNE(n_components=n_components, random_state=0)
    np.set_printoptions(suppress=True)
    X_tsne = tsne.fit_transform(X)

    plt.figure(figsize=(8, 6))
    plt.title(model_name)
    for label in np.unique(labels):
        indices = labels == label
        plt.scatter(
            X_tsne[indices, 0],
            X_tsne[indices, 1],
            label=label,
            alpha=0.8,
            edgecolors="w",
        )


def plot_cluster_features(df, model_name):
    sns.pairplot(
        df[
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
                model_name,
            ]
        ],
        hue=model_name,
        # dropna=True,
    )
