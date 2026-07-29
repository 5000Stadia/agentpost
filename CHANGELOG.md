# Changelog

AgentPost follows [Semantic Versioning](https://semver.org/). The supported
compatibility surface is defined in [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

## Unreleased

## [1.3.0] - 2026-07-28

### Added

- Project-qualified human addressing now uses the profile metadata seats
  already register: `PROJECT.SEAT` deliberately crosses projects, while a bare
  canonical name, display name, handle, or role resolves only among profiles
  sharing the sender's project aliases. There is no global fallback.
  `identities`, `profiles`, and `status` accept `--project`; mailbox inspection
  accepts qualified addresses or a project filter; directory output includes
  predictable qualified aliases. Canonical mailbox keys and project aliases
  reserve dot as the single qualification boundary.
- `agentpost wipe agent [NAME]`, `wipe project PROJECT`, and `wipe all` provide
  clean AgentPost identity resets without touching source or bridge
  repositories. Self-wipe is direct; every broader scope first returns the
  exact sorted affected mailbox list and requires the same list through
  `--confirm`. Wipe removes complete target mailboxes, bindings, workspace
  references, adapter state, and group membership, refuses other active
  consumers, and states that successful deletion is irreversible.
- `agentpost attach MAILBOX` gives an already-running Codex thread an explicit,
  expiring session identity without restarting, changing the workspace
  default, mutating its parent environment, or touching the global plugin.
  Compatible stable hooks and AgentPost CLI subprocesses select the attachment
  at subsequent lifecycle boundaries. Output distinguishes `boundary-only`
  catch-up from an existing managed `live-bridge`; attachment alone publishes
  no presence and cannot wake an already-idle thread. Owner-only atomic state,
  exact thread/hook evidence, workspace-seat reachability, ABI validation,
  consumer-lease checks, expiry, and explicit-identity precedence all fail
  closed.
- Codex doctor reports an exact `codex-session-attachment` check separately
  from aggregate mailbox hook-generation recovery. A working attached thread
  is now visible as boundary-compatible even when historical session-start,
  prompt, or stop observations still correctly require reload for full
  generation parity.
- Codex install negotiation now preserves a compatible newer stable-dispatch
  plugin generation when an older runtime runs `join`, preventing an in-thread
  replacement or downgrade. Ambiguous and incompatible changes retain the
  terminal-only, all-sessions-closed replacement contract.
- `agentpost upgrade` refreshes every bound adapter in one command and reports
  each binding as `current`, `upgraded`, `skipped`, or `failed`, naming which
  CLIs need a restart. Upgrading the Python package and refreshing plugin
  artifacts are separate axes: command paths pick up new package code on their
  next invocation, so only a changed plugin generation costs a restart, and
  reporting them apart keeps a package upgrade from looking like a full restart
  of every agent. One binding's failure never stops the rest, so a live Codex
  session blocks only its own bindings. `--dry-run` reports what each binding
  would do without changing anything, and `--cli`/`--project` narrow the set.
- `agentpost doctor` reports the running package version, and `agentpost`
  exposes `__version__`. Doctor named plugin generations but never the package,
  so a runtime could sit releases behind while every check passed and nothing
  named the number. The check fails only when the imported code disagrees with
  the installed distribution — a source checkout shadowing the venv, or a
  half-finished upgrade. It cannot report that a newer release exists; that
  needs a network call doctor deliberately does not make.

### Fixed

- `agentpost reply MESSAGE_ID` with an inferred sender now answers from the
  seat that actually holds the letter, instead of always acting as the single
  workspace default. A runtime notified as an alternate seat sharing the
  project root could read and claim its mail but not answer it: inference
  resolved the workspace default, that mailbox did not hold the letter, and
  the documented reply workflow failed with `message not found`. Holding the
  letter is now the deciding signal, and inference is the tiebreak — the
  workspace default still wins when it holds a copy, and two alternate seats
  holding the same letter is reported with both names rather than guessed.
  Explicit `--from`, `AGENTPOST_AGENT`, and single-seat workspaces are
  unchanged. `routing.workspace_seats()` exposes the mailboxes a runtime in a
  directory may act as; a letter held by an unrelated mailbox stays out of
  reach.

## [1.2.0] - 2026-07-27

### Added

- `agentpost doctor` now includes a `send-path` check, and `PostOffice`
  exposes `verify_send_path()` behind it. Registration verified a mailbox
  once and nothing re-checked it afterwards, so a mailbox that could still
  receive and claim mail but had lost the ability to reply passed every
  doctor check. The probe exercises the delivery lock, atomic publish into
  `sent` and `unread`, letter serialization, and the notification queue,
  commits no letter, and removes every artifact it creates. Its detail line
  states what it cannot cover: doctor runs as an already-approved subprocess,
  so a host CLI permission layer that blocks `agentpost message` or
  `agentpost reply` is never observable from inside this check.

### Fixed

- A mailbox miss on `agentpost reply` now names the acting seat and the rule
  that chose it — explicit identity, workspace default, adapter binding, or
  declared project root. `message not found for pbeo` reported only which
  mailbox was searched, so acting as the wrong seat in a multi-seat workspace
  was indistinguishable from the letter being absent or the recipient being
  unreachable. `routing.identify_agent_source()` exposes the resolution rule;
  `identify_agent()` is unchanged.
- Offline delivery warnings no longer promise a next adapter start for a
  registered profile that has no adapter binding. That mailbox has nothing to
  start, so the warning now says the mail is durable but undeliverable until
  the mailbox is connected or started by a named launcher. Bindings are the
  discriminator, because presence folds the profile's own `cli` field into its
  connected adapters and reports one even when nothing is bound.
- `agentpost watch --help` now states that it is a read-only stream which
  acquires no inbound consumer lease, publishes no presence, injects no native
  notifications, and stops with the process. The unleased semantics were
  already specified in `docs/PROTOCOL.md`, but the command itself said
  nothing, and it reads as a persistent monitor.

### Changed

- Agent skills now treat setup and reconnection as a fail-closed workflow:
  durable mailbox access is distinct from live receipt, alternate identities
  require named launchers, and readiness requires adapter diagnostics plus an
  honest `agentpost armed` result.
- Consumer-lease collisions now report the live owner and deterministically
  suggest the first unused numbered identity while requiring explicit approval
  before a separate durable mailbox is created.

## [1.1.0] - 2026-07-12

### Added

- `agentpost review` and `AgentChannel.review()` validate immutable repository
  review artifacts before delivery. They require a canonical full commit SHA,
  verified paths and file-qualified tests, and optionally a direct parent.
- Review letters carry machine-readable artifact headers and a generated
  Markdown block that is rendered to the sender before mailbox commit.

### Changed

- Replying now atomically claims an exact unread original. Already-read
  originals remain replyable for corrections, including retry after an
  ambiguous post-claim delivery error.
- Reply urgency inference now lives in `PostOffice.reply()`: questions default
  to immediate and ordinary letters default to idle across CLI and Python use.

### Reliability

- Preflight failures reject unresolved artifacts, non-direct merge parents,
  missing tree paths, unqualified tests, and shell/placeholder syntax without
  writing recipient or sender mail.
- Concurrency coverage pins one winner when competing replies both observed an
  unread original, while validation failures leave the original retryable.

## [1.0.0] - 2026-07-11

First stable release.

### Core

- Durable literal-file mailboxes with atomic delivery, inspection, claim,
  fanout, correlated replies, panels, groups, discovery, and offline catch-up.
- Token-free notification adapters for Claude Code, managed and ordinary
  Codex, Antigravity CLI lifecycle hooks, and embedded Python runtimes.
- CLI-neutral identities, shared-workspace role selection, mailbox-wide
  consumer ownership, and deterministic presence reporting.

### Reliability

- Clean-install verification on Python 3.11, 3.12, and 3.13.
- Transactional adapter installation and mailbox-preserving rollback,
  reinstall, and uninstall coverage.
- Exact Message-ID notification pointers that never claim work and remain
  usable without an installed AgentPost skill.

### Security

- New runtime roots and durable files use owner-only permissions independent
  of umask; migration tightens existing AgentPost-owned runtime state without
  following symlinks.
- The trusted-local OS-account boundary, loopback-only managed Codex transport,
  installer trust model, and vulnerability-reporting path are documented.

### Compatibility

- The documented CLI, exported Python API, mailbox/profile migration path,
  plugin-invoked command shapes, and durable delivery semantics are stable for
  the 1.x release line.
- Published bootstrap commands and the default installer source are pinned to
  the versioned `v1.0.0` release tag.

[1.3.0]: https://github.com/5000Stadia/agentpost/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/5000Stadia/agentpost/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/5000Stadia/agentpost/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/5000Stadia/agentpost/releases/tag/v1.0.0
