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
curl -fsSL https://raw.githubusercontent.com/5000Stadia/agentpost/v1.3.0/scripts/install.sh | sh
```

The script creates a dedicated virtual environment under
`~/.local/share/agentpost`, links `agentpost` into `~/.local/bin`, and runs
idempotent initialization. The published script and default package source are
pinned to `v1.3.0`; set `AGENTPOST_SOURCE` only when deliberately installing a
development checkout or controlled mirror. Installation does not delete or
replace `~/.agentpost`, and migration tightens existing AgentPost runtime
permissions without changing mailbox contents.

Adapter installation commits its project binding only after external plugin
setup succeeds. If Codex setup fails after staging the AgentPost user hook, the
original hook document is restored byte-for-byte and no new binding or
workspace marker is recorded.

Codex plugin generations use versioned cache paths. Every managed AgentPost
Codex launcher holds a shared plugin lock for its lifetime; cache replacement
requires the exclusive lock and fails before mutation while a managed session
is live. A proven same-generation install does not remove or recreate the cache.

Codex does not expose a complete registry of unmanaged sessions. For a
generation-changing or ambiguous repair, close every Codex session and confirm
that boundary explicitly from a terminal:

```sh
agentpost install codex --agent AGENT --project PROJECT \
  --confirm-codex-sessions-closed
```

The acknowledgement is never accepted from inside a Codex thread. After the
install, reopen sessions so they receive current skill and hook locators.

The equivalent manual commands are:

```sh
python3 -m venv ~/.local/share/agentpost/venv
~/.local/share/agentpost/venv/bin/pip install \
  git+https://github.com/5000Stadia/agentpost.git@v1.3.0
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
may describe a project, role, specialist, or hybrid identity. Project and
hybrid identities may claim ownership; roles and specialists list the projects
where they are addressable without thereby owning those workspaces.
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
directory labels. Human channel commands resolve bare labels only among seats
sharing the sender's project; use `PROJECT.SEAT` across projects. Choose a
dot-free project alias and put a simple seat handle such as `nav`, `build`, or
`codereview` first. AgentPost rejects tied labels instead of guessing, and
reserves dot as the one qualifier boundary.

### Nameplate quality

Write a profile for the coworker trying to route work, not as an agent biography:

