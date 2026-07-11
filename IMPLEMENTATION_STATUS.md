# AgentPost Implementation Status

Last updated: 2026-07-10

## Current phase

The prior-art gate is complete and selected an independent literal-filesystem
semantic core. The measured agmsg comparison and live Claude/Codex evaluation
are in `PRIOR_ART_EVALUATION.md`. The initial public release is available at
`https://github.com/5000Stadia/agentpost`.

The local four-agent deployment now uses AgentPost as its sole actionable
development-agent channel. Claude projects K/PB/C have the project-scoped
`agentpost@agentpost-local` plugin at 0.0.5 installed; Cx runs Codex plugin
generation `0.0.3+codex.20260710221500`, and the Python package is at 0.0.11.
Codex hook commands are stable across upgrades; a process that predates the
user prompt hook must reload before that event becomes live. The prior
Claude-to-Codex companion plugin, SQLite agentpost-eval prototype, global
Claude skills-dir workaround, and Cx filesystem inbox drain were decommissioned
on 2026-07-10 with historical data retained under the local AgentPost archive
or the original data directories.

## Implemented

- Python 3.11+ standard-library package and `agentpost` command.
- Atomic profile and group configuration writes.
- Profile-derived registry with exact selectors, token-overlap discovery,
  visible match reasons, and evidence-backed experience ranking.
- Literal UTF-8 Markdown mail with RFC-822-style headers.
- Atomic `tmp -> unread -> read` lifecycle, side-effect-free list/read, sender
  archive, stable physical ordering, and duplicate-delivery protection.
- Direct and group send with one shared Message-ID and per-recipient copies.
- Named groups, ad hoc lists, and role/project/specialty selectors.
- Correlated replies, direct/group questions, panel derivation, quorum,
  timeout, pending/error state, late answers, and duplicate response retention.
- CLI smoke coverage for discovery, group ask/reply, and panel rendering.
- Bell-adapter interface, deterministic fake, and token-free mailbox watcher.
- Claude Code marketplace plugin with a live monitor, exact catch-up,
  immediate wake, and delayed idle-boundary behavior.
- Codex plugin plus `agentpost codex` loopback app-server binding with live
  catch-up, `turn/steer`, idle deferral, exact-ID processing, and fallback-hook
  ownership suppression.
- Token-free Codex `SessionStart`/`UserPromptSubmit`/`Stop` catch-up, exact
  executed-generation markers that never imply presence, `3/3` hook-trust
  verification, stale/unobserved/ambiguous generation diagnostics, and
  explicit approval, reinstall, and reload recovery.
- Claude/Codex install, deterministic doctor, and mailbox-preserving uninstall
  commands.
- Antigravity CLI 1.1.1 plugin, install/doctor/uninstall path, non-claiming
  PreInvocation catch-up, and Stop-boundary delivery with honest degraded
  already-idle wake reporting.
- Live adapter heartbeats, mailbox-wide cross-adapter consumer leases,
  diagnostic runtime-instance ownership, `agentpost armed`, and sender-side
  catch-up-only warnings after durable delivery.
- CLI-neutral profile v2 identities, machine-local workspace defaults and
  known alternates, legacy adapter bindings, automatic known-project reconnect,
  manual binding mode, and per-process mailbox overrides for shared projects.
- Derived `offline`/`idle`/`working` presence, active-only responsibility
  discovery, offline profile views, and durable exact-name offline delivery.
- Interactive first-run connection-policy selection plus `connect`,
  bare-root-resolving idempotent `join`, `disconnect`, `bindings`, `status`, and explicit
  Claude/Codex launchers.
- CLI-neutral `AgentRuntime` for Python agent systems: token-free watcher
  thread, standby takeover, owner-only heartbeat, working/idle boundaries, callback/queue
  delivery, ordered callback retry with visible exhaustion, async consumption,
  unread reconciliation, and non-claiming restart catch-up.
- Human-facing channel addressing with an inspectable identity directory,
  ambiguity-safe name/display/project/responsibility resolution, inferred
  senders, natural named groups, and live-versus-queued delivery receipts.
