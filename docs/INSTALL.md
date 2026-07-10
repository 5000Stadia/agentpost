# Installation and recovery

## Prerequisites

- Python 3.11 or newer.
- Claude Code 2.1.206 or a compatible version for the Claude plugin monitor.
- Codex CLI 0.144.1 or a compatible version for the Codex integration.
- Antigravity CLI 1.1.1 or a compatible version for its lifecycle plugin.
- Node.js 22 or newer for the dependency-free Codex WebSocket bridge.

Consumer Gemini CLI access ended on June 18, 2026. AgentPost targets
Antigravity CLI instead; Enterprise Gemini CLI compatibility is not currently
scheduled. See [the roadmap](../ROADMAP.md) for remaining live-wake work.

## Core installation

The shortest install or upgrade is one line:

```sh
curl -fsSL https://raw.githubusercontent.com/5000Stadia/agentpost/main/scripts/install.sh | sh
```

The script creates a dedicated virtual environment under
`~/.local/share/agentpost`, links `agentpost` into `~/.local/bin`, and runs
idempotent initialization. It does not delete or replace `~/.agentpost`.

The equivalent manual commands are:

```sh
python3 -m venv ~/.local/share/agentpost/venv
~/.local/share/agentpost/venv/bin/pip install \
  git+https://github.com/5000Stadia/agentpost.git
mkdir -p ~/.local/bin
ln -sf ~/.local/share/agentpost/venv/bin/agentpost ~/.local/bin/agentpost
agentpost init
```

Interactive `init` asks for a connection policy:

- `auto` (recommended): reconnect an unqualified CLI through its workspace
  marker, binding, or registered project root;
- `manual`: require a binding created with `agentpost join` or `connect`.

Use `--connection-mode auto` or `--connection-mode manual` for unattended
installation. Automatic mode never creates a new mailbox merely because a CLI
process opened.

## Declare and connect a mailbox

For a tested end-to-end example with two identities, two project bindings, and
a correlated request/reply, start with [Two-agent quick start](TWO_AGENT_QUICKSTART.md).

Mailbox declaration and process connection are separate operations. A mailbox
may describe a project, role, specialist, or hybrid identity; only project and
hybrid identities need to claim project ownership in their profile.
`profile-register` creates or atomically updates the durable mailbox nameplate:

```sh
agentpost profile-register app \
  --display-name App --kind project \
  --summary 'Application engineering' \
  --roles engineering --projects application \
  --project-roots /work/application \
  --specialties 'python,release engineering' \
  --handles 'application engineering,release reviews'
```

Canonical name, display name, project entries, and responsibility handles are
the address-book labels accepted by `resolve`, `message`, and `question`.
Choose handles that are specific enough to avoid collisions; AgentPost rejects
tied labels instead of guessing.

### Nameplate quality

Write a profile for the coworker trying to route work, not as an agent biography:

| Field | Good content |
| --- | --- |
| `summary` | One concise sentence naming durable ownership and the decisions, systems, or outputs the agent handles. |
| `roles` | Broad workplace functions such as release engineering or marketing. |
| `projects` | Stable names and aliases that users actually call the projects. |
| `specialties` | Specific reusable technical or domain expertise. |
| `handles` | Two to five concrete request categories that should arrive here. |
| `does-not-handle` | Nearby responsibilities that belong to another agent. |

Use vocabulary another agent would search. A good summary is "Owns Pattern
Buffer temporal world-state semantics, ingestion fidelity, and deterministic
retrieval contracts." "Helpful coding agent working on the current task" is
not useful: it has no stable ownership or distinguishing search terms.

Keep status, availability, the current task, generic personality claims,
unverified future expertise, and secrets out of the durable profile. Inspect
existing identities first, avoid duplicate handles, then verify representative
queries:

```sh
agentpost identities
agentpost agents-find 'temporal provenance' --all
agentpost profile-register --help
```

For the usual first connection, change to the project and run one command. The
agent supplies its current CLI, records the adapter binding and CLI-neutral
workspace identity, and installs the native integration:

```sh
cd /work/application
agentpost join --cli codex
```

That makes onboarding two short steps: the owner declares the profile once;
the project agent runs bare `join` once. AgentPost resolves the unique deepest
registered project root and prints the remaining CLI-native
restart or hook-trust instruction.

`join` is idempotent: it handles fresh installation and an existing integration.
The explicit form also handles a moved checkout, where the new root cannot yet
identify itself. `connect` is an alias for users who prefer that verb, so the
agent never diagnoses installation state. Both create one machine-local
workspace default in `.agentpost.toml` and a separate adapter binding.
Reopening any installed CLI at that location resolves the same default mailbox:

