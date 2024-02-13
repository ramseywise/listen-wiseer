# TODO: setup api calls to get new train data for content-based recommendation models - based on genre/artist per playlist



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
