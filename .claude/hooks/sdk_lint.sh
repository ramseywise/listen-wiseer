#!/usr/bin/env bash
# PostToolUse hook for Write|Edit — enforces Anthropic SDK best practices in src/
# Adapted for listen-wiseer: AsyncAnthropic client, factory in src/utils/client.py

path=$(echo "$CLAUDE_TOOL_INPUT" | jq -r '.file_path // empty')
[ -z "$path" ] && exit 0
echo "$path" | grep -qE '/src/.*\.py$' || exit 0

issues=""

# --- B1: No bare SDK client instantiation ---
# Only src/utils/client.py may call anthropic.Anthropic( or anthropic.AsyncAnthropic(
if ! echo "$path" | grep -qE 'utils/client\.py$'; then
  line=$(grep -n 'anthropic\.Anthropic(\|anthropic\.AsyncAnthropic(' "$path" 2>/dev/null | grep -v '# noqa' | head -1 || true)
  [ -n "$line" ] && issues="$issues  [sdk-factory] use factory from utils.client, not bare anthropic client: $line\n"
fi

# --- B2: No hardcoded model strings ---
# Allow in config.py, settings.py, and test files
if ! echo "$path" | grep -qE 'config\.py$|settings\.py$|/tests/'; then
  line=$(grep -nE 'model\s*=\s*"claude-' "$path" 2>/dev/null | grep -v '# noqa' | head -1 || true)
  [ -n "$line" ] && issues="$issues  [sdk-model] use settings for model names (e.g. settings.llm_model), not hardcoded strings: $line\n"
fi

# --- B3: Token usage logging (advisory) ---
has_api_call=$(grep -cE '\.messages\.create|\.ainvoke\(' "$path" 2>/dev/null || echo 0)
if [ "$has_api_call" -gt 0 ]; then
  has_usage=$(grep -cE 'usage|token' "$path" 2>/dev/null || echo 0)
  if [ "$has_usage" -eq 0 ]; then
    echo "Advisory: $path makes API calls but has no token usage logging" >&2
  fi
fi

if [ -n "$issues" ]; then
  printf "SDK lint violations in %s:\n%b" "$path" "$issues" >&2
  exit 2
fi

exit 0
