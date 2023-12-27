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
    # "year",
    # "key",
    # "mode",
]
cat_features = [
    "decade",
    "key_mode",
    "genre",
]

features = ["id"] + num_features + cat_features

core_genres = ["jazz", "blues", "soul", "indie", "folk", "rock", "r&b"]

my_genres = [
    "alternative rock",
    "electronica",
    "downtempo",
    "house",
    "ambient",
    "lo-fi beats",
    "bossa nova",
    "disco",
    "funk",
    "punk",
    "arab",
    "zouk",
    "kizomba",
    "bachata",
]

all_genres = core_genres + my_genres

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

cat_cols = all_genres + all_key_modes + all_decades

top_features = [
    "F# Major",
    "D Minor",
    "Bb Major",  # statistically significant
    "E Major",
    "B Major",
    "F Minor",  # statistically significant
    "acousticness",
    "valence",
    "popularity",
    "loudness",
    "tempo",
    "danceability",
    "energy",
    "speechiness",
    "instrumentalness",
    "r&b",
    "blues",
    "jazz",
    "arab",
    "folk",
    "rock",
    "alternative rock",
    "electronica",
    "ambient",
    "lo-fi beats",
    "punk",
    "1980s",
    "2010s",
    "Db Major",
    "G Minor",
    "Ab Major",  # statistically significant
    "valence",
    "zouk",
    "soul",
    "kizomba",
    "downtempo",
    "funk",
    "house",
    "disco",
    "folk",
    "indie",
    "bossa nova",
    "bachata",
]
# Loudness > -15
# energy < 0.6 unless bachata
# tempo > 100
# Danceability > 0.4
