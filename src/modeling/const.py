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
    "key_mode",
    #"genre",
]

features = ["id"] + num_features + cat_features

my_genres = [
    "ambient",
    "rock",
    "jazz",
    "blues",
    "folk",
    "arab",
    "indie",
    "house",
    "electronica",
    "downtempo",
    "lo-fi beats",
    "alternative rock",
    "bossa nova",
    "funk",
    "soul",
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
