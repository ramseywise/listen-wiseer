import pandas as pd
import requests
from datetime import datetime
from flask import request, redirect, session
from config import *

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
    token_url: str
    redirect_uri: str
    session: dict

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        token_url: str,
        session: dict,
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self.redirect_uri = redirect_uri
        self.session = session

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
            print(response)
            # save session info to refresh otken
            token_info = response.json()
            session["access_token"] = token_info["access_token"]
            session["refresh_token"] = token_info["refresh_token"]
            session["expires_at"] = (
                datetime.now().timestamp() + token_info["expires_in"]
            )
            print(session["access_token"])
            return redirect("/data")


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
        response = response.json()
        tracks = response["items"]

        # continue if request is for more than 100 songs
        next_endpoint = response.get("next")
        if next_endpoint:
            response = requests.get(next_endpoint, headers=headers)
            response = response.json()
            tracks.append(response["items"])
        return tracks

    def request_audio_features(
        self, headers: dict, track_ids: list[str]
    ) -> pd.DataFrame:
        audio_features = []
        for track_id in track_ids:
            endpoint = f"https://api.spotify.com/v1/audio-features/{track_id}"
            response = requests.get(endpoint, headers=headers)
            audio = response.json()
            audio_features.append(audio)
        return pd.DataFrame(audio_features)

    # def request_artist_features(self, headers: dict, artist_id: str) -> pd.DataFrame:
    #     # NOTE: this limits requests as well
    #     endpoint = f"https://api.spotify.com/v1/artists/{artist_id}"
    #     response = requests.get(endpoint, headers=headers)
    #     artists = response.json()
    #     return artists

    def request_artist_features(
        self, headers: dict, filtered_artist_ids: list[str]
    ) -> pd.DataFrame:
        genres = {}
        popularity = {}
        if len(filtered_artist_ids) > 0:
            for artist_id in filtered_artist_ids:
                for _ in range(len(artist_id)):
                    response = self.request_artist_features(headers, artist_id)
                    genres.update({artist_id: response["genres"]})
                    popularity.update({artist_id: str(response["popularity"])})
        my_artists = pd.DataFrame([popularity, genres]).T.reset_index()

        # append new artists
        my_artists.columns = ["artist_id", "popularity", "genre"]
        my_artists.reset_index(drop=True).to_csv(
            "/Users/wiseer/Documents/github/listen-wiseer/src/data/api/my_artists.csv",
            mode="a",
            header=False,
        )
        return my_artists
