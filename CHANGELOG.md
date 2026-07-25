# Changelog

AgentPost follows [Semantic Versioning](https://semver.org/). The supported
compatibility surface is defined in [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

## Unreleased

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

[1.1.0]: https://github.com/5000Stadia/agentpost/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/5000Stadia/agentpost/releases/tag/v1.0.0
