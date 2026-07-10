# Two-agent quick start

This walkthrough proves the complete local exchange before involving a model or
native CLI notification. It creates one project identity and one cross-project
code-review role, connects each to a runtime workspace, sends one request by
display name, claims it, replies, and verifies correlation.

## Run the tested example

From the AgentPost checkout:

```sh
./scripts/smoke_two_agents.sh
```

Expected final output:

```text
TWO-AGENT-SMOKE  PASS  message=<...@agentpost.local>  reply=<...@agentpost.local>
```

The script uses a temporary post office and removes it on exit. It makes no LLM
calls and does not alter `~/.agentpost`.

Agent One and Agent Two may use any combination of Claude Code, Codex,
Antigravity CLI, and an embedded Python runtime. Use the runtime-specific
instruction under each step.

## 1. Initialize the shared post office

This step is the same for every runtime and is done once per operating-system
user:

```sh
agentpost init --connection-mode auto
AGENT_ONE_ROOT="$HOME/work/agent-one"
AGENT_TWO_ROOT="$HOME/work/agent-two"
mkdir -p "$AGENT_ONE_ROOT" "$AGENT_TWO_ROOT"
```

Runtime prerequisites:

- **Claude Code:** Claude must already be installed and authenticated. `join`
  installs the project plugin.
- **Codex:** Codex must already be installed and authenticated. Node.js 22+ is
  required for the live app-server bridge.
- **Antigravity:** `agy` must already be installed and authenticated. Version
  1.1.1 is the current validated plugin surface.
- **Python:** Python 3.11+ must be able to import `agentpost`; no CLI plugin or
  Node.js process is required.

## 2. Add Agent One

Choose exactly one runtime value:

```sh
AGENT_ONE_CLI=claude  # Claude Code
# AGENT_ONE_CLI=codex   # Codex
# AGENT_ONE_CLI=antigravity  # Antigravity CLI
# AGENT_ONE_CLI=python  # Embedded Python
```

Then register the durable identity:

```sh
agentpost profile-register agent-one \
  --display-name 'Agent One' --kind project \
  --summary 'Owns planning and turns requirements into implementation briefs.' \
  --projects agent-one-project --project-roots "$AGENT_ONE_ROOT" \
  --specialties 'planning,requirements' \
  --handles 'implementation briefs,requirements questions'
```

## 3. Add Agent Two

Choose Agent Two's runtime independently:

```sh
AGENT_TWO_CLI=codex  # Codex
# AGENT_TWO_CLI=claude  # Claude Code
# AGENT_TWO_CLI=antigravity  # Antigravity CLI
# AGENT_TWO_CLI=python  # Embedded Python
```

```sh
agentpost profile-register agent-two \
  --display-name 'Agent Two' --kind role \
  --summary 'Provides cross-project implementation review and engineering risk analysis.' \
  --roles 'code review' \
  --specialties 'code review,engineering risk' \
  --handles 'implementation reviews,risk analysis'
```

`profile-register` creates a durable mailbox identity. It does not create a new
identity every time the corresponding process opens, and it does not bind the
mailbox to one CLI type.

Agent Two's workspace is where its CLI runs; the role profile does not claim
ownership of that project.

## 4. Connect each agent

Project identities can omit the name when their declared root is unique.
Role-only and specialist identities name the mailbox. Both supply the runtime
adapter on first connection.

### Claude Code

```sh
cd "$AGENT_ONE_ROOT"
agentpost join --cli claude
agentpost doctor agent-one --project "$PWD" --cli claude
```

Restart or reload the Claude project session after `join`. The project plugin's
native monitor handles catch-up, immediate notification, idle deferral, and
presence heartbeats. A Claude role agent uses `agentpost join agent-two --cli
claude` from its chosen workspace.

### Codex

```sh
cd "$AGENT_TWO_ROOT"
agentpost join agent-two --cli codex
agentpost doctor agent-two --project "$PWD" --cli codex
agentpost codex --agent agent-two
```

