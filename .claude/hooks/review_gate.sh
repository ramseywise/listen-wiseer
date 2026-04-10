#!/usr/bin/env bash
# PreToolUse hook for Write|Edit — enforces show-before-apply for source files.
#
# Flow:
#   1. Claude calls Edit on src/foo.py
#   2. Hook blocks: "Show proposed change first"
#   3. Claude shows before/after code block in conversation
#   4. User reviews and confirms
#   5. Claude runs: touch .claude/.edit_ok
#   6. Claude retries Edit → hook sees flag → allows → clears flag
#
# Scoped to code files outside .claude/ and tests/.
# .claude/ files and test files flow through without review.

path=$(echo "$CLAUDE_TOOL_INPUT" | jq -r '.file_path // empty')
[ -z "$path" ] && exit 0

# Auto-allow: .claude/ internal files
echo "$path" | grep -qE '\.claude/' && exit 0

# Auto-allow: test files
echo "$path" | grep -qE '/tests/' && exit 0

# Only gate code files
echo "$path" | grep -qE '\.(py|yaml|yml|toml|json|sh)$' || exit 0

# Check approval flag — if set, allow this edit and clear
if [ -f ".claude/.edit_ok" ]; then
  rm -f .claude/.edit_ok
  exit 0
fi

# Block with review instruction
cat >&2 <<'MSG'
Review gate: show the proposed change as a before/after code block.
After user confirms, run: touch .claude/.edit_ok
Then retry this edit.
MSG
exit 2
