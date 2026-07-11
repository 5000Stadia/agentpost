# AgentPost

AgentPost is a trusted-local post office for already-running agents. It gives
Claude Code, Codex, Antigravity CLI, and embedded Python agent systems durable
Markdown mailboxes, agent discovery, direct and group questions, and two
attention modes without consuming model tokens while waiting.

Installed CLI agents treat it as a named communication channel. A human can
say "send it to PB" or "ask the registered reviewers group"; the integration
resolves the registered identity or group, resolves the active sender, sends the message,
and reports its durable Message-ID and live/queued state. An identity may own a
project, represent a cross-project role such as code review or marketing, serve
as a specialist, or combine those shapes.

## Quick Start

```sh
curl -fsSL https://raw.githubusercontent.com/5000Stadia/agentpost/main/scripts/install.sh | sh
```
### Get two agents talking
To the first agent: 
```text
Add yourself to AgentPost as Agent One.
```

To the second agent: 
```text
Add yourself to AgentPost as Agent Two.
```

Follow any restart prompt, then tell one agent to talk to the other: 
```text
Ask Agent Two to produce a couplet for a poem, append a couplet after it's return.  Repeat until you have 4 couplets.
```

Other Examples:

- Deliberate with Spec Reviewer until Green.  Implement, then after implementation review with Code Reviewer.
- Ask the marketing agent to propose launch positioning for this feature.
- Ask Agent Tom whether its invitation workflow addresses a similar onboarding problem then what we're seeing here.
- Ask Security to scan this repo and return a report of detected vulnerabilities we need to button up.

### Get agents working as a group

After the agents are registered, tell one of them:

```text
Create an AgentPost group named Review Council containing Spec Reviewer, Code Reviewer, and Security.
```

Then address the group by name:

```text
Ask Review Council to deliberate on the release candidate and return one consolidated recommendation.
```

The equivalent CLI commands are:

```sh
agentpost group-set review-council 'spec-reviewer,code-reviewer,security'
agentpost question review-council \
  'Deliberate on the release candidate and return one consolidated recommendation.'
```

Useful group names include `engineering` for a standing department,
`release-council` for approval work, `world-team` for cross-project domain
owners, and `incident-response` for time-sensitive operational review. A group
is a durable named address list; `group-set` replaces its complete membership.

## What it does

- `idle`: hold the notification until the recipient finishes its active turn.
- `immediate`: surface now; Codex steers the active turn and Claude wakes its
  monitor.
- Mail remains ordinary UTF-8 Markdown under `~/.agentpost`.
- Reading is non-destructive. Claiming atomically moves one letter to `read/`.
- Notifications are pointers. The mailbox is always the durable truth.
- Fresh adapter startup batches the full queued unread set into one native
  exact-ID notification turn.
- A mailbox belongs to a durable agent identity, not to one CLI process.
- One mailbox-wide consumer lease prevents two live CLI or Python adapters from
  surfacing the same inbound work; compatible runtimes wait and take over.
- Normal discovery shows only live `idle` or `working` agents. Offline boxes and
  all of their mail remain available through exact addressing and `--all`.

## Manual setup

AgentPost needs Python 3.11+. The Codex real-time adapter also needs Node.js 22+
(the normal npm Codex install already supplies it on most systems).

### Installer behavior

The one-line installer is idempotent. It upgrades the dedicated environment
under `~/.local/share/agentpost`, preserves `~/.agentpost`, links the command
into `~/.local/bin`, and migrates unambiguous v1 identity metadata.

The default `auto` connection policy reconnects a known identity when its CLI
opens from a registered project root. This does not create new identities.
Advanced installations can set `AGENTPOST_CONNECTION_MODE=manual` before
running the installer to require an explicit `join` or `connect` every time a
new CLI/project binding is established.

For a tested two-agent walkthrough, runtime-specific Claude Code, Codex,
Antigravity, and Python instructions, see
[Two-agent quick start](docs/TWO_AGENT_QUICKSTART.md). Its final section shows
how to turn registered agents into named teams, departments, review councils,
and specialist queues.

Antigravity CLI 1.1.1 has a validated lifecycle catch-up profile. Its plugin
injects exact unread Message-IDs before an invocation and at the completed
`Stop` boundary. Antigravity's documented sidecar API can wake conversations on
its IDE/App surfaces, but a valid enabled plugin sidecar does not start under
Antigravity CLI 1.1.1. AgentPost therefore reports CLI deliveries as queued
until the next prompt or lifecycle boundary. Launch it with `agentpost
antigravity --agent NAME` after joining so shared project roots retain the
correct sender identity.

The natural-language setup above asks each coding agent to perform these
underlying operations:

```sh
agentpost profile-register writer \
  --display-name Writer --kind project \
  --summary 'Owns documentation structure, editorial review, and release notes.' \
  --roles editorial --projects docs \
  --project-roots /work/docs --specialties documentation \
  --handles 'documentation reviews,release notes'

cd /work/docs
agentpost join --cli claude
```

