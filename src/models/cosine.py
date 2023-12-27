import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from preprocessing import *
from const import *


class Cosine_Similarity_Recommendation:
    def __init__(self, track_uris=[]):
        self.track_uris = track_uris

    def return_track_uris(self, y):
        # load train data for recommendation
        X = pd.read_csv(
            "/Users/wiseer/Documents/playground/listen-wiseer/src/data/train_transformed.csv",
            index_col=0,
        )
        X = X[top_features]
        y = y[top_features]

        # create df for score results
        result = pd.DataFrame(list(X.index), columns=["id"])
        # calculate cosine simularity
        for i in range(len(y)):
            j = i + 1
            scores = cosine_similarity(X, y[i:j], dense_output=True).flatten()
            result[i] = scores

        # prepare top tracks
        for i in range(len(y)):
            result = result.sort_values(i, ascending=False)
            track = result[1:2]["id"].item()
            track_uri = "spotify:track:" + track  # first row is input song
            self.track_uris.append(track_uri)
        return self.track_uris
