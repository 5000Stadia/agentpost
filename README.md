# AgentPost

AgentPost is a trusted-local post office for already-running agents. It gives
Claude Code, Codex, Antigravity CLI, and embedded Python agent systems durable
Markdown mailboxes, agent discovery, direct and group questions, and two
attention modes without consuming model tokens while waiting.

Installed CLI agents treat it as a named communication channel. A human can
say "send it to PB" or "ask the reviewers"; the integration resolves the
registered identity or group, infers the current sender from its project, sends
the message, and reports its durable Message-ID and live/queued state.

## Get two agents talking

Install AgentPost once:

```sh
python3 -m venv ~/.local/share/agentpost/venv
~/.local/share/agentpost/venv/bin/pip install \
  git+https://github.com/5000Stadia/agentpost.git
mkdir -p ~/.local/bin
ln -sf ~/.local/share/agentpost/venv/bin/agentpost ~/.local/bin/agentpost
agentpost init --connection-mode auto
```

Open the first project in Claude Code, Codex, or Antigravity CLI and say:

> Add this project to AgentPost as Agent One.

Open the second project and say:

> Add this project to AgentPost as Agent Two.

Each agent reads its project, writes its own useful directory profile, joins the
project, verifies the integration, and tells you about any restart or trust step.

After following any restart or trust prompt, tell Agent One:

> Ask Agent Two through AgentPost to review our storage plan and send back the
> biggest implementation risk.

That is the normal interface. You can also say:

> Send this to Agent Two: the API contract changed in section 4.

> Ask the reviewers through AgentPost whether this is ready to merge.

> Find the agent who handles release engineering and ask them to review this.

The agents resolve the address, send one durable message, and report whether it
was delivered live or queued for later. You do not need to manage inbox files
or repeat the request through another service.

For a tested two-agent walkthrough, runtime-specific Claude Code, Codex,
Antigravity, and Python instructions, and the exact underlying commands, see
[Two-agent quick start](docs/TWO_AGENT_QUICKSTART.md).

## What it does

- `idle`: hold the notification until the recipient finishes its active turn.
- `immediate`: surface now; Codex steers the active turn and Claude wakes its
  monitor.
- Mail remains ordinary UTF-8 Markdown under `~/.agentpost`.
- Reading is non-destructive. Claiming atomically moves one letter to `read/`.
- Notifications are pointers. The mailbox is always the durable truth.
- A mailbox belongs to a durable agent identity, not to one CLI process.
- Normal discovery shows only live `idle` or `working` agents. Offline boxes and
  all of their mail remain available through exact addressing and `--all`.

## Manual setup

AgentPost needs Python 3.11+. The Codex real-time adapter also needs Node.js 22+
(the normal npm Codex install already supplies it on most systems).

Antigravity CLI 1.1.1 has a validated lifecycle catch-up profile. Its plugin
injects exact unread Message-IDs before an invocation and at the completed
`Stop` boundary. Antigravity does not currently document an external input edge
for waking a TUI that is already idle, so AgentPost reports those deliveries as
queued until the next prompt or lifecycle boundary. Launch it with `agentpost
antigravity --agent NAME` after joining so shared project roots retain the
correct sender identity.

The natural-language setup above asks each coding agent to perform these
underlying operations:

```sh
agentpost profile-register writer \
  --display-name Writer --cli claude --kind project \
  --summary 'Owns documentation structure, editorial review, and release notes.' \
  --roles editorial --projects docs \
  --project-roots /work/docs --specialties documentation \
  --handles 'documentation reviews,release notes'

cd /work/docs
agentpost join
```

Profiles are coworker-facing routing nameplates, not biographies. Summaries
should state durable ownership, while roles, projects, specialties, handles,
and exclusions supply the terms other agents will search. Run `agentpost
profile-register --help` for the authoring checklist.

On an interactive first run, `agentpost init` asks whether registered project
mailboxes should reconnect automatically. `auto` reuses known project roots;
`manual` requires an explicit `join`/`connect` binding. Neither mode silently
creates a mailbox for every short-lived process.

Bare `join` resolves the unique deepest registered project root. When no root
or multiple roots match, it prints the available candidates and requires the
explicit exception form `agentpost join NAME`.

`join` is idempotent and is the normal second and final onboarding step. The
equivalent advanced installation command is:

```sh
agentpost install claude --agent writer --project /work/docs
agentpost doctor writer --project /work/docs --cli claude
```

For Codex, register a `--cli codex` profile, install the plugin, explicitly
trust its two hooks when Codex first presents them, and launch Codex through
the AgentPost app-server binding:

```sh
agentpost install codex --agent engineer --project /work/app
agentpost doctor engineer --project /work/app --cli codex
cd /work/app
agentpost codex --agent engineer
```

`agentpost codex --agent engineer resume --last` passes resume arguments
through while retaining the native mailbox bridge.

`agentpost install` also records the requested project as that mailbox's
default binding. To run a different mailbox from the same directory, use the
per-process override instead of changing the default:

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
agentpost identities
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
agentpost reply writer '<message-id>' 'Reviewed; one ambiguity remains.'
```

`message` and `question` are the normal human-facing channel commands. The
lower-level `send` and `ask` forms remain for scripts that already hold
canonical sender and mailbox keys. Passing `-` (or omitting the body) reads a
multi-line body from standard input.

## How waiting works

No model call, prompt loop, or polling conversation runs while an agent is
idle.

- Claude Code runs a plugin monitor that polls mailbox metadata and emits a
  native monitor event only when unread mail appears. Lifecycle hooks maintain
  a short busy/idle boundary.
- `agentpost codex` owns a loopback app-server, connects the ordinary Codex TUI,
  and runs a small Node bridge. It uses `turn/steer` for immediate mail and
  `turn/start` after the idle boundary. A plugin `Stop` hook provides catch-up
  for ordinary Codex launches and suppresses itself while the bridge is active.

The adapters never claim mail. A receiving agent claims a specific Message-ID
only when it starts that work.

Delivery to an inactive agent still succeeds and queues durably. Send, ask, and
reply print a catch-up-only warning when no live native adapter is armed;
`agentpost armed AGENT` provides the same state explicitly.

Presence is derived from adapter heartbeats:

- `working`: a connected CLI has an active turn;
- `idle`: a connected CLI is available between turns;
- `offline`: no live adapter heartbeat exists.

Offline profiles are hidden by `profiles` and `agents-find` unless `--all` or
`profiles --offline` is requested. Exact addresses and named groups still
deliver to offline mailboxes, so queued specs and review requests are not lost.

## Python agent systems

Python orchestrators can embed `AgentRuntime` instead of installing a
CLI-specific plugin. It provides a token-free watcher thread, heartbeat-derived
presence, working/idle boundaries, and Message-ID callbacks or a queue. Its
sender-bound `AgentChannel` exposes the same identity resolution and
`message`/`question` operations directly to Python. Neither calls a model or
claims mail; the host scheduler remains responsible for turn creation and work
admission. See [Python integration](docs/PYTHON.md).

## Adapter capabilities

| Runtime | Catch-up | Active-turn immediate | Post-turn idle | Already-idle wake |
| --- | --- | --- | --- | --- |
| Claude Code | Yes | Yes | Yes | Yes |
| Codex managed launcher | Yes | Yes | Yes | Yes |
| Antigravity CLI | Yes | Next lifecycle boundary | Yes | Not yet supported |
| Embedded Python | Yes | Host scheduler | Host scheduler | Host scheduler |

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
