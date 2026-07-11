# Changelog

AgentPost follows [Semantic Versioning](https://semver.org/). The supported
compatibility surface is defined in [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

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

[1.0.0]: https://github.com/5000Stadia/agentpost/releases/tag/v1.0.0
