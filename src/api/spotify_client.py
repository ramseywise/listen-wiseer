import pandas as pd
import requests
from datetime import datetime
from flask import request, redirect, session
from utils.config import *

session = requests.Session()
session.verify = False


class SpotifyClient:
    """SpotifyClient performs operations using the Spotify API."""

    def __init__(self) -> None:
        super().__init__()
        self.auth = SpotifyAuth(client_id, client_secret, redirect_uri, token_url)
        self.data = SpotifyPlaylistApi()
        # self.playlist = SpotifyPlaylistModifier()
        # self.recommendations = SpotifyRecommender()


class SpotifyAuth:
    """SpotifyAuth returns access token from Spotify API."""

    client_id: str
    client_secret: str
    token_url: str
    redirect_uri: str

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        token_url: str,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self.redirect_uri = redirect_uri

    #    def get_authentication_code(self):
    #        params = {
    #            "client_id": client_id,
    #            "response_type": "code",
    #            "redirect_uri": redirect_uri,
    #            "scope": scope,
    #        }
    #        log.info("Requesting authorization code")
    #        response = requests.get(auth_url, params=params)
    #
    #        return response

    def get_access_token(self) -> dict:
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

            # save token info to refresh token
            session_info = {}
            token_info = response.json()
            session_info["access_token"] = token_info["access_token"]
            session_info["refresh_token"] = token_info["refresh_token"]
            session_info["expires_at"] = (
                datetime.now().timestamp() + token_info["expires_in"]
            )
            return session_info["access_token"], redirect("/data")


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
    """SpotifyPlaylistAPI requests features for a specific playlist."""

    def request_track_features(self, headers: dict, playlist_id: str) -> dict:
        endpoint = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        response = requests.get(endpoint, headers=headers)  # get first 100 songs
        r = response.json()
        tracks = r["items"]

        # continue if request is for more than 100 songs
        if r["next"] is None:
            return tracks
        else:
            response = requests.get(r["next"], headers=headers)
            r = response.json()
            tracks.extend(r["items"])
            return tracks

    def request_audio_features(
        self, headers: dict, track_ids: list[str]
    ) -> pd.DataFrame:
        new_audio_features = []
        for track_id in track_ids:
            endpoint = f"https://api.spotify.com/v1/audio-features/{track_id}"
            response = requests.get(endpoint, headers=headers)
            audio_features = response.json()
            new_audio_features.append(audio_features)
        return pd.DataFrame(new_audio_features)

    def request_artist_features(
        self, headers: dict, filtered_artist_ids: list[str]
    ) -> pd.DataFrame:
        genres = {}
        popularity = {}
        if len(filtered_artist_ids) > 0:
            for artist_id in filtered_artist_ids:
                # NOTE: this limits requests to 500
                endpoint = f"https://api.spotify.com/v1/artists/{artist_id}"
                response = requests.get(endpoint, headers=headers)
                artists = response.json()
                genres.update({artist_id: artists["genres"]})
                popularity.update({artist_id: str(artists["popularity"])})
        new_artists = pd.DataFrame([popularity, genres]).T.reset_index()

        return new_artists


# TODO: add future api calls here as new classes or create different classes for each instead of one client to import?
