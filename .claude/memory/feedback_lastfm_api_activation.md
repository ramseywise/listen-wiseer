---
name: Last.fm API key activation
description: Last.fm API keys require manual approval — error 10 means pending, not wrong key
type: feedback
---

Last.fm API keys return error 10 ("Invalid API key") even when the key format is correct if the account/app hasn't been manually approved yet. This is NOT an OAuth or cache issue — there is no OAuth flow for Last.fm read-only endpoints like `track.getTopTags` or `track.getInfo`. Just wait for activation email.

**Why:** User initially thought it was a caching/auth issue like Spotify. It's a manual review queue.

**How to apply:** When Last.fm returns error 10 on a fresh key, tell the user to wait for Last.fm's activation email rather than debugging auth flow. The code is correct; the key is just pending.
