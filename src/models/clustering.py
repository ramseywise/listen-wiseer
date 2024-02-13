import os
import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt
from scipy.cluster.hierarchy import dendrogram, linkage
from sklearn.manifold import TSNE
from sklearn.decomposition import PCA
from sklearn.metrics import (
    silhouette_score,
    calinski_harabasz_score,
    davies_bouldin_score,
)
from yellowbrick.cluster import KElbowVisualizer
from yellowbrick.cluster import SilhouetteVisualizer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import MinMaxScaler, OrdinalEncoder
from sklearn.cluster import AgglomerativeClustering, KMeans, SpectralClustering, dbscan

from utils.const import *
from analysis.data import *

data = LoadPlaylistData()

os.chdir("/Users/wiseer/Documents/github/listen-wiseer/src/")

class RemixRecommendation:
    "Filters data to create new mixes based on clustering algorithm"

    def return_filtered_data(self) -> pd.DataFrame:
        df = data.return_enoa_data()

        # Set conditions for remix
        df = df[((df.playlist_name == "zoukini") & (df.tempo < 150))]
        return df

    def return_X_to_fit(self) -> pd.DataFrame:
        df = self.return_filtered_data()
        numeric_features = num_features + [
            "top",
            "left",
        ]  # let's try this out for genre
        categorical_features = ["time_signature", "key_mode", "decade"]
        # label encoding for decade; ordinal for time_signature and key_mode

        X = df[numeric_features + categorical_features]
        one_hot_encoded = pd.get_dummies(X[categorical_features])
        X = pd.concat([X, one_hot_encoded], axis=1)
        X = X.drop(categorical_features, axis=1)
        return X

    def config_model_pipeline(self, n_components, n_clusters):
        pipeline = Pipeline(
            [
                ("scaler", MinMaxScaler()),
                ("ordinal_encoder", OrdinalEncoder()),
                ("pca", PCA(n_components=n_components)),
                ("classifier", SpectralClustering(n_clusters=n_clusters)),
            ]
        )
        return pipeline

    def run_model_pipeline(self, df: pd.DataFrame) -> pd.DataFrame:
        X = self.return_X_to_fit()
        n_components = 3  # select_pca_n_components(X)
        n_clusters = 5  # plot_elbow_method(X)
        pipeline = self.config_model_pipeline(n_components, n_clusters)

        # return clusters
        model_name = type(pipeline.named_steps["classifier"]).__name__
        labels = pipeline.fit_predict(X).tolist()
        df[model_name] = labels
        return df

    def return_track_uris(self) -> list[str]:
        df = self.return_filtered_data()
        df = self.run_model_pipeline(df)
        # for now, let's just add one playlist mix
        df[df.SpectralClustering == 0][["id"]]
        df["track_uri"] = df["id"].apply(lambda x: f"spotify:track:{x}")
        return df["track_uri"].to_list()

    # TODO: add function to limit playlists to each group or use different clustering
