import requests
from flask import Flask
from utils.logger import *
from api.spotify_client import *
from api.data.playlists import *
from models.clustering import *

# config app
app = Flask(__name__)
app.secret_key = client_secret


spAuth = SpotifyAuth(client_id, client_secret, redirect_uri, token_url)
spData = SpotifyTrackFeatures()
spMix = CreateNewMixesApi()

log = get_logger("app")


@app.route("/")
def index():
    """return login page to give authorization permissions."""
    return "Welcome to Spotify App <a href='/login'>Login with Spotify</a>"


@app.route("/login")
def login():
    """Request authorization code to grant privileges."""
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": scope,
    }
    log.info("Requesting authorization code")
    response = requests.get(auth_url, params=params)

    return redirect(response.url)


@app.route("/callback")
def update_spotify_playlists():
    """Request Spotify API to return features for my playlists."""

    session = spAuth.get_access_token()
    headers = {"Authorization": "Bearer {token}".format(token=session["access_token"])}
    print(headers)

    spData.update_spotify_features(headers)
    spData.update_playlist_data()
    ## TODO: automate playlist analysis and update genre map

    log.info("Clustering data")
    remix = RemixRecommendation()
    track_uris = remix.return_track_uris()
    # NOTE: can only add 100 songs or set limit
    data = json.dumps({"uris": list(set(track_uris[:100]))})

    log.info("Posting recommended tracks to playlist")
    # session = spAuth.refresh_access_token(session)
    # new_access_token = session['access_token']
    # print(new_access_token)
    # headers = {"Authorization": "Bearer {token}".format(token=new_access_token)}
    # playlist_id = spMix.create_new_playlist("Zouk slow flow", headers)
    # TODO: put new playlist name and condition to save somewhere and later add user input
    playlist_id = "557eD2DZltDGnhRigKgwnK"  # test playlist
    spMix.update_tracks_to_playlist(playlist_id, data, headers)

    ## TODO: add recommendation workflow
    return redirect("/recommend")


# TODO: verify data with schema - should it be final playlists or when requests are made :/
# TODO: change from csv to DB;
# TODO: add historical table of playlist tracks with column if track was deleted from the playlist (ie to filter future recommendations)
# TODO: also tables for liked, recently listened to (API requests)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
