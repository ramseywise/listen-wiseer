import json
import pandas as pd
import logger
import requests
import datetime
from flask import request, redirect, session
from config import *

log = logger.get_logger("app")


class SpotifyClient:
    """SpotifyClient performs operations using the Spotify API."""

    def __init__(self) -> None:
        super().__init__()
        self.auth = SpotifyAuth()
        self.data = SpotifyPlaylistApi()
        # self.playlist = SpotifyPlaylistModifier()
        # self.recommendations = SpotifyRecommender()


class SpotifyAuth:
    """SpotifyAuth returns access token from Spotify API."""

    client_id: str
    client_secret: str
    redirect_uri: str
    token_url: str

    def __init__(
        self, client_id: str, client_secret: str, token_url: str, redirect_uri: str
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self.redirect_uri = redirect_uri

    def get_access_token(self):
        """Return authorization code to exchange for session access token."""
        if "code" in request.args:
            params = {
                "code": request.args["code"],
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
            response = requests.post(self.token_url, data=params)
            try:
                token_data = response.json()
            except (json.decoder.JSONDecodeError, ValueError):
                token_data = None

                # define session info to refresh token
                session["access_token"] = token_data["access_token"]
                session["refresh_token"] = token_data["refresh_token"]
                session["expires_at"] = (
                    datetime.now().timestamp() + token_data["expires_in"]
                )
                print(session["access_token"])
                return session["access_token"], redirect("/data")

#    def refresh_access_token(self):
#        refresh_headers = {"Content-Type": "application/x-www-form-urlencoded"}
#        params = {
#            "grant_type": "refresh_token",
#            "refresh_token": session["refresh_token"],
#            "client_id": self.client_id,
#            "redirect_uri": self.redirect_uri,
#        }
#        response = requests.post(
#            self.token_url, data=params, headers=refresh_headers
#        )
#        new_token_info = response.json()
#        session["access_token"] = new_token_info["access_token"]
#        session["expires_at"] = (
#            datetime.datetime.now().timestamp() + new_token_info["expires_in"]
#        )
#        return session["access_token"]


class SpotifyPlaylistApi:

    """SpotifyPlaylistAPI requests track features for a specific playlist."""

    def request_track_features(self, headers: dict, playlist_id: str) -> list[list]:
        endpoint = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        response = requests.get(endpoint, headers=headers)
        my_tracks = response.json()

        # continue if request is for more than 100 songs
        next_endpoint = my_tracks.get("next")
        if next_endpoint:
            response = requests.get(next_endpoint, headers=headers)
            next_tracks = response.json()
            my_tracks.append(next_tracks)
        return my_tracks

    def request_audio_features(
        self, headers: dict, track_ids: list[str]
    ) -> pd.DataFrame:
        results = []
        for track_id in track_ids:
            endpoint = f"https://api.spotify.com/v1/audio-features/{track_id}"
            response = requests.get(endpoint, headers=headers)
            audio = response.json()
            results.append(audio)
        return pd.DataFrame(results)

    def request_artist_features(self, headers: dict, artist_id: str) -> dict:
        # NOTE: this limits requests as well
        endpoint = f"https://api.spotify.com/v1/artists/{artist_id}"
        response = requests.get(endpoint, headers=headers)
        my_artists = response.json()
        return my_artists
