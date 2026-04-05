# SESSION.md — listen-wiseer

## Active docs

- **Plan**: `.claude/docs/plans/phase4b_memory.md`
- **Research**: `.claude/docs/research/infra_support.md`

## Current position

- **Phase 3a** (preprocessing pipeline): DONE — `src/recommend/preprocessing.py`
- **Phase 3b** (training pipeline): DONE — `src/paths.py`, `train.py`; models trained locally
  - `models/gmm_corpus.pkl`, `models/scaler_corpus.pkl`, `models/classifier_*.pkl` generated
  - `data/cache/corpus_features.parquet` (includes `t2v_0..t2v_63` columns)
  - Track2Vec in `track_embeddings` DuckDB table; `embedding_similarity` via `_add_embedding_similarity`
- **Phase 3c** (CatBoost): DONE — train/inference feature gap fixed, CatBoost comparison added (`f7f3474`)
- **Phase 3d** (EDA notebooks): DONE — 9 notebooks (`00`–`08`), `notebooks/old/` deleted
- **Phase 4a** (LangGraph agent + Chainlit): DONE — `src/agent/{state,tools,nodes,graph}.py`, `src/app/main.py` (`1c1ee5a`)
- **Phase 4b** (memory): NOT STARTED — next
- **Tests**: 280 passed, 3 skipped, 32 failed (all `duckdb.IOError` — missing LFS DB on this env, not regressions) (2026-04-05)
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
- `src/agent/` has Phase 4a scaffold (`state.py`, `tools.py`, `nodes.py`, `graph.py`) — no memory layer yet.
- `audio-features` Spotify endpoint is dead (403, deprecated 2025 for all apps).
- Last.fm key (`LAST_FM_API_KEY`) pending activation (error 10). Genre fill for 229 tracks with NULL `first_genre` blocked until key activates.
- `build_feature_matrix` requires a writable connection (not `read_only=True`) because `init_schema` refreshes the `track_profile` view with `CREATE OR REPLACE VIEW`.
- `embedding_similarity` is 0.0 for artist/playlist/genre pipelines (centroid-based, no single seed track). Only populated for `TrackPipeline` where `seed_id` is a track ID.

## Open questions / blockers

- **Git LFS / DB portability** — other deployment env has no git-lfs. Decide: install lfs there vs. object storage.
- **Last.fm key activation** — pending. Once active: `PYTHONPATH=src uv run python -m etl.sync --playlists 0 --lastfm-limit 50`
- Phase 4b (memory): needs `REDIS_URL` for cross-session persistence (Step 4.1). `InMemoryStore` for dev.
- Phase 5a (RAG): needs `TAVILY_API_KEY` — confirm before executing.

## Next session prompt

```
We're in listen-wiseer, starting Phase 4b (Long-Term Memory for ENOA).
See `.claude/docs/plans/phase4b_memory.md` for the full plan.

Phases 3a–4a are complete:
- ML pipeline: preprocessing → training → CatBoost comparison → EDA notebooks (00–08)
- Agent: LangGraph ReAct agent + Chainlit UI wired up (src/agent/, src/app/main.py)
- 280 tests passing, 3 skipped (32 duckdb.IOError failures = missing LFS DB, not regressions)

Active gotchas:
- models/ and data/cache/ are gitignored — regenerate after pull (Track2Vec then train)
- Other env has no git-lfs — DB portability unresolved
- RecommendationEngine raises FileNotFoundError if models missing; wrap in try/except
- 32 test failures are all duckdb.IOError — need LFS DB to resolve

Start with: /start then read phase4b_memory.md plan before executing.
```

_compact: 2026-04-04_

_compact: 2026-04-05 14:38_

_compact: 2026-04-05 14:51_

## Notebook Reorganization (2026-04-05)

Steps completed:
- Step 1: Extended `02_explore_library.ipynb` — artist genre tags (3b), popularity scatter (3c)
- Step 2: Extended `01_corpus_health.ipynb` — per-playlist centroid outliers (7b)
- Step 3: Extended `04_genre_clustering.ipynb` — gen_8 per playlist (6b), genre map health (9)
- Step 4: Extended `06_model_comparison.ipynb` — model registry, live N-model training, IF anomaly (§9), RFE feature selection (§10)
- Step 5: Created `08_sync.ipynb` — merged old/data_refresh + old/sync_preview
- Step 6: Verified old/ coverage — 5 notebooks fully ported, 5 have remaining unique views. Awaiting user decision on cleanup.
- Step 7: Ported remaining unique content — radar charts per gen_4 (§5c), multi-algorithm clustering with Davies-Bouldin (§4b), genre dendrogram (§10) to 04; per-playlist t-SNE (§10) to 05
- Step 8: Fixed bugs — find_similar dict→ndarray in 00/05, read_only→read_write for init_schema in 00
- Step 9: Installed git-lfs, pulled DB, generated enoa.csv, ran training (28 classifiers)
- Step 10: Ran all 8 notebooks (00-07) — all pass. 08_sync skipped (requires Spotify auth)
- Step 11: Deleted `notebooks/old/` — all high-value content ported
- Step 12: Added standard model dev diagnostics to `06_model_comparison.ipynb` — §10b KFold CV, §10c SMOTE comparison, §10d GridSearchCV (DT + LightGBM)
- Step 13: Added standard clustering diagnostics to `04_genre_clustering.ipynb` — §4c PCA scree, KMeans elbow, silhouette k-sweep
- Step 14: Fixed GridSearchCV Polars SchemaError — pandas fallback for cv_results_ with Object dtype columns
- Step 15: Re-ran notebooks 04 and 06 — both pass clean

_compact: 2026-04-05 15:16_

_compact: 2026-04-05 15:41_

_compact: 2026-04-05 18:18_

_compact: 2026-04-05 18:52_
