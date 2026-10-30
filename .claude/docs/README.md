# .claude/docs

Reference documentation for listen-wiseer. Plans are implementation-ready specs; research docs are decision support. Archive holds completed phases — useful for context, not active work.

---

## research/

Decision support docs. Start here before planning new work.

### music-agent/

| Doc | What it covers |
|---|---|
| [exploration-architecture.md](research/music-agent/exploration-architecture.md) | **Phase 7 design doc.** Spotify MCP server extraction, graph + intent refactor, exploration UX, implementation sequence |
| [recommender-design.md](research/music-agent/recommender-design.md) | Phase 2 recommender assessment: corpus characteristics, audio feature gaps, ENOA differentiator, Spotify API capabilities, RAG/websearch strategy |
| [peer-repos.md](research/music-agent/peer-repos.md) | Peer repo survey: spotify-ai-analytics, spotify-langgraph-agent, WikiSpotify-MCP — what they do better and what we should adopt |
| [spotify-repos.md](research/music-agent/spotify-repos.md) | Six Spotify repos studied for improvement ideas: ETL patterns, playlist tools, discovery flows |

### evaluation/

| Doc | What it covers |
|---|---|
| [eval-harness.md](research/evaluation/eval-harness.md) | Phase 5c eval harness research: LangFuse tracing, golden dataset design, intent/tool metrics |

---

## plans/

Active and upcoming implementation plans.

| Plan | Status | What it covers |
|---|---|---|
| [2026-10-30-repo-audit.md](plans/2026-10-30-repo-audit.md) | A–E ✓ · F data-gated | Backlog completeness + local production readiness: fresh clone, docs, dep diet, coverage, Docker; carries S3b reranker |
| [2026-10-30-player-app.md](plans/2026-10-30-player-app.md) | PLAN DRAFTED | Player app — own "Spotify" on top of Navidrome |

---

## archive/

Completed phase plans (phases 1–9, incl. `2026-10-28-free-music-stack.md`) and superseded research. Read-only reference.
