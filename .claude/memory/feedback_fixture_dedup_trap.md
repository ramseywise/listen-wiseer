---
name: Test fixture dedup trap — use distinct field values
description: When code deduplicates on field values, fixtures sharing defaults silently collapse to 1 result
type: feedback
---

When the code under test deduplicates on a field (e.g. `(query, doc_url)` key), test fixtures that use default args will silently produce fewer results than expected — the test appears to work but is validating the wrong count.

**Why:** Happened twice in the golden dataset extractor: `test_bronze_extracts_all_resolved` and `test_output_file_is_valid_jsonl` both used `_make_ticket("t1"), _make_ticket("t2")` with identical default query + url — deduplicated to 1. Tests asserted `len == 2` and failed.

**How to apply:** Whenever testing code that deduplicates, groups, or filters by field value, use distinct field values in multi-item fixtures — never rely on a default shared across items. Add a comment explaining which field drives uniqueness.
