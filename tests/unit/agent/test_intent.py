"""Unit tests for music-domain query understanding.

Tests intent classification, entity extraction, query expansion,
decomposition, and confidence scoring.
"""

from __future__ import annotations

from agent.intent import (
    QueryAnalyzer,
    classify_intent,
    decompose_query,
    expand_query,
    extract_entities,
)

# =============================================================================
# Intent classification
# =============================================================================


class TestClassifyIntent:
    def test_classify_artist_info(self) -> None:
        result = classify_intent("who is Aphex Twin?")
        assert result["intent"] == "artist_info"
        assert result["confidence"] > 0.3

    def test_classify_artist_info_tell_me(self) -> None:
        result = classify_intent("tell me about Radiohead")
        assert result["intent"] == "artist_info"

    def test_classify_genre_info(self) -> None:
        result = classify_intent("what is bossa nova?")
        assert result["intent"] == "genre_info"

    def test_classify_genre_info_explain(self) -> None:
        result = classify_intent("explain the origins of zouk music style")
        assert result["intent"] == "genre_info"

    def test_classify_recommendation(self) -> None:
        result = classify_intent("recommend me tracks similar to Boards of Canada")
        assert result["intent"] == "recommendation"

    def test_classify_recommendation_suggest(self) -> None:
        result = classify_intent("suggest something like Radiohead")
        assert result["intent"] == "recommendation"

    def test_classify_history(self) -> None:
        result = classify_intent("what have I been listening to?")
        assert result["intent"] == "history"

    def test_classify_history_recently_played(self) -> None:
        result = classify_intent("show me my recently played tracks")
        assert result["intent"] == "history"

    def test_classify_chit_chat(self) -> None:
        result = classify_intent("hello!")
        assert result["intent"] == "chit_chat"

    def test_classify_chit_chat_thanks(self) -> None:
        result = classify_intent("thanks, that was great")
        assert result["intent"] == "chit_chat"

    def test_classify_explore_my_taste_top_artists(self) -> None:
        result = classify_intent("show me my top artists")
        assert result["intent"] == "explore_my_taste"

    def test_classify_explore_my_taste_top_tracks(self) -> None:
        result = classify_intent("what are my top tracks right now?")
        assert result["intent"] == "explore_my_taste"

    def test_classify_explore_my_taste_profile(self) -> None:
        result = classify_intent("what kind of music am I actually into?")
        assert result["intent"] == "explore_my_taste"

    def test_classify_discover_new_music(self) -> None:
        result = classify_intent("find me something new I haven't heard")
        assert result["intent"] == "discover"

    def test_classify_discover_surprise(self) -> None:
        result = classify_intent("surprise me with some music")
        assert result["intent"] == "discover"

    def test_classify_discover_expand_taste(self) -> None:
        result = classify_intent("I want to discover something new and underrated")
        assert result["intent"] == "discover"

    def test_history_not_reclassified_as_explore(self) -> None:
        result = classify_intent("show me my recently played tracks")
        assert result["intent"] == "history"

    def test_classify_default_fallback(self) -> None:
        """Unrecognized query falls back to artist_info with low confidence."""
        result = classify_intent("asdfghjkl zxcvbnm")
        assert result["intent"] == "artist_info"
        assert result["confidence"] <= 0.3


# =============================================================================
# Entity extraction
# =============================================================================


class TestExtractEntities:
    def test_extract_mood_entity(self) -> None:
        entities = extract_entities("suggest some chill tracks for studying")
        assert "mood" in entities
        assert "chill" in entities["mood"]

    def test_extract_time_period(self) -> None:
        entities = extract_entities("80s rock recommendations")
        assert "time_period" in entities
        assert "80s" in entities["time_period"]

    def test_extract_context(self) -> None:
        entities = extract_entities("workout playlist suggestions")
        assert "context" in entities
        assert "workout" in entities["context"]

    def test_extract_multiple_entities(self) -> None:
        entities = extract_entities("chill 90s tracks for studying")
        assert "mood" in entities
        assert "time_period" in entities
        assert "context" in entities

    def test_extract_no_entities(self) -> None:
        entities = extract_entities("who is Radiohead?")
        assert entities == {}


# =============================================================================
# Query expansion
# =============================================================================


class TestExpandQuery:
    def test_expand_adds_synonyms(self) -> None:
        original = "find me songs similar to Radiohead"
        result = expand_query(original)
        assert len(result) > len(original)

    def test_expand_no_match_passthrough(self) -> None:
        original = "who is Aphex Twin?"
        result = expand_query(original)
        assert result == original

    def test_expand_track_synonym(self) -> None:
        result = expand_query("find me a good track")
        assert any(syn in result for syn in ["song", "tune", "record"])


# =============================================================================
# Decomposition
# =============================================================================


class TestDecomposeQuery:
    def test_decompose_multi_question(self) -> None:
        subs = decompose_query("who is Radiohead and what genre are they?")
        assert len(subs) >= 2

    def test_decompose_single_passthrough(self) -> None:
        subs = decompose_query("who is Aphex Twin?")
        assert subs == ["who is Aphex Twin?"]

    def test_decompose_multiple_question_marks(self) -> None:
        subs = decompose_query("who is Radiohead? what genre are they?")
        assert len(subs) >= 2


# =============================================================================
# Confidence
# =============================================================================


class TestConfidence:
    def test_high_confidence_strong_match(self) -> None:
        """Multiple keyword hits → confidence > 0.5."""
        result = classify_intent(
            "recommend me tracks similar to Boards of Canada, find me something like them"
        )
        assert result["confidence"] > 0.5

    def test_low_confidence_weak_match(self) -> None:
        """No keyword hits → confidence ≤ 0.3."""
        result = classify_intent("asdfghjkl")
        assert result["confidence"] <= 0.3


# =============================================================================
# Full analyzer integration
# =============================================================================


class TestQueryAnalyzer:
    def test_analyzer_artist_info(self) -> None:
        analyzer = QueryAnalyzer()
        result = analyzer.analyze("who is Aphex Twin?")
        assert result.intent == "artist_info"
        assert result.original_query == "who is Aphex Twin?"

    def test_analyzer_recommendation_with_entities(self) -> None:
        analyzer = QueryAnalyzer()
        result = analyzer.analyze("suggest some chill tracks for studying")
        assert result.intent == "recommendation"
        assert "mood" in result.entities
        assert "chill" in result.entities["mood"]

    def test_analyzer_complexity_simple(self) -> None:
        analyzer = QueryAnalyzer()
        result = analyzer.analyze("who is Aphex Twin?")
        assert result.complexity == "simple"

    def test_analyzer_complexity_moderate_decompose(self) -> None:
        analyzer = QueryAnalyzer()
        result = analyzer.analyze("who is Radiohead and what genre are they?")
        assert result.complexity in ("moderate", "complex")

    def test_analyzer_disabled_features(self) -> None:
        analyzer = QueryAnalyzer(
            expand_terms=False, extract_entities_flag=False, decompose=False
        )
        result = analyzer.analyze("suggest some chill 80s tracks for workout")
        assert result.expanded_query == result.original_query
        assert result.entities == {}
        assert result.sub_queries == [result.original_query]
