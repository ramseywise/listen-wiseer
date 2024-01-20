import os
from dotenv import load_dotenv

load_dotenv(".env")
client_id = os.getenv("CLIENT_ID")
client_secret = os.getenv("CLIENT_SECRET")
user_id = os.getenv("USER_ID")
scope = os.getenv("SCOPE")

# endpoints
redirect_uri = "http://localhost:8000/callback"
auth_url = "https://accounts.spotify.com/authorize"
redirect_uri = "http://localhost:8000/callback"
token_url = "https://accounts.spotify.com/api/token"
refresh_token = ""
