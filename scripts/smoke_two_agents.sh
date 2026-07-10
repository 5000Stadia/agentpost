#!/usr/bin/env bash
set -euo pipefail

AGENTPOST_BIN="${AGENTPOST_BIN:-agentpost}"
DEMO_ROOT="$(mktemp -d)"
POST_ROOT="$DEMO_ROOT/post"
AGENT_ONE_ROOT="$DEMO_ROOT/agent-one"
AGENT_TWO_ROOT="$DEMO_ROOT/agent-two"
trap 'rm -rf "$DEMO_ROOT"' EXIT

mkdir -p "$AGENT_ONE_ROOT" "$AGENT_TWO_ROOT"
AP=("$AGENTPOST_BIN" --root "$POST_ROOT")

"${AP[@]}" init --connection-mode auto >/dev/null
"${AP[@]}" profile-register agent-one \
  --display-name "Agent One" --cli python --kind project \
  --summary "Owns planning and turns requirements into implementation briefs." \
  --projects agent-one-project --project-roots "$AGENT_ONE_ROOT" \
  --specialties "planning,requirements" \
  --handles "implementation briefs,requirements questions" >/dev/null
"${AP[@]}" profile-register agent-two \
  --display-name "Agent Two" --cli python --kind role \
  --summary "Provides cross-project implementation review and engineering risk analysis." \
  --roles "code review" \
  --specialties "code review,engineering risk" \
  --handles "implementation reviews,risk analysis" >/dev/null

(cd "$AGENT_ONE_ROOT" && "${AP[@]}" join >/dev/null)
(cd "$AGENT_TWO_ROOT" && "${AP[@]}" join agent-two --cli python >/dev/null)

message_output="$({
  cd "$AGENT_ONE_ROOT"
  "${AP[@]}" message "Agent Two" \
    "Please review the storage plan and identify its largest implementation risk."
} 2>/dev/null)"
message_id="$(awk -F '\t' '$1 == "MESSAGE" {print $2}' <<< "$message_output")"
test -n "$message_id"

"${AP[@]}" next agent-two --message-id "$message_id" >/dev/null
reply_id="$({
  "${AP[@]}" reply agent-two "$message_id" \
    "The largest risk is retrying a partially committed write without an idempotency key."
} 2>/dev/null)"
test -n "$reply_id"

reply_text="$("${AP[@]}" read agent-one "$reply_id")"
grep -q "In-Reply-To: $message_id" <<< "$reply_text"
grep -q "From: agent-two" <<< "$reply_text"
grep -q "idempotency key" <<< "$reply_text"

printf 'TWO-AGENT-SMOKE\tPASS\tmessage=%s\treply=%s\n' \
  "$message_id" "$reply_id"