```sh
agentpost connect app --cli codex --project /work/application
agentpost identify --cli codex --cwd /work/application
```

After upgrading the AgentPost package, re-run the same `join` command. Claude
refreshes its marketplace cache, updates and enables the local plugin; Codex
reinstalls from a cache-busted local manifest; Antigravity validates and
reinstalls its plugin. Mail and workspace identity remain untouched.

Moving a project is a new binding, not a mailbox migration. Connect the new
path, verify it, then remove the old default:

```sh
agentpost connect app --cli codex --project /work/application-v2
agentpost disconnect --cli codex --project /work/application
```

There is one unqualified default per workspace. Multiple agents and multiple
adapter types may still work from the same directory by selecting a mailbox per
process:

```sh
agentpost codex --agent app
agentpost codex --agent reviewer
agentpost claude --agent docs
```

Resolution uses explicit `--agent`/`AGENTPOST_AGENT` first. Otherwise the
deepest workspace marker, legacy adapter binding, or declared project root
wins, in that priority order for equal paths. `known_agents` in the workspace
marker records valid alternates but never guesses among them.

Only one inbound consumer may own a mailbox across all adapter types. Python
runtimes and Claude monitors wait as standbys; Codex and Antigravity launchers
report the existing owner when a second live bridge cannot attach safely. Start
separate role or reviewer sessions with separate mailbox names when both must
process inbound work concurrently.

When child arguments begin with an option, separate them from AgentPost's own
options: `agentpost claude --agent docs -- --model opus`.

The wrappers set `AGENTPOST_AGENT` only for the child process. They do not
rewrite the project default. A CLI-specific `/connect` command may wrap the
same operation, but the portable common instruction is `agentpost join`.

## Claude Code

```sh
agentpost install claude --agent docs --project /work/docs
agentpost doctor docs --project /work/docs --cli claude
```

Restart Claude Code after installation. During local development, Claude copies
the marketplace plugin into its cache, so source changes need a plugin update or
reinstall and another restart. Static doctor must report `PASS` for identity,
mailbox, and `claude-plugin`.

`install` records the project binding before installing the native integration.

## Codex

```sh
agentpost install codex --agent app --project /work/application
```

Start Codex once and explicitly trust both AgentPost hooks when prompted. Then:

```sh
agentpost doctor app --project /work/application --cli codex
cd /work/application
agentpost codex --agent app
```

Doctor checks that the plugin is enabled, both hook trust records exist, and
Node is available. Ordinary `codex` sessions retain SessionStart/Stop catch-up,
but real-time immediate steering and true idle deferral require `agentpost
codex`.

The launcher binds only to `127.0.0.1`, creates a fresh app-server for the TUI,
and removes its active marker and child processes on exit. Its diagnostic trace
is stored at:

```text
~/.agentpost/agents/AGENT/adapter/codex-bridge.log
```

## Antigravity CLI

Register a CLI-neutral project profile, then connect its Antigravity adapter:

```sh
agentpost install antigravity --agent app --project /work/application
agentpost doctor app --project /work/application --cli antigravity
agentpost antigravity --agent app
```

Restart through the AgentPost launcher after first installation. It sets the
per-process mailbox identity, which matters when multiple CLI agents share one
project root. The plugin uses `PreInvocation` and `Stop` hooks to inject exact
unread Message-IDs without claiming them. It supports startup/next-prompt
catch-up and completed-turn idle delivery.

Antigravity documents plugin sidecars and `agentapi` for its IDE/App surfaces,
but live CLI 1.1.1 acceptance showed that an installed, enabled, schema-valid
plugin sidecar does not start: no sidecar process, runtime data, or
`SidecarManager` initialization appears. `doctor` therefore reports the CLI
profile as lifecycle catch-up, and senders conservatively see delivery as
queued. Do not compensate with terminal keystroke injection or a duplicate
message channel.

## Recovery

Mail delivery does not depend on an adapter being healthy. If a native bell
fails, restart the CLI integration and inspect the complete unread set:

```sh
agentpost list AGENT
agentpost armed AGENT
agentpost status AGENT
agentpost profiles --offline
agentpost doctor AGENT --project /work/project --cli claude
```

Never resend an actionable letter through a fallback channel. Use the fallback
only for installation control or a pointer to the existing Message-ID.

## Uninstall

```sh
agentpost uninstall claude --project /work/docs
agentpost uninstall codex --project /work/application
agentpost uninstall antigravity --project /work/application
```

Uninstall removes only the CLI plugin registration. The post office, profiles,
groups, sent archive, unread mail, and read history are retained. Remove the
core virtual environment and `~/.agentpost` only as a separate, explicit data
destruction operation.
