import pandas as pd
import numpy as np
#from sklearn.preprocessing import MinMaxScaler
#from sklearn.metrics import euclidean_distances
from scipy.spatial.distance import pdist, squareform

class Euclidean_Distance_Recommendation:
    def __init__(self, track_uris=[]):
        self.track_uris = track_uris
        # self.normalize = StandardScaler()
        # self.model = cosine_similarity()

    def return_track_uris(self):
        df = pd.read_csv(
            "/Users/wiseer/Documents/playground/listen-wiseer/src/data/sample.csv",
            index_col=0,
        )

        # calculate distance
        X = df.set_index(["Spotify ID"])
        distances = pdist(X.values, metric="euclidean")
        dist_matrix = squareform(distances)
        distances_from_input_row = pd.DataFrame(dist_matrix)[1].sort_values()

        X = X.reset_index()  # to rejoin track IDs with results
        nearest_rows = X[X.index.isin(distances_from_input_row.index)]
        output_df = pd.concat((nearest_rows, distances_from_input_row), axis=1)
        result = output_df.sort_values(1)

        for item in result["Spotify ID"][:10]:
            track_uri = "spotify:track:" + item
            self.track_uris.append(track_uri)

        return self.track_uris
