import requests
import logger
import requests
import pandas as pd
from pydantic import BaseModel
from marshmallow import ValidationError
from datetime import datetime
from flask import request, redirect, jsonify, session
from api.data.schema import *
from config import *

log = logger.get_logger("app")

data_schema = PlaylistFeaturesSchema()
data_schema.context = {
    "artist_schema": ArtistFeaturesSchema(),
    "audio_schema": AudioFeaturesSchema(),
    "track_schema": TrackFeaturesSchema(),
}


class SpotifyClient(BaseModel):
    """SpotifyClient performs operations using the Spotify API."""

    def __init__(self) -> None:
        super().__init__()
        self.auth = SpotifyAuth()
        self.data = SpotifyPlaylistData()
        # self.playlist = SpotifyPlaylistModifier()
        # self.recommendations = SpotifyRecommender()


class SpotifyAuth:
    """SpotifyAuth returns access token from Spotify API."""

    def __init__(
        self, client_id: str, client_secret: str, redirect_uri: str, token_url: str
    ):
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_url = token_url
        self.redirect_uri = redirect_uri

    def get_access_token(self):
        """Return authorization code to exchange for session access token."""
        if "error" in request.args:
            return jsonify({"error": request.args["error"]})
        if "code" in request.args:
            params = {
                "code": request.args["code"],
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
            }
            log.info("Requesting access token")
            response = requests.post(token_url, data=params)
            if "error" in request.args:
                return jsonify({"error": request.args["error"]})
            else:
                token_info = response.json()
                session["access_token"] = token_info["access_token"]
                session["refresh_token"] = token_info["refresh_token"]
                session["expires_at"] = (
                    datetime.now().timestamp() + token_info["expires_in"]
                )
                print(session["access_token"])
                return session, redirect("/data")

    def refresh_token(self):
        if datetime.datetime.now().timestamp() > session["expries_at"]:
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
            params = {
                "grant_type": "refresh_token",
                "refresh_token": session["refresh_token"],
                "client_id": client_id,
                "redirect_uri": redirect_uri,
            }
            response = requests.post(token_url, data=params, headers=headers)
            new_token_info = response.json()
            session["access_token"] = new_token_info["access_token"]
            session["expires_at"] = (
                datetime.datetime.now().timestamp() + new_token_info["expires_in"]
            )
        return session["access_token"]


class SpotifyPlaylistData:
    def __init__(self) -> pd.DataFrame:
        self.session = session
        self.headers = {
            "Authorization": "Bearer {token}".format(token=session["access_token"])
        }

    def request_playlist_data(self, playlist_id: str) -> list:
        endpoint = f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks"
        response = requests.get(endpoint, headers=self.headers)
        json_data = response.json()
        try:
            my_tracks = data_schema.load(json_data["items"], many=True)
        except ValidationError as err:
            log.error("Invalid track data: %s", err)
            return None

        # continue if request is for more than 100 songs
        while json_data["next"]:
            response = requests.get(json_data["next"], headers=self.headers)
            json_data = response.json()

            # Validate tracks data with marshmallow schema
            try:
                next_tracks = data_schema.load(json_data["items"], many=True)
            except ValidationError as err:
                log.error("Invalid track data: %s", err)
                return None
            my_tracks.extend(next_tracks)
        return my_tracks

    def get_playlist_data(
        self, track_ids: list[str], artist_ids: list[str], my_tracks: pd.DataFrame
    ) -> pd.DataFrame:
        my_artists = [
            self._request_artist_features(artist_id) for artist_id in artist_ids
        ]
        audio_features = [
            self._request_audio_features(track_id) for track_id in track_ids
        ]
        df = pd.concat([my_tracks] + my_artists + audio_features, axis=1)

        # Validate final dataframe
        try:
            data_schema.load(df.to_dict(orient="records"), many=True)
        except ValidationError as err:
            log.error("Invalid track data")
            return None

        return df

    def _request_artist_features(self, artist_id: str) -> dict:
        # NOTE: this limits requests as well
        endpoint = f"https://api.spotify.com/v1/artists/{artist_id}"
        response = requests.get(endpoint, headers=self.headers)
        json_data = response.json()
        try:
            my_artists = data_schema.load(json_data["items"], many=True)
        except ValidationError as err:
            log.error("Invalid track data: %s", err)
        return my_artists

    def _request_audio_features(self, track_ids: list[str]) -> pd.DataFrame:
        results = []
        for track_id in track_ids:
            endpoint = f"https://api.spotify.com/v1/audio-features/{track_id}"
            response = requests.get(endpoint, headers=self.headers)
            json_data = response.json()
            try:
                audio = data_schema.load(json_data["items"], many=True)
            except ValidationError as err:
                log.error("Invalid track data: %s", err)
                continue
            results.append(audio)
        return pd.DataFrame(results)