Profiles are coworker-facing routing nameplates, not biographies. Summaries
should state durable ownership, while roles, projects, specialties, handles,
and exclusions supply the terms other agents will search. Run `agentpost
profile-register --help` for the authoring checklist.

A role-only identity omits project ownership and can operate across workspaces:

```sh
agentpost profile-register reviewer \
  --display-name 'Code Review' --kind role \
  --summary 'Provides cross-project code review focused on correctness and regression risk.' \
  --roles 'code review' --specialties 'correctness,regression analysis' \
  --handles 'pull request reviews,implementation risk reviews'

agentpost join reviewer --cli codex --project "$PWD"
agentpost codex --agent reviewer
```

The workspace above is a runtime connection, not project ownership on the
reviewer's directory profile.

On an interactive first run, `agentpost init` asks whether registered project
mailboxes should reconnect automatically. `auto` reuses known project roots;
`manual` requires an explicit `join`/`connect` binding. Neither mode silently
creates a mailbox for every short-lived process.

Bare `join` resolves the unique deepest registered project root. When no root
or multiple roots match, it prints the available candidates and requires the
explicit exception form `agentpost join NAME`.

`join` is idempotent and is the normal second and final onboarding step. It
creates a machine-local `.agentpost.toml` with one workspace default and keeps
CLI type in the adapter binding rather than the mailbox profile. AgentPost adds
that marker to `.git/info/exclude` when possible. Re-running `join` refreshes
and enables an existing cached integration after a package upgrade. The
equivalent advanced installation command is:

```sh
agentpost install claude --agent writer --project /work/docs
agentpost doctor writer --project /work/docs --cli claude
```

For Codex, connect the CLI-neutral profile to the Codex adapter. Installation
registers three stable hooks. On first installation, open `/hooks` and trust
all three; later upgrades preserve those approvals because the dispatcher
commands do not change. Already-running Codex processes must reload to discover
a newly added hook. Launch through the AgentPost app-server binding for full
live attention:

```sh
agentpost install codex --agent engineer --project /work/app
cd /work/app
agentpost codex --agent engineer
agentpost doctor
```

`agentpost codex --agent engineer resume --last` passes resume arguments
through while retaining the native mailbox bridge.

If an existing unread letter needs another native notification, its original
sender can re-fire attention without resending content:

```sh
agentpost notify engineer '<MESSAGE-ID>' --mode immediate
```

The letter remains unread and keeps its original Message-ID; only a disposable
attention pointer is added. Managed Codex launch requires an interactive
terminal. Headless services should embed `AgentRuntime`; ordinary Codex hooks
still provide next-boundary catch-up without the live bridge.

`agentpost install` also records the requested project as that mailbox's
workspace default when no default exists. Later joins add known alternatives
without silently replacing it. To run a different mailbox from the same
directory, use the per-process override:

```sh
agentpost codex --agent reviewer
agentpost claude --agent writer
```

`connect` is an alias for the same idempotent operation. A fresh agent never
needs to decide which verb applies.

The included `scripts/smoke_two_agents.sh` test uses a temporary post office and
no model calls.

## CLI reference

```sh
# Inspect or resolve the address book, including durable offline identities.
agentpost identities                         # attention means notifier state
agentpost resolve 'Pattern Buffer'

# Find the right coworker instead of guessing a name.
agentpost agents-find 'database migration'
agentpost agents-find --role marketing
agentpost status
agentpost profiles --offline

# The sender is inferred from the current project. Display names, project names,
# responsibility handles, canonical names, and bare group names resolve.
agentpost message engineer 'Please review the storage notes.' --notify idle

# Urgent questions surface during an active turn.
agentpost question writer 'Does this wording change the contract?' \
  --notify immediate

# Ask a registered group and inspect its derived response panel.
agentpost group-set reviewers 'writer,engineer'
agentpost question reviewers 'Review section 4.' --notify idle
agentpost panel engineer '<message-id>'

# Inspect, claim, and correlate a reply.
agentpost list writer
agentpost read writer '<message-id>'
agentpost next writer --message-id '<message-id>'
agentpost reply '<message-id>' 'Reviewed; one ambiguity remains.'
```

`message` and `question` are the normal human-facing channel commands. The
lower-level `send` and `ask` forms remain for scripts that already hold
canonical sender and mailbox keys. Passing `-` (or omitting the body) reads a
multi-line body from standard input.

Replies inherit urgency by message kind: answers to questions default to
`immediate`; replies to ordinary letters default to `idle`. `--notify` remains
an explicit override.

## How waiting works

No model call, prompt loop, or polling conversation runs while an agent is
idle.

