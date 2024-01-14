import os
import requests
from datetime import datetime
from flask import Flask, request, redirect, jsonify, session
from dotenv import load_dotenv
from api.playlists import *
from modeling.models.cosine import *
import logger

log = logger.get_logger("app")

load_dotenv(".env")
client_id = os.getenv("CLIENT_ID")
client_secret = os.getenv("CLIENT_SECRET")
user_id = os.getenv("USER_ID")
scope = os.getenv("SCOPE")
redirect_uri = "http://localhost:8000/callback"

# endpoints
auth_url = "https://accounts.spotify.com/authorize"
redirect_uri = "http://localhost:8000/callback"
token_url = "https://accounts.spotify.com/api/token"
refresh_token = ""

# config app
app = Flask(__name__)
app.secret_key = client_secret


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
            return redirect("/data")


@app.route("/data")
def recommend_new_tracks():
    headers = {"Authorization": "Bearer {token}".format(token=session["access_token"])}

    dance_playlists = {
        "0bSPcUdxDq7xbOVXTt0JT6": "zoukini",  # 1wqGHI2nMMUarvo79ptIxh
        "4oBTLUak282wPIZKxge1EA": "kizombamama",  # 5hqTEgPgI3rpxu3mHegHcU
        "0HQjD6fO1LLO1yFqrqLDTb": "¡zapatos! ¡zapatos!",  # 61PZdnZQTNSgi2LVapULAE
    }
    playlists = {
        "7lTZ9kdDXhD5QFwen86pY3": "kozmic blues",
        "1ipYsue7fX009BDxTX43pN": "pink moon",
        "3OKp4BoFeq3pw7yxI1ODG9": "lebanese blonde",
        "0eRuzZsUFgsX2LH8Ik3aih": "lady stardust",
        "5T5rQUgCGCsqRx6utNZ7BU": "hollow sound of morning chimes",
    }

    for k, v in playlists.items():  # get set of ids from my_playlists.csv
        log.info(f"Loading {v}")
        df = return_full_playlist_df(headers, k, v)
        log.info(v + " updated successfully!")

    return redirect("/recommend")


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
