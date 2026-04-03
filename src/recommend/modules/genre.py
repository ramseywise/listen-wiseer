"""ENOA spatial proximity filtering. Genre name -> ENOA coordinates -> filtered corpus zone."""

from pathlib import Path

import polars as pl


def load_genre_map(path: Path) -> pl.DataFrame:
    """Load genre_xy.csv and return [first_genre, top, left] columns.

    Args:
        path: Path to genre_xy.csv (columns: first_genre, color, top, left).

    Returns:
        DataFrame with columns [first_genre, top, left].
    """
    df = pl.read_csv(path)
    return df.select(["first_genre", "top", "left"])


def genre_to_enoa(
    genre_name: str,
    genre_map: pl.DataFrame,
    fuzzy: bool = True,
) -> tuple[float, float] | None:
    """Return (top, left) ENOA coordinates for a genre name, or None if not found.

    Tries exact (case-insensitive) match first. If fuzzy=True and no exact match,
    falls back to case-insensitive substring match returning the first hit.

    Args:
        genre_name: Genre name to look up.
        genre_map: DataFrame with [first_genre, top, left] columns.
        fuzzy: Whether to attempt substring match if exact match fails.

    Returns:
        Tuple of (top, left) floats, or None if no match found.
    """
    name_lower = genre_name.lower().strip()

    # Exact case-insensitive match
    exact = genre_map.filter(pl.col("first_genre").str.to_lowercase() == name_lower)
    if len(exact) > 0:
        row = exact.row(0, named=True)
        return (float(row["top"]), float(row["left"]))

    if not fuzzy:
        return None

    # Substring match
    fuzzy_match = genre_map.filter(
        pl.col("first_genre").str.to_lowercase().str.contains(name_lower)
    )
    if len(fuzzy_match) > 0:
        row = fuzzy_match.row(0, named=True)
        return (float(row["top"]), float(row["left"]))

    return None


def filter_by_enoa_proximity(
    corpus: pl.DataFrame,
    center: tuple[float, float],
    radius: float = 1500.0,
) -> pl.DataFrame:
    """Return corpus rows within Euclidean radius of the given ENOA center point.

    Adds an 'enoa_distance' column and sorts ascending by distance.
    corpus must have 'top' and 'left' columns.

    Args:
        corpus: DataFrame with 'top' and 'left' columns.
        center: (top, left) center of the search zone.
        radius: Maximum Euclidean distance to include.

    Returns:
        Filtered DataFrame with 'enoa_distance' column, sorted ascending.
    """
    if len(corpus) == 0:
        return corpus.with_columns(pl.lit(0.0).alias("enoa_distance")).filter(
            pl.lit(False)
        )

    center_top, center_left = center

    result = (
        corpus.with_columns(
            (
                (
                    (pl.col("top") - center_top) ** 2
                    + (pl.col("left") - center_left) ** 2
                )
                ** 0.5
            ).alias("enoa_distance")
        )
        .filter(pl.col("enoa_distance") <= radius)
        .sort("enoa_distance")
    )
    return result


def expand_genre_zone(
    genre_name: str,
    genre_map: pl.DataFrame,
    corpus: pl.DataFrame,
    radius: float = 1500.0,
) -> pl.DataFrame:
    """Convenience wrapper: genre name -> ENOA zone of corpus tracks.

    Returns empty DataFrame (does not raise) if the genre is not found.

    Args:
        genre_name: Genre name to look up.
        genre_map: DataFrame with [first_genre, top, left] columns.
        corpus: DataFrame with 'top' and 'left' columns.
        radius: Maximum Euclidean distance for zone membership.

    Returns:
        Filtered corpus within the genre zone, with 'enoa_distance' column.
        Empty DataFrame if genre not found.
    """
    center = genre_to_enoa(genre_name, genre_map, fuzzy=True)
    if center is None:
        return corpus.clear()
    return filter_by_enoa_proximity(corpus, center, radius)
