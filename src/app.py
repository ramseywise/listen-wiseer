import logger
import requests
from flask import Flask, redirect, session

from config import *
from api.playlists import *
from api.spotify_client import SpotifyAuth

# from modeling.models.cosine import *

log = logger.get_logger("app")

# config app
app = Flask(__name__)
app.secret_key = client_secret

sp = SpotifyAuth(client_id, client_secret, redirect_uri, token_url)

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
def get_access_token():
    """Return authorization code to exchange for session access token."""
    access_token = sp.get_access_token()
    print(access_token)
    return redirect("/data")


@app.route("/data")
def return_playlist_data():
    headers = {"Authorization": "Bearer {token}".format(token=session["access_token"])}

    for k, v in playlists.items():
        log.info(f"Loading {v}")

        # sp.refresh_access_token()
        df = return_full_playlist_df(headers, k, v)
        if df.popularity.isnull().sum() > 0:
            log.info(v + " is still missing artist features!")
        else:
            log.info(v + " updated successfully!")
    return redirect("/eda")


# @app.route("/eda")
# def analyze_playlist_genres():
#    # TODO: when updated successfully, run analysis and update genre map
#
#    return redirect("/model")
#
#
## TODO: once playlist is loaded, run playlist analysis, then update genre map


# @app.route("/recommend")
# def recommend_new_tracks():
#    log.info("Loading playlist data")
#    headers = {"Authorization": "Bearer {token}".format(token=session["access_token"])}
#    playlist_id = "0N1llBQMoJX2d9BW3wKHIL"  # cosine similarity
#    df = return_playlist_features(headers, playlist_id)
#
#    #log.info("Begin data preprocessing")
#    #y = transform_feature_data(df)
#
#    log.info("Calculating cosine similarity")
#    model = Cosine_Similarity_Recommendation()
#    track_uris = model.return_track_uris(df)
#    data = json.dumps({"uris": list(set(track_uris))})
#
#    log.info("Posting recommended tracks to playlist")
#    headers = {"Authorization": "Bearer {token}".format(token=session["access_token"])}
#    response = requests.post(
#        f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
#        headers=headers,
#        data=data,
#    )
#    if response.status_code == 201:
#        return {"message": "Track added successfully!"}
#    else:
#        return {"error": response.json()}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
