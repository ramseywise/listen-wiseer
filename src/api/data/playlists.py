import requests
import pandas as pd
from marshmallow import ValidationError
from api.spotify_client import *
from api.data.schema import *
from config import *

log = logger.get_logger("app")

spAuth = SpotifyAuth(client_id, client_secret, token_url, redirect_uri)


class SpotifyPlaylistAPI:
    access_token: str

    def __init__(self) -> pd.DataFrame:
        self.headers = {
            "Authorization": "Bearer {token}".format(token=self.access_token)
        }

    def request_playlist_data(self, playlist_id: str) -> list:
        endpoint = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        response = requests.get(endpoint, headers=self.headers)
        my_tracks = response.json()

        # continue if request is for more than 100 songs
        if my_tracks["next"]:
            response = requests.get(my_tracks["next"], headers=self.headers)
            next_tracks = response.json()
            my_tracks.extend(next_tracks)
        return my_tracks

    def request_audio_features(self, track_ids: list[str]) -> pd.DataFrame:
        results = []
        for track_id in track_ids:
            endpoint = f"https://api.spotify.com/v1/audio-features/{track_id}"
            response = requests.get(endpoint, headers=self.headers)
            audio = response.json()
            results.append(audio)
        return pd.DataFrame(results)

    def request_artist_features(self, artist_id: str) -> dict:
        # NOTE: this limits requests as well
        endpoint = f"https://api.spotify.com/v1/artists/{artist_id}"
        response = requests.get(endpoint, headers=self.headers)
        my_artists = response.json()
        return my_artists

    ## return as dataframe
    def return_artist_features(self, artist_ids: list[str]) -> pd.DataFrame:
        my_artists = [
            self.request_artist_features(artist_id) for artist_id in artist_ids
        ]
        return my_artists

    def return_playlist_data(
        self, my_tracks: list, my_artists: list, audio_features: list
    ) -> pd.DataFrame():
        df = pd.concat([my_tracks] + my_artists + audio_features, axis=1)
        return df
