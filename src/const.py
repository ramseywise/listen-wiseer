# from pydantic import BaseSettings

## NOTE: This is getting ridiculously long, also put with model version???
audio_features = [
    "id",
    "key",
    "mode",
    "danceability",
    "energy",
    "loudness",
    "speechiness",
    "acousticness",
    "instrumentalness",
    "liveness",
    "valence",
    "tempo",
]
audio_features_list = [
    "id",
    "danceability",
    "energy",
    "loudness",
    "speechiness",
    "acousticness",
    "instrumentalness",
    "liveness",
    "valence",
    "tempo",
    "duration_ms",
    "time_signature",
    "key",
    "mode",
]

num_features = [
    "danceability",
    "energy",
    "loudness",
    "speechiness",
    "acousticness",
    "instrumentalness",
    "liveness",
    "valence",
    "tempo",
    "popularity",
]
cat_features = [
    "decade",
    "key_mode"
    # "genre",
]

features = ["id"] + num_features + cat_features

my_genres = [
    "ambient",
    "rock",
    "jazz",
    "blues",
    "folk",
    "indie",
    "house",
    "electronica",
    "lo-fi",
    "alternative rock",
    "bossa nova",
    "soul",
    "funk",
    "zouk",
    "bachata",
    "kizomba",
]

all_key_modes = [
    "C Minor",
    "Db Minor",
    "D Minor",
    "Eb Minor",
    "E Minor",
    "F Minor",
    "F# Minor",
    "G Minor",
    "Ab Minor",
    "A Minor",
    "Bb Minor",
    "B Minor",
    "C Major",
    "Db Major",
    "D Major",
    "Eb Major",
    "E Major",
    "F Major",
    "F# Major",
    "G Major",
    "Ab Major",
    "A Major",
    "Bb Major",
    "B Major",
]

all_decades = [
    "1950s",
    "1960s",
    "1970s",
    "1980s",
    "1990s",
    "2000s",
    "2010s",
    "2020s",
]

cat_cols = my_genres + all_key_modes + all_decades

dance_playlists = {
    "0bSPcUdxDq7xbOVXTt0JT6": "zoukini",  # 1wqGHI2nMMUarvo79ptIxh
    "4oBTLUak282wPIZKxge1EA": "kizombamama",  # 5hqTEgPgI3rpxu3mHegHcU
    "0HQjD6fO1LLO1yFqrqLDTb": "¡zapatos! ¡zapatos!",  # 61PZdnZQTNSgi2LVapULAE
}
acoustic_playlists = {
    "0eRuzZsUFgsX2LH8Ik3aih": "lady stardust",
    "5T5rQUgCGCsqRx6utNZ7BU": "hollow sound of morning chimes",
    "7lTZ9kdDXhD5QFwen86pY3": "kozmic blues",
    "1ipYsue7fX009BDxTX43pN": "pink moon",
    "3OKp4BoFeq3pw7yxI1ODG9": "lebanese blonde",
    "3dpEckOnvB7vqVM3r8j7t4": "pajarito del amor",
}
instrumental_playlists = {
    "7gKjRHhX5yQ2L2TZiLB8u3": "sinnerman",
    "2CDlU9jQQ6G1HaSMYulgP0": "feelin' good",
    "0ysvvFavIycXfwrzut4VXC": "bossa nova",
    "7p39CDlkJpp9P2FuBBxARh": "bitches brew",
    "0ZU9aRVIabSFCa0AORq9HK": "nightbirds",
    "6JHE9jVMah3rVa8im2H83v": "searching for the moon",
}
electronic_playlists = {
    "2KxAE0Fs33W4YhnGG7NmxQ": "champagne problems",
    "60tFx9tLxSalVDLzrfH5hT": "acid blues",
    "6Lk4TJuAdVQ7oL3Hay9jDu": "avril 14th",
    "689ZvTECXnNCrenbjv9YJN": "cooking with palms trax",
}
playlists = {
    **electronic_playlists,
    **instrumental_playlists,
    **acoustic_playlists,
    **dance_playlists,
}

playlist_group_dict_4 = {
    "dance": [
        "kizombamama",
        "¡zapatos! ¡zapatos!",
        "zoukini",
    ],
    "electronic": [
        "cooking with palms trax",
        "champagne problems",
        "acid blues",
    ],
    "instrumental": [
        "avril 14th",
        "bossa nova",
        "bitches brew",
        "searching for the moon",
    ],
    "acoustic": [
        "sinnerman",
        "feelin' good",
        "nightbirds",
        "kozmic blues",
        "pink moon",
        "lebanese blonde",
        "lady stardust",
        "hollow sound of morning chimes",
        "pajarito del amor",
    ],
}
playlist_group_dict = {
    "dance": [
        "kizombamama",
        "¡zapatos! ¡zapatos!",
        "zoukini",
    ],
    "electronic": [
        "cooking with palms trax",
        "champagne problems",
        "acid blues",
    ],
    "ambient": [
        "avril 14th",
    ],
    "jazz": [
        "bossa nova",
        "bitches brew",
        "searching for the moon",
    ],
    "r&b": [
        "feelin' good",
        "sinnerman",
        "nightbirds",
    ],
    "acoustic": [
        "kozmic blues",
        "pink moon",
        "lady stardust",
        "lebanese blonde",
        "hollow sound of morning chimes",
        "pajarito del amor",
    ],
}
order = [
    "1920s",
    "1930s",
    "1940s",
    "1950s",
    "1960s",
    "1970s",
    "1980s",
    "1990s",
    "2000s",
    "2010s",
    "2020s",
]