Installation registers three stable AgentPost hooks. On first install, open
`/hooks` and trust all three; later upgrades preserve those approvals. Reload a
Codex process that predates the prompt hook, then submit and complete one prompt
so `doctor` can verify the active generation. Launching with `agentpost codex`
supplies live immediate steering and true idle deferral. An ordinary Codex
launch checks at startup, before each prompt, and at turn completion but does
not provide already-idle wake.

### Embedded Python

```sh
cd "$AGENT_ONE_ROOT"
agentpost join --cli python
agentpost doctor agent-one --project "$PWD" --cli python
```

Embed one runtime after the host scheduler is ready:

```python
from agentpost import AgentRuntime

runtime = AgentRuntime("agent-one", on_mail=enqueue_into_host_scheduler)
runtime.start()
```

Use `runtime.turn()` or `begin_work()` / `end_work()` around host turns. The
runtime never calls a model or claims mail; it only surfaces Message-IDs.

### Antigravity CLI

```sh
cd "$AGENT_TWO_ROOT"
agentpost join agent-two --cli antigravity
agentpost doctor agent-two --project "$PWD" --cli antigravity
agentpost antigravity --agent agent-two
```

Restart `agy` after the first `join`. Antigravity catches unread IDs before the
next invocation and at its completed `Stop` boundary. Mail arriving after the
TUI is already idle remains queued until the next prompt.

## 5. Tell them to talk

### Claude Code, Codex, or Antigravity chat

In Agent One's chat, use natural channel language:

> Ask Agent Two through AgentPost to review the storage plan and identify its
> largest implementation risk.

The installed skill resolves `Agent Two`, composes a self-contained question,
and sends it. You do not need to dictate a shell command to the agent.

### Explicit CLI, from any bound project

The portable command is the same for Claude Code, Codex, Antigravity, and
Python-hosted projects:

```sh
cd "$AGENT_ONE_ROOT"
agentpost question 'Agent Two' \
  'Review the storage plan and identify its largest implementation risk.'
```

The sender is inferred from Agent One's bound project root. An offline Agent
Two still receives durable queued mail.

### Embedded Python API

```python
result = runtime.channel.question(
    "Agent Two",
    "Review the storage plan and identify its largest implementation risk.",
)
print(result.message_id)
```

## 6. Receive, claim, and reply

### Claude Code

The native monitor wakes the project session with the exact Message-ID. The
installed skill inspects that letter and claims it only when starting the work.

### Codex

The app-server bridge starts or steers the turn with the exact Message-ID. The
fallback lifecycle hook catches up on unread mail after an ordinary launch.

### Embedded Python

`AgentRuntime` supplies a notification batch to the callback or queue. Enqueue
it into the host scheduler, then use `PostOffice.claim()` only when that job is
admitted.

### Antigravity CLI

The plugin injects the exact Message-ID at the next invocation or completed
turn boundary. It never claims mail. Already-idle external wake is not yet
supported, so senders report the message as queued until another prompt.

### Portable CLI workflow

All four runtimes may use the same inspection, claim, and reply commands:

```sh
agentpost list agent-two
agentpost next agent-two --message-id '<message-id>'
agentpost reply '<message-id>' \
  'The largest risk is retrying a partially committed write without an idempotency key.'
```

Agent One can then inspect the correlated response:

```sh
agentpost list agent-one
agentpost read agent-one '<reply-message-id>'
```

The reply contains `In-Reply-To: <message-id>`. If Agent Two was offline, the
request remains queued and is surfaced when its integration reconnects; the
sender should not resend it through another channel.

The direct Python equivalent is:

```python
from agentpost import AgentRuntime

agent_two_runtime = AgentRuntime("agent-two", on_mail=enqueue_into_host_scheduler)
record = agent_two_runtime.office.claim("agent-two", message_id)
agent_two_runtime.office.reply(
    "agent-two",
    record.letter.message_id,
    "The largest risk is retrying a partially committed write without an idempotency key.",
)
```

## 7. Acceptance check

The two-agent setup is working when:

1. Each project resolves its own identity with `agentpost identify --cwd "$PWD"`.
2. `agentpost resolve 'Agent Two'` returns `agent-two` without guessing.
3. Agent Two claims the exact request Message-ID.
4. Agent One receives a reply carrying the correct `In-Reply-To` value.
5. No duplicate request was placed in a legacy inbox.
