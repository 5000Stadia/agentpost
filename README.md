# AgentPost

[![Test](https://github.com/5000Stadia/agentpost/actions/workflows/test.yml/badge.svg)](https://github.com/5000Stadia/agentpost/actions/workflows/test.yml)

AgentPost is a trusted-local post office for already-running agents. It gives
Claude Code, Codex, Antigravity CLI, and embedded Python agent systems durable
Markdown mailboxes, agent discovery, direct and group questions, and two
attention modes without consuming model tokens while waiting.

AgentPost 1.x is the stable Linux/POSIX release line. Its compatibility and
security boundaries are explicit; optional future adapter capabilities do not
weaken durable delivery.

Installed CLI agents treat it as a named communication channel. A human can
say "send it to PB" or "ask the registered reviewers group"; the integration
resolves the registered identity or group within the active sender's project,
sends the message, and reports its durable Message-ID and live/queued state.
Cross-project seats use an explicit `PROJECT.SEAT` address such as
`pbe.codereview`. An identity may own a project, represent a role such as code
review or marketing, serve as a specialist, or combine those shapes.

## Quick Start

```sh
curl -fsSL https://raw.githubusercontent.com/5000Stadia/agentpost/v1.3.0/scripts/install.sh | sh
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

Follow any restart prompt. Ask Agent Two to report the qualified address printed
by `agentpost identities --project PROJECT`, then tell Agent One to use it:

```text
Ask PROJECT.SEAT to produce a couplet for a poem, append a couplet after its return. Repeat until you have 4 couplets.
```

If both seats share the same registered project, bare `Agent Two` also resolves.

Other Examples:

- Deliberate with Spec Reviewer until Green.  Implement, then after implementation review with Code Reviewer.
- Ask the marketing agent to propose launch positioning for this feature.
- Ask Agent Tom whether its invitation workflow addresses a similar onboarding problem then what we're seeing here.
- Ask Security to scan this repo and return a report of detected vulnerabilities we need to button up.

## What it does

- `idle`: hold the notification until the recipient finishes its active turn.
- `immediate`: surface now; Codex steers the active turn and Claude wakes its
  monitor.
- Mail remains ordinary UTF-8 Markdown under `~/.agentpost`.
- Reading is non-destructive. Claiming atomically moves one letter to `read/`.
- Replying atomically claims an exact unread original; already-read originals
  remain replyable for corrections.
- Notifications are pointers. The mailbox is always the durable truth.
- Fresh interactive-adapter startup batches the full queued unread set into one
  consent gate. The agent reports the mailbox and count, then asks whether to
  inspect that exact set now, reload or rebind first, or defer it. Startup
  priority never authorizes reading or claiming mail.
- A mailbox belongs to a durable agent identity, not to one CLI process.
- One mailbox-wide consumer lease prevents two live CLI or Python adapters from
  surfacing the same inbound work; compatible runtimes wait and take over.
- Normal discovery shows only live `idle` or `working` agents. Offline boxes and
  all of their mail remain available through project-qualified addressing and
  `--all`.

### Assigning agents to a group (Optional)

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

Useful group ideas include `engineering` for a standing department,
`release-council` for approval work, `world-team` for cross-project domain
owners, and `incident-response` for time-sensitive operational review. A group
is a durable named address list; `group-set` replaces its complete membership.


## Manual setup

AgentPost needs Python 3.11+. The Codex real-time adapter also needs Node.js 22+
(the normal npm Codex install already supplies it on most systems).

### Installer behavior

The one-line installer is idempotent. The published script and its default
source are pinned to `v1.3.0`; `AGENTPOST_SOURCE` is the explicit development
or mirror override. It upgrades the dedicated environment
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
`Stop` boundary. Its first host-process snapshot is a consent gate; later mail
uses the ordinary exact-ID instruction. Antigravity's SDK documents external
pushes into SDK-owned sessions; it does not document waking an arbitrary
IDE/App-owned idle conversation. The CLI exposes no validated already-idle
wake path, so AgentPost reports CLI deliveries as queued until the next prompt
or lifecycle boundary.
Launch it with `agentpost antigravity --agent NAME` after joining so shared
project roots retain the correct sender identity.

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

A review identity can be addressable in more than one project without claiming
ownership of either runtime workspace:

```sh
agentpost profile-register reviewer \
  --display-name 'Code Review' --kind role \
  --summary 'Provides cross-project code review focused on correctness and regression risk.' \
  --roles 'code review' --projects 'application,docs' \
  --specialties 'correctness,regression analysis' \
  --handles 'codereview,pull request reviews,implementation risk reviews'

agentpost join reviewer --cli codex --project "$PWD"
agentpost codex --agent reviewer
```

The workspace above is a runtime connection, not project ownership. The
`projects` entries are the namespaces in which coworkers may address this seat
as `application.codereview` or `docs.codereview`.

Mailbox access and live connection are different states. An agent asked to set
up or reconnect must run `join`, then verify the requested adapter with
`doctor` and `armed`; successful address resolution or inbox access alone does
not mean notifications are live:

```sh
agentpost doctor reviewer --project "$PWD" --cli codex
agentpost armed reviewer
```

Only `ARMED` establishes live receipt. `QUEUED` means delivery remains durable
but the current notifier is not live. An ordinary active Codex thread can
explicitly select an alternate known workspace seat without restart:

```sh
agentpost attach reviewer
```

This session-scoped operation never installs or replaces the global plugin. It
provides exact-ID delivery at the next Codex prompt/stop boundary and remains
honestly `QUEUED`; true already-idle wake still requires an external managed
resume with `agentpost codex --agent reviewer resume THREAD_ID`. Other adapters
that support lifecycle catch-up but not idle wake also remain `QUEUED` between
lifecycle boundaries.

If a named launcher finds that another process already consumes the mailbox,
it reports the owner and suggests the first unused numbered identity, such as
`reviewer2`. The agent must offer that option rather than creating it silently.
After user approval, the new identity is registered, joined, launched, and
verified separately. It has its own inbox and does not inherit mail already
addressed to `reviewer`.

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

When replacing or removing an existing Codex plugin generation, first close
every Codex session and run the operation from a terminal with
`--confirm-codex-sessions-closed`. AgentPost coordinates managed launches with
a process lock, but Codex does not expose all ordinary unmanaged sessions for
automatic enumeration. A same-generation install leaves the live cache intact.

`agentpost codex --agent engineer resume --last` passes resume arguments
through while retaining the native mailbox bridge.

If an ordinary active Codex thread started as the wrong default seat but
already has a compatible AgentPost hook loaded, attach it without reinstalling
or restarting:

```sh
agentpost attach reviewer
```

The command verifies the current `CODEX_THREAD_ID`, reachable workspace seat,
hook event and ABI, finite coherent expiry, owner-private attachment directory,
and mailbox consumer ownership. Invalid pre-existing attachment state fails
closed during ordinary identity lookup. It reports `boundary-only` unless the
thread already has a managed bridge. The session selection outranks workspace
defaults for hooks and AgentPost CLI subprocesses, but explicit `--from`,
`--agent`, and `AGENTPOST_AGENT` still outrank it. See
[Codex session attach](specs/CODEX-SESSION-ATTACH-V1.md).

Managed consumers report held leases independently from heartbeat presence. A
suspended terminal job therefore appears as `suspended`, not misleadingly
offline. If the user intended to close that exact managed instance, AgentPost
prints a guarded recovery command shaped as:

```sh
agentpost consumer-stop reviewer --instance FULL_INSTANCE_ID
```

The full instance guard prevents a stale instruction from stopping a
replacement consumer. It releases the process tree and lease without deleting
mail, identity state, bindings, or attachments. Managed Codex and Antigravity
sessions convert terminal suspension into clean shutdown because a stopped
bridge cannot provide wake while retaining exclusive mailbox ownership.

Managed Codex owner metadata also records a digest of a resumed thread ID. A
resume under another AgentPost seat fails before startup when that thread is
already managed elsewhere and prints the existing seat and exact recovery
command. See [safe session re-entry](specs/SAFE-SESSION-REENTRY-V1.md).

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
agentpost identities --project pattern-buffer
agentpost resolve pb --project pattern-buffer
agentpost resolve pattern-buffer.pb

# Find the right coworker instead of guessing a name.
agentpost agents-find 'database migration'
agentpost agents-find --role marketing
agentpost status
agentpost profiles --offline

# The sender is inferred from the current project. Bare names resolve only
# inside it; another project's seat must be qualified.
agentpost message engineer 'Please review the storage notes.' --notify idle
agentpost message pattern-buffer.pb 'Please review the storage notes.' \
  --notify idle

# Urgent questions surface during an active turn.
agentpost question writer 'Does this wording change the contract?' \
  --notify immediate

# Repository reviews fail closed unless the immutable artifact resolves.
commit=$(git rev-parse HEAD)
parent=$(git rev-parse HEAD^)
agentpost review reviewer 'Check reply concurrency and regression coverage.' \
  --repo "$PWD" --commit "$commit" --parent "$parent" \
  --path src/agentpost/core.py \
  --test tests/test_core.py::PostOfficeTest::test_reply_correlates_to_original

# Ask a registered group and inspect its derived response panel.
agentpost group-set reviewers 'writer,engineer'
agentpost question reviewers 'Review section 4.' --notify idle
agentpost panel engineer '<message-id>'

# Inspect, claim, and correlate a reply.
agentpost list writer
agentpost read writer '<message-id>'
agentpost next writer --message-id '<message-id>'
agentpost reply '<message-id>' 'Reviewed; one ambiguity remains.'

# Irreversibly wipe only this inferred mailbox.
agentpost wipe agent

# Broader wipes first print the exact affected boxes and require that exact
# user-confirmed list on the second invocation.
agentpost wipe project pattern-buffer
agentpost wipe all
```

`message` and `question` are the normal general-purpose channel commands.
`review` is the repository-specific question form: it requires a Git worktree,
an explicit full commit SHA, one or more commit-tree paths, and one or more
file-qualified test nodes. An optional `--parent` must be a direct parent. It
rejects unresolved shell or placeholder syntax, prints the complete generated
artifact block, and writes no recipient or sender copy if preflight fails.
The lower-level `send` and `ask` forms remain for scripts that already hold
canonical sender and mailbox keys. Passing `-` (or omitting the body) reads a
multi-line body from standard input.

### Project-qualified addressing

Every project seat registers a dot-free canonical mailbox key, at least one
dot-free `projects` name or alias, and preferably a short handle first. The
directory then exposes predictable addresses:

```text
canonical: pbe-r
projects: pattern-buffer-evolution,pbe
handles: codereview,implementation review
qualified: pattern-buffer-evolution.codereview,pbe.codereview
```

Bare `codereview` resolves only among profiles sharing a project entry with the
sender. It never retries against the global directory, even when another
project's matching seat is globally unique. Cross-project communication uses
`pbe.codereview`; `agentpost identities --project pbe` lists every registered
seat in that project, including offline seats. A qualified address contains
exactly one dot, which is why mailbox keys and project aliases cannot contain
dots. See [Project-qualified identities](specs/PROJECT-QUALIFIED-IDENTITIES-V1.md).

Named groups remain deliberate global fan-out addresses. Prefer explicit
`@group` where a group could resemble a local seat. Low-level `send` and `ask`
retain canonical mailbox-key semantics for scripts.

### Clean starts

`agentpost wipe agent` removes the current mailbox, mail, bindings, adapter
state, workspace references, and group membership. It needs no affected-box
confirmation, but still refuses a held consumer lease; close the seat and run
its final self-wipe from a terminal with `AGENTPOST_AGENT=NAME`. Wiping a
different agent, a project, or all agents never proceeds on the first call:
AgentPost prints the sorted affected mailbox list and the exact `--confirm`
value. Show that list to the user and obtain explicit confirmation before
rerunning it. A changed list invalidates the confirmation, and every live
consumer must be stopped. Wipe holds each authoritative lease fence through
mailbox detachment. Profile registration shares a namespace lock with wipe, so
project target discovery, confirmation validation, consumer fencing, and commit
observe one namespace state, and same-name recreation cannot switch to a new
consumer-lock inode mid-transaction. If an unsupported filesystem collision
prevents rollback, the original mailbox stage is preserved and its recovery
path is reported.

Wipe never touches source or AgentBridge repositories. It is irreversible
inside AgentPost; copies held by unaffected mailboxes remain their history. See
[Safe wipe workflow](specs/SAFE-WIPE-V1.md).

Replies inherit urgency by message kind: answers to questions default to
`immediate`; replies to ordinary letters default to `idle`. `--notify` remains
an explicit override. A successful reply claims an unread original as part of
the same operation. Validation failures leave it unread; a delivery error after
claim leaves it read because recipient delivery may already have committed.
Retry that case as a correction against the already-read original rather than
requeueing it and risking a duplicate response.

## How waiting works

No model call, prompt loop, or polling conversation runs while an agent is
idle.

- Claude Code runs a plugin monitor that polls mailbox metadata and emits a
  native monitor event only when unread mail appears. Lifecycle hooks maintain
  a short busy/idle boundary in the mailbox's AgentPost adapter directory. A
  fresh Claude load starts the monitor automatically; no model call is made
  until mail causes a native event. Its initial event announces only the queued
  count and asks whether to inspect, reload, or defer. Later live events name
  the optional `/agentpost:agentpost` skill and include exact positional `read`
  and `next` commands, so inspection remains retry-safe when the skill is
  unavailable.
- `agentpost codex` owns a loopback app-server, connects the ordinary Codex TUI,
  and runs a small Node bridge. It uses `turn/steer` for immediate mail and
  `turn/start` after the idle boundary. For ordinary Codex launches, plugin
  `SessionStart`, `UserPromptSubmit`, and `Stop` hooks provide catch-up at
  startup, before every user-requested turn, and at turn completion. Hook
  checks are deterministic and token-free; the managed bridge still supplies
  true already-idle wake and active-turn steering.
- `agentpost attach NAME` gives an already-running ordinary Codex thread a
  private, expiring mailbox selection without mutating its environment or
  plugin. It affects subsequent lifecycle boundaries and AgentPost CLI
  subprocesses, publishes no presence, and does not create an idle-wake bridge.

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
gone. Its `qualified` column lists stable cross-project addresses.

Offline profiles are hidden by `profiles` and `agents-find` unless `--all` or
`profiles --offline` is requested. Project-qualified addresses and named groups
still deliver to offline mailboxes, so queued specs and review requests are not
lost.

## Security boundary

AgentPost trusts processes running under one operating-system account. Runtime
mail and configuration are owner-only, and upgrades tighten existing
AgentPost-owned state through `agentpost migrate`. The filesystem post office
opens no network listener; the managed Codex transport is loopback-only.
AgentPost does not provide remote authentication, encryption, hostile-prompt
filtering, or isolation between same-account agents. See the
[security policy](SECURITY.md) before using mail that may contain secrets or
untrusted instructions.

## Python agent systems

Python orchestrators can embed `AgentRuntime` instead of installing a
CLI-specific plugin. It provides a token-free watcher thread, heartbeat-derived
presence, working/idle boundaries, and Message-ID callbacks or a queue. Its
callback handoff retries in order and expects Message-ID idempotency. Its
sender-bound `AgentChannel` exposes the same identity resolution and
`message`/`question` operations directly to Python, including
`identities(project=...)` and fail-closed `PROJECT.SEAT` routing. Neither calls
a model or claims mail; the host scheduler remains responsible for turn
creation and work admission. A second runtime for the same mailbox waits as
standby and takes over without surfacing duplicate mail. Async hosts can await
`runtime.get_async()` directly. Start with the
[Python agent quick start](docs/PYTHON_AGENT_QUICKSTART.md), then use
[Python integration](docs/PYTHON.md) for the complete host contract.

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

Every post-startup native exact-ID pointer is self-sufficient when its optional
skill is not available. It emits one retry-safe `agentpost read AGENT
MESSAGE_ID` command per letter and a separate `agentpost next AGENT
--message-id MESSAGE_ID` command for the moment work actually starts. Startup
gates intentionally omit those commands until the user consents. Exact pointers
never recommend a blanket inbox listing, and neither inspection nor notification
claims mail automatically.

## Documentation

- [Installation and recovery](docs/INSTALL.md)
- [Two-agent quick start](docs/TWO_AGENT_QUICKSTART.md)
- [Mailbox protocol](docs/PROTOCOL.md)
- [Python agent quick start](docs/PYTHON_AGENT_QUICKSTART.md)
- [Python integration](docs/PYTHON.md)
- [Legacy inbox migration](docs/MIGRATION.md)
- [Compatibility policy](docs/COMPATIBILITY.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)
- [Release procedure](docs/RELEASING.md)
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
