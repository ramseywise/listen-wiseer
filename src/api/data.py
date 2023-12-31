import json
import requests
import numpy as np
import pandas as pd
from flask import jsonify, request
from modeling.const import *
import logger


log = logger.get_logger("app")


def _request_playlist_data(headers, playlist_id):
    endpoint = "https://api.spotify.com/v1/playlists/" + playlist_id + "/tracks"
    response = requests.get(endpoint, headers=headers)
    if "error" in request.args:
        return jsonify({"error": request.args["error"]})
    else:
        r = response.json()
        tracks = r["items"]
        while r["next"]:
            response = requests.get(r["next"], headers=headers)
            if "error" in request.args:
                return jsonify({"error": request.args["error"]})
            else:
                r = response.json()
                tracks.extend(r["items"])
                return tracks


def _request_artist_info(headers, artist_id):  # genre, popularity
    endpoint = "https://api.spotify.com/v1/artists/" + artist_id
    response = requests.get(endpoint, headers=headers)
    if "error" in request.args:
        return jsonify({"error": request.args["error"]})
    else:
        return response.json()


def _request_audio_features(headers, track_ids):
    results = []
    for track_id in track_ids:
        endpoint = "https://api.spotify.com/v1/audio-features/" + track_id
        response = requests.get(endpoint, headers=headers)
        if "error" in request.args:
            return jsonify({"error": request.args["error"]})
        else:
            r = response.json()
            results.append(r)
    return pd.DataFrame(results)


def return_playlist_data(headers, playlist_id, playlist_name):
    log.info("Requesting track info data")
    my_current_tracks = pd.read_csv(
        "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_tracks.csv",
        index_col=0,
    )
    my_current_track_ids = list(my_current_tracks["id"])

    tracks = _request_playlist_data(headers, playlist_id)

    track_ids = []
    track_uris = []
    track_names = []
    release_dates = []
    artist_ids = []
    artist_names = []
    for i in range(len(tracks)):
        track_ids.append(tracks[i]["track"]["id"])
        track_uris.append(tracks[i]["track"]["uri"])
        track_names.append(tracks[i]["track"]["name"])
        artists = [artist["id"] for artist in tracks[i]["track"]["artists"]]
        artist_ids.append(artists)
        artists = [artist["name"] for artist in tracks[i]["track"]["artists"]]
        artist_names.append(artists)
        release_dates.append(tracks[i]["track"]["album"]["release_date"])

    my_tracks = pd.DataFrame(
        {
            "id": track_ids,
            "track_name": track_names,
            "release_date": release_dates,
            "artist_ids": artist_ids,
            "artist_names": artist_names,
            "playlist_id": playlist_id,
            "playlist_name": playlist_name,
        }
    )

    # append only new tracks
    my_tracks[~my_tracks.id.isin(my_current_track_ids)].reset_index(drop=True).to_csv(
        "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_tracks.csv",
        mode="a",
        header=False,
    )
    return my_tracks


def return_artist_data(headers, my_tracks):
    log.info("Requesting artist info for tracks")
    my_current_artists = pd.read_csv(
        "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_artists.csv",
        index_col=0,
    )
    my_current_artist_ids = list(my_current_artists["id"])

    # filter artist ids if already in my_artists
    filtered_artist_ids = set()
    for row in my_tracks.artist_ids:
        filtered_artist_ids.update(
            set([element for element in row if element not in my_current_artist_ids])
        )
    if len(filtered_artist_ids) > 0:
        # if not call api
        genres = {}
        popularity = {}
        for artist_id in filtered_artist_ids:
            for i in range(len(artist_id)):
                r = _request_artist_info(headers, artist_id)
                genres.update({artist_id: r["genres"]})
                popularity.update({artist_id: str(r["popularity"])})
        my_new_artists = pd.DataFrame([popularity, genres]).T.reset_index()
        my_new_artists.columns = ["artist_id", "popularity", "genre"]

        # append new artists to my_artists
        my_new_artists.reset_index(drop=True).to_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_artists.csv",
            mode="a",
            header=False,
        )

        return my_new_artists


def return_audio_features(headers, my_tracks):
    log.info("Requesting audio features for track ids")
    audio_features = pd.read_csv(
        "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/audio_features.csv",
        index_col=0,
    )
    audio_feature_track_ids = list(audio_features["id"])

    # filter artist ids if already in my_artists
    filtered_track_ids = set(
        [
            element
            for element in set(my_tracks.id)
            if element not in audio_feature_track_ids
        ]
    )

    if len(filtered_track_ids) > 0:
        data = _request_audio_features(headers, filtered_track_ids).reset_index()
        data = data[
            [
                "id",
                "danceability",
                "energy",
                "loudness",
                "speechiness",
                "acousticness",
                "instrumentalness",
                "liveness",
                "valence",
                "tempo",
                "duration_ms",
                "time_signature",
                "key",
                "mode",
            ]
        ]
        data.reset_index(drop=True).to_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/audio_features.csv",
            mode="a",
            header=False,
        )
        return data
    else:
        data = pd.read_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/audio_features.csv",
            index_col=0,
        )
        return data


def return_full_playlist_df(headers, playlist_id, playlist_name):
    my_tracks = return_playlist_data(headers, playlist_id, playlist_name)
    # my_new_artists = return_artist_data(headers, my_tracks)
    data = return_audio_features(headers, my_tracks)

    log.info("Preparing categorical variables")
    # reload this with all artists
    my_artists = pd.read_csv(
        "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_artists.csv",
        index_col=0,
    )
    # get artist genres
    artists = my_tracks[["artist_ids"]]
    genres = []
    for row in artists["artist_ids"]:
        genre = my_artists[my_artists.id.isin(row)]["genre"].values
        genres.append(genre)
    artists.loc[:, "genres"] = genres
    artists.loc[:, "genres"] = [", ".join(map(str, l)) for l in artists["genres"]]
    artists.loc[:, "first_genre"] = artists.genres.str.split(",", expand=True)[0]
    artists.first_genre = artists.first_genre.replace("nan", np.nan)

    # search for my genres as categories
    for genre in my_genres:
        artists.loc[artists["genres"].str.contains(genre), "genre_cat"] = genre
    # artists.genre_cat.replace("", np.nan, inplace=True)

    # get artist popularity
    my_artists["popularity"] = pd.to_numeric(my_artists["popularity"], errors="coerce")

    popu_avg = []
    for row in artists.artist_ids:
        popu_avg.append(my_artists[my_artists.id.isin(row)].popularity.mean())
    artists.loc[:, "popularity"] = popu_avg

    # prepare merge
    my_tracks.loc[:, "artist_ids"] = [
        ", ".join(map(str, l)) for l in my_tracks["artist_ids"]
    ]
    artists.loc[:, "artist_ids"] = [
        ", ".join(map(str, l)) for l in artists["artist_ids"]
    ]
    my_artists.columns = ["artist_ids", "popularity", "genre"]
    df = my_tracks.merge(artists, on="artist_ids", how="left")
    df = df.merge(data, on="id", how="left")

    # Prepare other categorical variables
    df["release_date"] = pd.to_datetime(df["release_date"], format="ISO8601")
    df["year"] = df["release_date"].dt.year

    # map keys/mode to labels
    df["decade"] = df["year"].apply(lambda x: str(x)[:3] + "0s")
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

    # save playlist data
    df = df[df.playlist_name == playlist_name].drop_duplicates(subset=["id"])
    df.to_csv(
        "/Users/wiseer/Documents/github/listen-wiseer/src/data/playlists/"
        + playlist_name
        + ".csv"
    )

    return df
