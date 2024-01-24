import logger
import requests
from flask import Flask
from modeling.utils.const import *

# from api.spotify_client import *
# from api.spotify_auth import *
# from api.data.spotify_playlists import *
from api.data.playlists import *

log = logger.get_logger("app")

# config app
app = Flask(__name__)
app.secret_key = client_secret

# initiate spotify client
# spAuth = SpotifyAuth(client_id, client_secret, redirect_uri, token_url)
# spApi = SpotifyPlaylistApi()
spData = SpotifyPlaylistData()


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
    """Request Spotify API to return dfs for my playlists."""

    my_tracks = spData.update_spotify_features()
    df = spData.update_playlist_data(my_tracks)

    return redirect("/eda")


#    # refresh access token to make new api requests is not inheriting session
#    access_token = spAuth.get_access_token()
#    headers = {"Authorization": "Bearer {token}".format(token=access_token[0])}
#    print(headers)
#
#    log.info(f"Loading Spotify playlists")
#    for playlist_id, playlist_name in playlists.items():
#        # return my playlists' track features
#        tracks = spApi.request_track_features(headers, playlist_id)
#        my_tracks = spData.return_my_tracks(tracks, playlist_id, playlist_name)
#
#        # update audio features
#        filtered_track_ids = spData.filter_new_audio_features(my_tracks)
#        if len(filtered_track_ids) > 0:
#            new_audio_features = spApi.request_audio_features(
#                headers, filtered_track_ids
#            )
#            _ = spData.append_new_audio_features(new_audio_features)
#
#        # update artists features
#        filtered_artist_ids = spData.filter_new_artist_features(my_tracks)
#        if len(filtered_track_ids) > 0:
#            new_artists = spApi.request_artist_features(headers, filtered_artist_ids)
#            _ = spData.append_new_artist_features(new_artists)
#
#        # update playlist dfs
#        playlist_df = spData.merge_audio_features(my_tracks)
#        playlist_df = spData.merge_artist_features(playlist_df)
#        playlist_df = spData.update_playlist_data(playlist_df, playlist_name)
#
#        # TODO: verify data with schema - should it be final playlists or when requests are made :/
#        # TODO: change from csv to DB;
#        # TODO: add historical table of playlist tracks with column if track was deleted from the playlist (ie to filter future recommendations)
#        # TODO: also tables for liked, recently listened to (API requests)
#    log.info("Playlists updated successfully!")
#    return redirect("/eda")


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
