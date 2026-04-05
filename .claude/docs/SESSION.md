# SESSION.md — listen-wiseer

## Active docs

- **Plan**: `.claude/docs/plans/phase4a_agent_chainlit.md`
- **Research**: `.claude/docs/research/infra_support.md`

## Current position

- **Phase 3a** (preprocessing pipeline): DONE — `src/recommend/preprocessing.py` complete, 450 tests
- **Phase 3b** (training pipeline): DONE — `src/paths.py`, `train.py` complete; models trained locally
  - `models/gmm_corpus.pkl`, `models/scaler_corpus.pkl`, `models/classifier_*.pkl` generated
  - `data/cache/corpus_features.parquet` generated (includes `t2v_0..t2v_63` columns)
  - Track2Vec embeddings stored in `track_embeddings` DuckDB table and joined into corpus
  - `embedding_similarity` now computed at inference via `_add_embedding_similarity` in pipelines
- **Phase 3c** (LangGraph agent + Chainlit): NOT STARTED — next
- **Tests**: 247 passed, 3 skipped (2026-04-04)
- **Last updated**: 2026-04-05

## Token log

| Date | Start | End | Turns | Compacted? |
|------|-------|-----|-------|------------|
| 2026-04-02 | — | — | — | yes (context overflow) |
| 2026-04-03 | — | — | — | no |
| 2026-04-04 | — | — | — | yes |

## Active gotchas

- **Git LFS blocker**: other env doesn't have git-lfs installed — `listen_wiseer.db` (tracked via LFS) won't pull correctly. Options: install git-lfs there, or migrate DB to object storage (S3/R2). Unresolved — decision deferred.
- `models/` and `data/cache/` are gitignored — must regenerate after every pull:
  1. (One-time) compute Track2Vec: `PYTHONPATH=src uv run python -c "from etl.db import ...; compute_track2vec..."`
  2. `PYTHONPATH=src uv run python -m recommend.train`
- `RecommendationEngine` raises `FileNotFoundError` at init if pkls missing. `server.py` wraps with try/except. Any new tool entrypoint must do the same.
- `src/agent/` is an empty directory — Phase 3c creates the scaffold.
- `audio-features` Spotify endpoint is dead (403, deprecated 2025 for all apps).
- Last.fm key (`LAST_FM_API_KEY`) pending activation (error 10). Genre fill for 229 tracks with NULL `first_genre` blocked until key activates.
- `build_feature_matrix` requires a writable connection (not `read_only=True`) because `init_schema` refreshes the `track_profile` view with `CREATE OR REPLACE VIEW`.
- `embedding_similarity` is 0.0 for artist/playlist/genre pipelines (centroid-based, no single seed track). Only populated for `TrackPipeline` where `seed_id` is a track ID.

## Open questions / blockers

- **Git LFS / DB portability** — other deployment env has no git-lfs. Decide: install lfs there vs. object storage.
- **Last.fm key activation** — pending. Once active: `PYTHONPATH=src uv run python -m etl.sync --playlists 0 --lastfm-limit 50`
- Phase 4 (RAG): needs `TAVILY_API_KEY` — confirm before executing.

## Next session prompt

```
We're in listen-wiseer, starting Phase 3c (LangGraph agent + Chainlit UI).
See `.claude/docs/plans/phase3c_agent_chainlit.md` for the full plan.

Phase 3a and 3b are complete:
- preprocessing.py: build_feature_matrix with Track2Vec, ENOA, imputation cascade
- train.py: GMM + scaler + per-playlist LightGBM classifiers; corpus parquet with t2v columns
- pipelines.py: _add_embedding_similarity wired into all 4 pipelines before rerank
- 247 tests passing, 3 skipped

Active gotchas:
- models/ and data/cache/ are gitignored — regenerate after pull (Track2Vec then train)
- Other env has no git-lfs — DB portability unresolved
- src/agent/ is empty — Phase 3c creates the scaffold
- RecommendationEngine raises FileNotFoundError if models missing; wrap in try/except

Start with: /start then read phase3c_agent_chainlit.md plan before executing.
```

_compact: 2026-04-04_