- Sender-bound `AgentChannel` Python API with the same directory,
  resolve/message/question vocabulary as the CLI and direct availability as
  `AgentRuntime.channel`.
- Durable nameplate authoring guidance in registration help and installed
  skills, including searchable summaries, concrete handles, project aliases,
  stable ownership boundaries, and CLI support for organization/exclusions.
- Evidence-gated per-agent legacy cutover policy, preserving unconfirmed
  agents independently and requiring a post-cutover direct/reply/restart test.
- Tested two-agent getting-started walkthrough and executable smoke test covering
  registration, project binding, display-name delivery, exact claim, reply, and
  correlation without a model call.

## Verification

Run:

```sh
cd /path/to/agentpost
PYTHONPATH=src python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests
```

The current suite contains 112 passing tests. Twenty consecutive pre-Antigravity
full-suite runs passed after the concurrency and UTF-8 fixes. A clean Python
virtual environment editable install and executable smoke test also passed.

The final deployed-architecture council panel completed 3/3: K, PB, and
Construct all returned GREEN with no blocking findings. PB's reply-urgency and
presence-freshness polish was folded into 0.0.8.

The 0.0.11 wheel was built and installed into a clean temporary virtual
environment and home. Its Claude, Codex, and Antigravity integrations all
materialized without the source checkout, and the installed CLI passed the
executable two-agent smoke. The packaged Claude integration is generation
0.0.5. Its monitor no longer depends on `CLAUDE_PLUGIN_DATA`, which Claude Code
2.1.206 does not export to monitor processes, and doctor now requires the
current enabled entry for the exact project being diagnosed. The expected
generation is derived from the packaged manifest, and an unbound monitor exits
quietly instead of crash-looping after missing runtime state. The packaged
Codex bridge accepts the launcher's kebab-case ownership arguments and fails a
malformed startup visibly.

Live acceptance is being rerun on Claude Code 2.1.206 and Codex CLI 0.144.1.
Managed Codex has proved restart catch-up, already-idle wake, and active-turn
immediate steering plus post-turn idle deferral; child-state cleanup remains
open. Claude K, PB, and C each proved project-local 0.0.5 fresh-load monitor
startup, already-idle wake before any user prompt, exact-ID claims, and
correlated replies. K and PB additionally completed active-turn immediate and
post-turn idle-deferral probes. C completed active-turn immediate delivery; its
idle probe remains correctly deferred while C's real work turn is still active.
The Codex generation slice additionally proved `3/3` current hook discovery,
token-free trust inspection through `hooks/list`, per-event generation stamps,
and stable trust across plugin reinstall.
Kernos independently returned GREEN on the complete diff and reran 111 tests.
Its two non-blocking notes were then implemented: packaged-manifest version
derivation and graceful unbound-monitor exit. Kernos returned focused GREEN on
that delta and independently reran all 112 tests with no new findings. The
standalone smoke and suite also pass with inherited `AGENTPOST_AGENT` and
`AGENTPOST_ROOT` deliberately set to unrelated values.
Antigravity CLI 1.1.1 proved plugin loading, exact next-prompt catch-up, claim,
and correlated reply. Its documented sidecar shape was also installed and
enabled experimentally, but the CLI did not initialize `SidecarManager` or
start the process; the integration therefore retains truthful lifecycle-only
delivery.

## Not yet implemented

- Antigravity CLI already-idle external wake. The IDE/App sidecar mechanism did
  not run on CLI 1.1.1; lifecycle catch-up is the accepted CLI behavior.
- Opt-in live doctor automation, final rollback acceptance, and an automated
  clean-install matrix.
- Generation-truth diagnostics for Claude and Antigravity; the Codex slice is
  implemented and accepted.
- Durable panel-completion notification and machine-readable adapter
  capability reporting.

See `ROADMAP.md` for priorities, optional candidates, and deliberate non-goals.

Legacy inbox directories are read-only history and are no longer polled. Never
place the same actionable request in AgentPost and a legacy inbox. After a
proven notification failure, use direct installation control or a pointer to
the existing AgentPost Message-ID, never a duplicate work request.
