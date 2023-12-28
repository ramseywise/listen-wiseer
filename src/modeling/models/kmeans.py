from matplotlib import pyplot as plt
import numpy as np
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA


def plot_PCA(df):
    pca = PCA().fit(train)
    y = np.cumsum(pca.explained_variance_ratio_)
    xi = np.arange(1, len(y) + 1, step=1)
    plt.figure(figsize=(12, 6))
    plt.plot(xi, y, marker="o", linestyle="--", color="b")
    plt.xlabel("Number of Components")
    plt.ylabel("Cumulative variance (%)")
    plt.title("The number of components needed to explain variance")
    plt.axhline(y=0.95, color="r", linestyle="-")
    plt.axhline(y=0.80, color="r", linestyle="-")

    return plt.show()


def plot_elbow(df):
    # elbow method for determining n clusters
    sum_of_squared_distances = []
    K = range(1, 15)  # 15 max clusters
    for k in K:
        km = KMeans(n_clusters=k)
        km = km.fit(df)
        sum_of_squared_distances.append(km.inertia_)  ### wtf

    plt.plot(K, sum_of_squared_distances, "bx-")
    plt.xlabel("num_clusters")
    plt.ylabel("sum_of_squared_distances")
    plt.title("Elbow Method For Optimal k")

    return plt.show()


def kmean_classification(df):
    k_means = KMeans(random_state=1, n_clusters=10)  # default n_clusters = 8
    k_means.fit(df)
    predicted_clusters = k_means.fit_predict(df)
    df["kmean"] = predicted_clusters
    return df

# TODO: make report for cluster classifications

#def impute_genre(df):
#    test = df[["id", "track_name", "artist_names", "genres", "top_genre"]].merge(
#        df[["id", "kmean"]], on="id", how="inner"
#    )
#
#    test["genre"] = test.top_genre
#    test.genre = np.where(test.kmean == 0, test.genre.fillna("ambient"), test.genre)
#    test.genre = np.where(test.kmean == 1, test.genre.fillna("rock"), test.genre)
#    test.genre = np.where(test.kmean == 2, test.genre.fillna("folk"), test.genre)
#    test.genre = np.where(test.kmean == 4, test.genre.fillna("bachata"), test.genre)
#    test.genre = np.where(test.kmean == 5, test.genre.fillna("electronica"), test.genre)
#    test.genre = np.where(test.kmean == 6, test.genre.fillna("kizomba"), test.genre)
#    test.genre = np.where(test.kmean == 7, test.genre.fillna("lo-fi beats"), test.genre)
#    test.genre = np.where(test.kmean == 8, test.genre.fillna("acoustic"), test.genre)
#    test.genre = np.where(
#        test.kmean == 8, test.genre.fillna("turkish alt pop"), test.genre
#    )
#    test.top_genre = test.genre
#
#    return df
