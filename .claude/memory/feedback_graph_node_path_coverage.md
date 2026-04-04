---
name: Graph node tests need path-context coverage, not just local I/O
description: Node-isolation tests can validate incorrect behavior when state varies by routing path; review must trace full paths
type: feedback
---

A node that sits after a conditional edge may receive qualitatively different state depending on which path led there. Testing the node in isolation with a single synthetic state only validates one path's contract.

**Why:** `confidence_gate` had a test `test_confidence_gate_sets_no_answer_when_no_chunks` (confident=True, graded_chunks=[]) that passed — but this exact state also describes the direct-path (chit_chat) case, where the gate should NOT fire. The test encoded the bug as correct behavior. The review caught it by tracing the full direct-path sequence, not just the node.

**How to apply:** For graph nodes that are reachable via multiple routing paths:
- Write at least one test per distinct path that reaches the node (retrieval path vs direct path)
- In the test name and docstring, identify which path is being exercised
- During review, trace each routing path end-to-end, not just individual nodes

The execute phase should also note when a node sits after a conditional merge point — that's the signal that path-context tests are needed.