# TODO: refractor to be pydantic with validation
# class SpotifyPlaylistModifier:
#    """SpotifyAuth returns access token from Spotify API."""
#    def __init__(self):
#
#        def create_playlist(self, name):
#            """
#            :param name (str): New playlist name
#            :return playlist (Playlist): Newly created playlist
#            """
#            data = json.dumps(
#                {"name": name, "description": "Recommended songs", "public": True}
#            )
#            url = f"https://api.spotify.com/v1/users/{self.user_id}/playlists"
#            response = self._place_post_api_request(url, data)
#            response_json = response.json()
#            playlist_id = response_json["id"]
#            # TODO: add playlist schema
#            #playlist = Playlist(name, playlist_id)
#            return playlist_id
#
#        #def populate_playlist(self, playlist, tracks):
#        #    """Add tracks to a playlist.
#        #    :param playlist (Playlist): Playlist to which to add tracks
#        #    :param tracks (list of Track): Tracks to be added to playlist
#        #    :return response: API response
#        #    """
#        #    track_uris = [track.create_spotify_uri() for track in tracks]
#        #    data = json.dumps(track_uris)
#        #    url = f"https://api.spotify.com/v1/playlists/{playlist.id}/tracks"
#        #    response = self._place_post_api_request(url, data)
#        #    response_json = response.json()
#        #    return response_json


# class SpotifyRecommender:
#    """SpotifyAuth returns recommendations from Spotify API."""
#
#    def __init__(self):
#
#        def get_spotify_username(self):
#            response = requests.get(
#                "https://api.spotify.com/v1/me", headers=self.headers_authentication
#            )
#            print(response.json())
#
#        ## TODO: add new release, similar artist, listening history
#        #def get_last_played_tracks(self, limit=10):
#        #    """Get the last n tracks played by a user
#        #    :param limit (int): Number of tracks to get. Should be <= 50
#        #    :return tracks (list of Track): List of last played tracks
#        #    """
#        #    url = f"https://api.spotify.com/v1/me/player/recently-played?limit={limit}"
#        #    response = self._place_get_api_request(url)
#        #    response_json = response.json()
#        #    print()
#        #    tracks = [
#        #        Track(
#        #            track["track"]["name"],
#        #            track["track"]["id"],
#        #            track["track"]["artists"][0]["name"],
#        #        )
#        #        for track in response_json["items"]
#        #    ]
#        #    return tracks
#        #def get_track_recommendations(self, seed_tracks, limit=50):
#        #    """Get a list of recommended tracks starting from a number of seed tracks.
#        #    :param seed_tracks (list of Track): Reference tracks to get recommendations. Should be 5 or less.
#        #    :param limit (int): Number of recommended tracks to be returned
#        #    :return tracks (list of Track): List of recommended tracks
#        #    """
#        #    seed_tracks_url = ""
#        #    for seed_track in seed_tracks:
#        #        seed_tracks_url += seed_track.id + ","
#        #    seed_tracks_url = seed_tracks_url[:-1]
#        #    url = f"https://api.spotify.com/v1/recommendations?seed_tracks={seed_tracks_url}&limit={limit}"
#        #    response = self._place_get_api_request(url)
#        #    response_json = response.json()
#        #    tracks = [
#        #        Track(track["name"], track["id"], track["artists"][0]["name"])
#        #        for track in response_json["tracks"]
#        #    ]
#        #    return tracks


# ## move to helpers bc can use it also for auth and data
# def _place_get_api_request(self, url):
#     response = requests.get(
#         url,
#         headers={
#             "Content-Type": "application/json",
#             "Authorization": f"Bearer {self._authorization_token}",
#         },
#     )
#     return response
# def _place_post_api_request(self, url, data):
#     response = requests.post(
#         url,
#         data=data,
#         headers={
#             "Content-Type": "application/json",
#             "Authorization": f"Bearer {self._authorization_token}",
#         },
#     )
#     return response
