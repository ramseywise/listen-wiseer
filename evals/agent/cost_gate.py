"""Env-var-driven cost gate for LLM-calling eval tiers.

Reads from the CONFIRM_EXPENSIVE_OPS env var so Makefile
targets can toggle it: CONFIRM_EXPENSIVE_OPS=true make eval-trajectory

All eval modules (including evals/graders/answer_eval.py) import from here.
"""

from __future__ import annotations

import os

CONFIRM_EXPENSIVE_OPS: bool = os.getenv("CONFIRM_EXPENSIVE_OPS", "").lower() in (
    "true",
    "1",
)
