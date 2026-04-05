# Plan — Notebook Reorganization

Backfill missing views from `notebooks/old/` into the current `notebooks/` set,
extend model comparison to be modular, and merge the two sync notebooks.

> Notebooks live at `notebooks/*.ipynb` (flat, no `eda/` subfolder).

---

## Step 1: Extend `02_explore_library.ipynb` — Artist gaps

Add two new sections after the existing "3. Artist Stats" section:

**3b. Artist Genre Tag Vocabulary** (from `old/artist_eda`)
- Query `artists.genres` (raw Spotify tag strings), explode into individual tags
- Horizontal bar chart: top-25 artist genre tags by artist count
- Comparison note: how raw tags map to curated `gen_4`/`gen_8` taxonomy

**3c. Artist Popularity vs Track Count** (from `old/artist_eda`)
- Scatter plot: artist popularity (x) vs number of tracks in library (y)
- Color by `n_playlists` to show cross-playlist presence
- Annotate top outliers (high track count or high popularity)

---

## Step 2: Extend `01_corpus_health.ipynb` — Per-playlist outlier z-scores

Add a new section after existing "7. Outlier Detection":

**7b. Per-Playlist Centroid Outliers** (from `old/playlist_eda`)
- For each playlist: compute audio feature centroid, then Euclidean distance per track
- Table: top-20 most outlying tracks (track name, playlist, z-score distance)
- KDE histogram: outlier distance distribution by playlist (overlapping, colored)

---

## Step 3: Extend `04_genre_clustering.ipynb` — Genre map & gen_8 views

Add two new sections:

**After section 6 (Genre Coverage Gaps):**

**6b. gen_8 Composition per Playlist** (from `old/playlist_eda`)
- Stacked bar chart: playlist × gen_8 breakdown (row-normalized)
- Shows finer-grained genre character than the gen_4 heatmap in `02`

**After section 8 (Cross-Playlist Genre Overlap):**

**9. Genre Map Health** (from `old/playlist_eda`)
- Count tracks with unmapped `first_genre` (no `gen_4`/`gen_8`)
- Table: top unmapped genres by track count
- ENOA distance heatmap for top genre groups (pairwise centroid distances)

---

## Step 4: Extend `06_model_comparison.ipynb` — Modular multi-model pipeline

Restructure to support swappable models. Currently hard-codes LightGBM vs CatBoost
bar charts. New structure:

**Section 0 (new): Model Registry**
- Define a `MODEL_REGISTRY` dict mapping model names to sklearn-compatible estimators
- Include: LightGBM, CatBoost, LogisticRegression, DecisionTree, RandomForest, IsolationForest
- Each entry: `{"name": ..., "estimator": ..., "type": "classifier" | "anomaly"}`
- Single `evaluate_model()` function that trains, predicts, returns standardized metrics dict

**Section 1-2: Keep existing** — load JSONL metrics, filter to compare mode (for LGBM/Cat historical runs)

**Section 3 (rewrite): Per-Playlist Comparison — All Models**
- Loop over `MODEL_REGISTRY` classifiers, train each per-playlist
- Grouped bar chart: playlists × models × metric (generalized from the current 2-model version)
- Use the corpus + playlist labels directly (not just JSONL files)

**Section 4 (rewrite): Win/Loss Summary — All Models**
- Generalize current win/loss logic to N models
- Pivot table: models × metrics with mean values, best highlighted

**Section 5-6: Keep existing** box plots and correlation heatmaps (adapt to N models)

**Section 7 (new): Isolation Forest Anomaly Scoring**
- Train IF on full corpus audio features
- Histogram of anomaly scores
- Table: top-20 most anomalous tracks with feature values
- Compare anomaly labels vs playlist membership

**Section 8 (new): RFE Feature Selection Comparison**
- Run RFE on LR, DT, RF pipelines (from `old/classifiers`)
- Heatmap: features × models showing selected/not-selected
- Identifies which features each model family considers important

---

## Step 5: Create `08_sync.ipynb` — Merged sync workflow

Merge `old/data_refresh` + `old/sync_preview` into one notebook with clear sections:

**Part A: Preview (read-only)**
1. Spotify auth check — token status, `/v1/me` probe, force-refresh cell
2. DB state — table row counts, gap audit (missing audio features by playlist, missing artists)
3. Fetch playlists from API — with 1hr `/tmp` cache
4. Sync delta — `plan_sync()` output: new/stale/current/excluded classification
5. API call estimate — per-step call counts, total
6. Ignore list management — exclude/include playlist cells

**Part B: Sync (write path)**
7. Limits config — `MAX_PLAYLISTS`, `MAX_TRACKS`, `AUDIO_LIMIT`, `ARTIST_LIMIT`
8. Upsert playlists
9. Sync tracks (new/stale only)
10. Fill missing audio features
11. Fill missing artist data
12. Verify — final table counts + `track_profile` row count

---

## Step 6: Clean up `notebooks/old/`

After all views are ported:
- Verify each old notebook's unique outputs are covered in the new set
- Delete `notebooks/old/` directory (with user confirmation)

---

## Execution order

Steps 1-3 (EDA backfills) are independent and can be done in any order.
Step 4 (model comparison) is the largest change.
Step 5 (sync notebook) is independent.
Step 6 (cleanup) is last, after verification.
