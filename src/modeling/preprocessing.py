import os
import numpy as np
import pandas as pd
from datetime import datetime
from sklearn.preprocessing import MinMaxScaler, OneHotEncoder
from modeling.const import *
import logger

os.chdir("/Users/wiseer/Documents/github/listen-wiseer/src/")
log = logger.get_logger("app")


def return_first_genre(df):
    log.info("Return first genre")
    df["genres"] = [",".join(map(str, l)) for l in df["genres"]]
    df["first_genre"] = df["genres"].apply(
        lambda x: x.split(",")[0].replace("[", "").replace("]", "").replace("'", "")
    )

    return df


def map_genres(df):
    # prepare genre feature
    df = return_first_genre(df)

    log.info("Mapping genres")
    # load genre map
    gm = pd.read_csv(
        "data/genre_map_source.csv",
        index_col=0,
    )
    gm = gm.sort_values("genre").reset_index(drop=True)
    gm.columns = ["genre_cat", "first_genre"]
    df = df.merge(gm, on="first_genre", how="left")

    # check if first genre matches my genres
    for genre in my_genres:
        df.loc[df["first_genre"].str.contains(genre), "genre"] = genre
    df.genre = np.where(df.genre.isnull(), df.genre_cat, df.genre)

    # check if genres contains subgenre
    for genre in list(gm.genre_cat):
        df.loc[df["genres"].str.contains(genre), "sub_genre"] = genre
    df.genre = np.where(df.genre.isnull(), df.sub_genre, df.genre)

    return df


def engineer_features(df):
    log.info("Engineering features")
    # prepare genre features
    df = map_genres(df)

    # set release date as datetime
    df["release_date"] = pd.to_datetime(df["release_date"], format="ISO8601")

    # make year column datetime
    df["year"] = df["release_date"].dt.year

    # create decade column
    df["decade"] = df["year"].apply(lambda x: str(x)[:3] + "0s")

    # map keys/mode to labels
    keys = {
        0: "C",
        1: "Db",
        2: "D",
        3: "Eb",
        4: "E",
        5: "F",
        6: "F#",
        7: "G",
        8: "Ab",
        9: "A",
        10: "Bb",
        11: "B",
    }
    df["key_labels"] = df["key"].map(keys)
    modes = {0: "Minor", 1: "Major"}
    df["mode_labels"] = df["mode"].map(modes)

    # create a column that concatonates key with mode
    df["key_mode"] = df["key_labels"] + " " + df["mode_labels"]

    return df


def preprocess_numerical_features(df):
    log.info("Preprocessing numerical features")
    # set index
    df = df.set_index(["id"])
    # select features
    df = df[num_features]
    # Normalize continuous features
    scaler = MinMaxScaler()
    # scaler = StandardScaler() #ss gives neg
    df[num_features] = scaler.fit_transform(df[num_features])

    return df


def preprocess_cat_features(df):
    log.info("Preprocessing categorical features")
    ohe = OneHotEncoder(categories="auto")
    values = ohe.fit_transform(df[cat_features]).toarray()
    labels = pd.unique(df[cat_features].values.ravel())
    features = pd.DataFrame(values, columns=labels)
    # features.drop([np.nan], axis=1, inplace=True)

    return features


def transform_feature_data(df):
    df = engineer_features(df)
    num_df = preprocess_numerical_features(df).reset_index()
    cat_df = preprocess_cat_features(df)

    # create empty genre columns
    for col in cat_cols:
        if col not in cat_df.columns:
            cat_df[col] = 0
        else:
            continue

    log.info("Combining dfs")
    new_df = num_df.join(cat_df).fillna(0)
    new_df = new_df.set_index(["id"])

    return new_df