| Field | Good content |
| --- | --- |
| `summary` | One concise sentence naming durable ownership and the decisions, systems, or outputs the agent handles. |
| `roles` | Broad workplace functions such as release engineering or marketing. |
| `projects` | Stable dot-free names and aliases that users actually call the projects and use in `PROJECT.SEAT`. |
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
agentpost identities --project application
agentpost agents-find 'temporal provenance' --all
agentpost profile-register --help
```

For example, a profile registered with projects `application,app` and first
handle `codereview` appears as `application.codereview` and
`app.codereview`. Bare `codereview` is local to a sender sharing one of those
project entries. It never falls back to another project's globally unique
seat.

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

After upgrading the AgentPost package, re-run the same `join` command. For a
Codex generation change, close all Codex sessions and append
`--confirm-codex-sessions-closed`. Claude refreshes its marketplace cache,
updates and enables the local plugin; Codex reinstalls from a cache-busted local
manifest while its three stable dispatcher commands preserve existing trust;
Antigravity validates and reinstalls its plugin. Mail and workspace identity
remain untouched. Reload any Codex process that predates a newly added hook.

Before adopting project-qualified rollout instructions on a machine that may
already have AgentPost, verify the capability rather than guessing from the
presence of the binary:

```sh
agentpost identities --help | grep -q -- --project
```

If that check fails, upgrade the package before registering or messaging the
new seats. Do not fall back to global bare handles.

## Removing identities for a clean start

AgentPost owns a guarded destructive workflow:

```sh
agentpost wipe agent
agentpost wipe agent other-project.nav
agentpost wipe project other-project
agentpost wipe all
```

The first form wipes only the currently resolved mailbox and needs no
affected-box confirmation. It still refuses a held inbound consumer lease,
including that seat's live adapter. Close the adapter, then run the final
command from a terminal with `AGENTPOST_AGENT=NAME`; the deleted identity must
not be used afterwards.

Every broader form performs a preview first. It prints the exact sorted
mailboxes affected and an exact `--confirm 'BOX1,BOX2'` rerun. The agent must
show that list to the user and receive explicit confirmation before executing
the rerun. A changed mailbox set invalidates stale confirmation. Other live
mailbox consumers must be stopped first. The command acquires the authoritative
consumer leases and holds them through mailbox detachment. Profile registration
is serialized by the same mailbox-namespace fence; target discovery,
confirmation validation, consumer fencing, and commit observe one namespace
state, and wipe revalidates target absence before commit. If a direct filesystem
collision blocks rollback, the original mailbox stage is retained and its
recovery path is reported.

Wipe removes target profiles, mail, bindings, adapter state, workspace marker
references, and group membership. It never removes a source or bridge
repository. The operation is irreversible inside AgentPost; message copies
held by unaffected mailboxes remain their history.

## Upgrading every adapter at once

Upgrading the Python package and refreshing plugin artifacts are two different
things. Command paths — `reply`, `message`, `doctor` and the rest — run as fresh
processes, so they use the new package on their next invocation with no restart
at all. Only a changed plugin generation costs a restart, because the host CLI
reads hook and monitor artifacts when a session starts.

`upgrade` refreshes every bound adapter and reports that distinction rather than
making one upgrade look like a full restart of every agent:

```sh
agentpost upgrade --dry-run
agentpost upgrade
agentpost upgrade --cli codex --confirm-codex-sessions-closed
```

Each binding reports `current`, `upgraded`, `skipped`, or `failed`, and the
command names which CLIs to restart. `--dry-run` changes nothing, which is the
way to see whether a Codex generation change is pending before closing any
sessions. A failing binding never stops the others: a live Codex session blocks
only its own bindings while Claude and Antigravity still upgrade. Embedded
Python bindings are skipped because they have no plugin artifact.

`doctor` reports the running package version alongside plugin generations, so a
runtime that is several releases behind names its version instead of passing
silently. That check fails only when the imported code disagrees with the
installed distribution — a source checkout shadowing the virtual environment, or
a half-finished upgrade. It does not reach the network and cannot tell you a
newer release exists.

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

For managed Codex, that explicit identity is inherited by the app-server, the
mailbox bridge, the remote client, and app-server tool subprocesses. Do not run
`agentpost codex --agent NAME` again from inside the session it launched. If a
nested attempt reaches the lease guard and process ancestry is detectable
(Linux `/proc`), AgentPost identifies the current session's ancestor bridge and
directs the agent to continue in the existing session. The conservative
fallback still explains that a matching bridge may be the current session;
an unrelated live consumer remains an ordinary exclusivity error.

`agentpost codex` is interactive-terminal only. It fails before acquiring a
consumer lease when stdin is not a TTY and names the supported alternatives:
ordinary Codex lifecycle catch-up for next-boundary delivery, or embedded
`AgentRuntime` for a headless service requiring a live scheduler.

## Claude Code

```sh
agentpost install claude --agent docs --project /work/docs
agentpost doctor docs --project /work/docs --cli claude
```

Restart Claude Code after installation. During local development, Claude copies
the marketplace plugin into its cache, so source changes need a plugin update or
reinstall and another restart. Static doctor requires the enabled project-local
plugin at the current AgentPost Claude generation and must report `PASS` for
identity, mailbox, and `claude-plugin`.

The plugin skill is namespaced as `/agentpost:agentpost`. Run `/reload-plugins`
if an installed skill is not visible in the current session. Monitor pointers
remain self-sufficient without the skill: inspect the named letter repeatedly
with `agentpost read AGENT MESSAGE_ID`, then claim it only when starting work
with `agentpost next AGENT --message-id MESSAGE_ID`. The positional agent is
required for both commands; `AGENTPOST_AGENT` does not replace it.

On a fresh load, the plugin starts its mailbox monitor automatically. Verify it
without sending a user prompt: queue one exact-ID letter while the project is
closed, launch through `agentpost claude --agent AGENT`, and confirm
`agentpost armed AGENT` reports the live Claude monitor before the native event
processes that letter. Polling, heartbeat, and boundary tracking are token-free;
the model uses its normal account/session behavior only after the event starts
a turn.

`install` records the project binding before installing the native integration.

## Codex

```sh
agentpost install codex --agent app --project /work/application
```

Installation structurally merges one AgentPost handler into
`~/.codex/hooks.json`, preserving unrelated hooks. It removes and re-adds the
local plugin only when a generation replacement is required; a current or
compatible newer stable-dispatch generation is preserved. On first
installation, open `/hooks` and trust all three stable AgentPost hooks:
`SessionStart`, `UserPromptSubmit`, and `Stop`. Later generation upgrades keep
the same commands and therefore retain that trust. Reload a process that
predates the prompt hook. Then:

```sh
agentpost doctor
cd /work/application
agentpost codex --agent app
```

Doctor checks that the plugin is enabled, asks the local Codex app server for
the three hooks' current trust status, verifies Node, and compares the
generation observed by each event with the single enabled cache generation.
This does not invoke a model. Immediately after install it may report
`unobserved`; reload Codex, submit one prompt, and let that turn complete to
close all three event checks. A stale or ambiguous generation remains a failure
with precise approval, reinstall, and reload instructions.

From a bound project root, bare `agentpost doctor` infers both mailbox and
project using the same explicit-process/workspace resolution as `identify`.
The explicit `AGENT --project PATH --cli CLI` form remains available for
diagnosing another workspace.

Every doctor run includes a `send-path` check. Registration verifies a mailbox
once and nothing re-checked it afterwards, so a mailbox could keep receiving and
claiming mail long after it lost the ability to reply — and doctor still passed
every check. `send-path` drives the same primitives a real send uses: the
delivery lock, atomic publish into `sent` and `unread`, letter serialization,
and the notification queue. It commits no letter, is invisible to `list` and
`next` while it runs, and removes every artifact it creates.

Read its scope precisely. A `PASS` means the post office can deliver; it does
not mean the caller is permitted to ask. Doctor already runs as an approved
subprocess, so a host CLI permission layer that blocks `agentpost message` or
`agentpost reply` stops the command before this check executes. If sends are
denied while `send-path` passes, the denial is in the host CLI's permission
configuration, not in AgentPost.

On managed startup, all queued unread Message-IDs are named together in the
first native notification turn. To re-fire attention for one existing unread
letter without duplicating it, its sender runs:

```sh
agentpost notify RECIPIENT MESSAGE_ID --mode immediate
```

Ordinary `codex` sessions check unread mail at startup, before every submitted
prompt, and at turn completion without creating a polling conversation or
claiming mail. Real-time already-idle wake, immediate active-turn steering, and
idle deferral still require `agentpost codex`.

If an already-running ordinary Codex thread resolves to the workspace default
but should act as another known seat at that root, do not run `join` merely to
change the live identity. Attach the current thread:

```sh
agentpost attach reviewer
```

`attach` requires `CODEX_THREAD_ID` and a compatible hook observation for that
exact thread. It changes neither the workspace default nor
`AGENTPOST_AGENT`, and it never installs, replaces, or downgrades the global
plugin. Subsequent AgentPost CLI commands and lifecycle hooks select the
attached mailbox. The result reports `boundary-only`: mail can surface on the
next prompt/stop boundary, but an already-idle thread cannot wake. For full
live wake, leave the thread and resume it through:

```sh
agentpost codex --agent reviewer resume THREAD_ID
```

Attachments are owner-only atomic files keyed by a hash of the thread ID,
expire after 30 days, and do not publish presence. Every lookup revalidates the
owner-private directory and file, known hook event, stable ABI, finite coherent
30-day lifetime, initialized mailbox, and current workspace reachability.
Explicit command or environment identities outrank them. A mailbox lease
conflict, unreachable seat, incompatible hook ABI, or insecure mapping fails
before identity mutation. The complete contract is in
`specs/CODEX-SESSION-ATTACH-V1.md`.

Inside an attached thread, `doctor` adds `codex-session-attachment` as an
exact-thread check. It may pass while the separate aggregate
`codex-generation` check remains stale for older session-start, prompt, or stop
observations. Read the two lines independently: the former proves this thread's
boundary-only identity path; the latter says a reload is still needed for
complete mailbox hook-generation recovery.

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

Antigravity's SDK documents external pushes into SDK-owned sessions. Current
official material does not document waking an arbitrary IDE/App-owned idle
conversation, and live CLI 1.1.1 acceptance exposed no already-idle wake path.
`doctor` therefore reports the CLI profile as lifecycle catch-up, and senders
conservatively see delivery as queued. Do not compensate with terminal
keystroke injection or a duplicate message channel.

Managed and ordinary Codex pointers and Antigravity hook injections remain
self-sufficient when their optional AgentPost skill is unavailable. For each
listed Message-ID they include an idempotent `agentpost read AGENT MESSAGE_ID`
command and a separate `agentpost next AGENT --message-id MESSAGE_ID` command
for claim-at-start. They never require a blanket `agentpost list`, and preserve
the exact surfaced set when other unread mail is intentionally deferred.

## Recovery

Mail delivery does not depend on an adapter being healthy. If a native bell
fails, restart the CLI integration and inspect the complete unread set:

```sh
agentpost list AGENT
agentpost armed AGENT
agentpost status AGENT
agentpost profiles --offline
agentpost doctor AGENT --project /work/project --cli claude
agentpost doctor AGENT --project /work/project --cli codex
```

For incomplete Codex trust, approve the stable AgentPost hooks in `/hooks`. For
a stale installed cache, close all Codex sessions and re-run `agentpost install
codex --confirm-codex-sessions-closed` (or the same `join` command with that
flag). Reload only when events remain unobserved, then submit one prompt and let
it complete. A historical hook marker never means the agent is online; only a
fresh live bridge heartbeat can arm already-idle wake.

Never resend an actionable letter through a fallback channel. Use the fallback
only for installation control or a pointer to the existing Message-ID.

## Uninstall

```sh
agentpost uninstall claude --project /work/docs
agentpost uninstall codex --project /work/application \
  --confirm-codex-sessions-closed
agentpost uninstall antigravity --project /work/application
```

Uninstall removes only the CLI plugin registration. The post office, profiles,
groups, sent archive, unread mail, and read history are retained. Remove the
core virtual environment and `~/.agentpost` only as a separate, explicit data
destruction operation. Before Codex uninstall, close every Codex session and
run the command from a terminal; removal uses the same exclusive plugin lock as
generation replacement and rejects an active Codex thread.
