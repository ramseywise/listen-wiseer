import logger
import requests
from flask import Flask
from modeling.utils.const import *
from api.spotify_client import *

# from api.data.playlists import *
from api.playlists_old import *

log = logger.get_logger("app")

# config app
app = Flask(__name__)
app.secret_key = client_secret

# initiate spotify client
spAuth = SpotifyAuth(client_id, client_secret, redirect_uri, token_url, session)
# spApi = SpotifyPlaylistApi()
# spData = SpotifyPlaylistData()


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
def return_playlist_data():
    """Return authorization code to exchange for session access token."""
    # refresh access token to make new api requests is not inheriting session
    access_token = spAuth.get_access_token()
    headers = {"Authorization": "Bearer {token}".format(token=session["access_token"])}
    print(access_token)

    for playlist_id, playlist_name in playlists.items():
        log.info(f"Loading {playlist_name}")
        df = return_full_playlist_df(headers, playlist_id, playlist_name)

    return redirect("/recommend")

    #        # update track features
    #        tracks = spApi.request_track_features(headers, playlist_id)
    #        my_tracks = spData.return_my_tracks(tracks, playlist_id, playlist_name)
    #
    #        # update audio features
    #        filtered_track_ids = spData.filter_new_audio_features(my_tracks)
    #        audio_features = spApi.request_audio_features(headers, filtered_track_ids)
    #
    #        # return artists features
    #        filtered_artist_ids = spData.filter_new_artist_features(headers, my_tracks)
    #        my_artists = spApi.request_artist_features(headers, filtered_artist_ids)

    # df = spData.merge_new_features(audio_features)

    # return as dataframe
    # df = pd.concat([my_tracks] + my_artists + audio_features, axis=1)
    # if df.popularity.isnull().sum() > 0:
    #    log.info(playlist_name + " is still missing artist features!")
    # else:
    #    log.info(playlist_name + " updated successfully!")

    return redirect("/eda")

    # df = sp.Data.merge_audio_features(audio_features)


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