- Claude Code runs a plugin monitor that polls mailbox metadata and emits a
  native monitor event only when unread mail appears. Lifecycle hooks maintain
  a short busy/idle boundary in the mailbox's AgentPost adapter directory. A
  fresh Claude load starts the monitor automatically; no model call is made
  until mail causes a native event.
- `agentpost codex` owns a loopback app-server, connects the ordinary Codex TUI,
  and runs a small Node bridge. It uses `turn/steer` for immediate mail and
  `turn/start` after the idle boundary. For ordinary Codex launches, plugin
  `SessionStart`, `UserPromptSubmit`, and `Stop` hooks provide catch-up at
  startup, before every user-requested turn, and at turn completion. Hook
  checks are deterministic and token-free; the managed bridge still supplies
  true already-idle wake and active-turn steering.

Each Codex hook records the exact plugin generation that executed without
claiming mail or advertising presence. `doctor` compares that observation with
the sole enabled cache generation and asks the local Codex app server for each
hook's current trust status. This deterministic check fails clearly for stale,
unobserved, ambiguous, or untrusted state. `agentpost armed` and sender warnings
include the same generation detail.

The adapters never claim mail. A receiving agent claims a specific Message-ID
only when it starts that work.

Lifecycle-only fallback hooks hold ownership for their hook event rather than
the whole CLI session; atomic `next` remains their final duplicate-work guard.

Delivery to an inactive agent still succeeds and queues durably. Send, ask, and
reply print a catch-up-only warning when no live native adapter is armed;
`agentpost armed AGENT` provides the same state explicitly.

Presence is derived from adapter heartbeats:

- `working`: a connected CLI has an active turn;
- `idle`: a connected CLI is available between turns;
- `offline`: no live adapter heartbeat exists.

Live adapters heartbeat every second and remain present through a five-second
freshness window, avoiding transient discovery flaps from brief scheduler or
filesystem stalls.

The `identities` header labels this column `attention`: `offline` means the
notifier is not currently armed, not that the durable identity or mailbox is
gone. Exact addressing is unaffected.

Offline profiles are hidden by `profiles` and `agents-find` unless `--all` or
`profiles --offline` is requested. Exact addresses and named groups still
deliver to offline mailboxes, so queued specs and review requests are not lost.

## Python agent systems

Python orchestrators can embed `AgentRuntime` instead of installing a
CLI-specific plugin. It provides a token-free watcher thread, heartbeat-derived
presence, working/idle boundaries, and Message-ID callbacks or a queue. Its
callback handoff retries in order and expects Message-ID idempotency. Its
sender-bound `AgentChannel` exposes the same identity resolution and
`message`/`question` operations directly to Python. Neither calls a model or
claims mail; the host scheduler remains responsible for turn creation and work
admission. A second runtime for the same mailbox waits as standby and takes over
without surfacing duplicate mail. Async hosts can await `runtime.get_async()`
directly. See
[Python integration](docs/PYTHON.md).

## Adapter capabilities

| Runtime | Catch-up | Active-turn immediate | Post-turn idle | Already-idle wake |
| --- | --- | --- | --- | --- |
| Claude Code | Yes | Yes | Yes | Yes |
| Codex managed launcher | Yes | Yes | Yes | Yes |
| Codex ordinary launch | Every prompt boundary | Next prompt | Turn completion | No |
| Antigravity CLI | Yes | Next lifecycle boundary | Yes | Not yet supported |
| Embedded Python | Yes | Host scheduler | Host scheduler | Host scheduler |

These runtimes share one delivery and exact-ID contract, but startup evidence
is adapter-specific. Claude must start a live monitor after a fresh process
load; managed Codex must attach its app-server bridge; ordinary Codex proves
lifecycle-hook catch-up only; Antigravity proves hook injection at its first
`PreInvocation`; and Python delegates turn creation to its host scheduler.

## Documentation

- [Installation and recovery](docs/INSTALL.md)
- [Two-agent quick start](docs/TWO_AGENT_QUICKSTART.md)
- [Mailbox protocol](docs/PROTOCOL.md)
- [Python integration](docs/PYTHON.md)
- [Legacy inbox migration](docs/MIGRATION.md)
- [Roadmap and parked work](ROADMAP.md)
- [Detailed design and acceptance criteria](SPEC.md)
- [Prior-art evaluation](PRIOR_ART_EVALUATION.md)
- [Current implementation status](IMPLEMENTATION_STATUS.md)

## Development

```sh
git clone https://github.com/5000Stadia/agentpost.git
cd agentpost
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests scripts
node --check src/agentpost/data/codex_bridge.mjs
claude plugin validate integrations/claude --strict
claude plugin validate integrations/claude/agentpost --strict
```

Uninstalling an adapter retains `~/.agentpost` and every message:

```sh
agentpost uninstall claude --project /work/docs
agentpost uninstall codex --project /work/app
```

AgentPost is released under the [MIT License](LICENSE).
