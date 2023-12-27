import json
import requests
import pandas as pd


def _request_playlist_data(headers, playlist_id):
    endpoint = "https://api.spotify.com/v1/playlists/" + playlist_id + "/tracks"
    r = requests.get(endpoint, headers=headers)
    return r.json()


def _request_artist_info(headers, artist_ids):  # genre, popularity
    endpoint = "https://api.spotify.com/v1/artists/" + artist_ids
    r = requests.get(endpoint, headers=headers)
    return r.json()


def _request_audio_features(headers, track_ids):
    results = []
    for track_id in track_ids:
        endpoint = "https://api.spotify.com/v1/audio-features/" + track_id
        r = requests.get(endpoint, headers=headers)
        r = r.json()
        results.append(r)
    data = pd.DataFrame(results)
    return data


def return_playlist_features(headers, playlist_id):
    print("Requesting playlist track ids")
    r = _request_playlist_data(headers, playlist_id)
    df = pd.DataFrame(r["items"])[["track"]]
    track_ids = []
    track_names = []
    release_dates = []
    artist_ids = []
    artist_names = []
    genres = []
    popularity = []

    for row in df["track"]:
        track_id = row["id"]
        track_ids.append(track_id)
        track_name = row["name"]
        track_names.append(track_name)
        release_date = row["album"]["release_date"]
        release_dates.append(release_date)
        artist_id = row["artists"][0]["id"]
        artist_ids.append(artist_id)
        artist_name = row["artists"][0]["name"]
        artist_names.append(artist_name)

    print("Requesting artist info for tracks")
    for artist_id in artist_ids:
        r = _request_artist_info(headers, artist_id)  # artist id
        genres.append(r["genres"])
        popularity.append(r["popularity"])

    print("Requesting audio features for track ids")
    data = _request_audio_features(headers, track_ids)
    data["id"] = track_ids
    data["track_name"] = track_names
    data["release_date"] = release_dates
    data["artist_ids"] = artist_ids
    data["artist_names"] = artist_names
    data["genres"] = genres
    data["popularity"] = popularity

    return data
