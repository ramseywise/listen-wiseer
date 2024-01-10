import os
import pandas as pd
from sklearn.metrics.pairwise import cosine_similarity
from modeling.const import *

os.chdir("/Users/wiseer/Documents/github/listen-wiseer/src/")


class Cosine_Similarity_Recommendation:
    def __init__(self, track_uris=[]):
        self.track_uris = track_uris

    def return_track_uris(self, test):
        train = pd.read_csv("data/train_new.csv", index_col=0)
        test = map_genres(test)

        X = transform_feature_data(train)
        y = transform_feature_data(test)

        X = X[y.columns]

        # create df for score results to filter
        result = train[["id", "first_genre", "track_name", "genre"]]
        # names = pd.read_csv("data/recommended_tracks.csv", index_col=0)
        # filter = list(names.track_name)
        filter = list(test.track_name)

        # calculate cosine simularity
        for i in range(len(y)):
            j = i + 1
            scores = cosine_similarity(X, y[i:j], dense_output=True).flatten()
            result.loc[i] = scores

        # recommendation tracks
        for ind, row in test.iterrows():
            r = result[result.first_genre == row[["first_genre"]].item()]
            r = r[~r.track_name.isin(filter)]
            r = r.sort_values(ind, ascending=False)
            if len(r) > 0:
                # add tracks that match to first_genre
                track = r[:1]["id"].item()
                track_uri = "spotify:track:" + track
                self.track_uris.append(track_uri)
                filter.append(r[:1]["track_name"].item())
            else:
                r = result[result.genre == row[["genre"]].item()]
                r = r[~r.track_name.isin(filter)]
                r = r.sort_values(ind, ascending=False)
                if len(r) > 0:
                    # add tracks that match to genre category
                    track = r[:1]["id"].item()
                    track_uri = "spotify:track:" + track
                    self.track_uris.append(track_uri)
                    filter.append(r[:1]["track_name"].item())
                else:
                    ## TODO: if genre unmatched, add to genre source map
                    continue

        # save recommendations to filter future recommendations
        result = result[result.track_name.isin(filter)]
        result[["track_name"]].reset_index(drop=True).to_csv("data/recommended_tracks.csv")

        return self.track_uris
