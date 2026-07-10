# AgentPost Implementation Status

Last updated: 2026-07-10

## Current phase

The prior-art gate is complete and selected an independent literal-filesystem
semantic core. The measured agmsg comparison and live Claude/Codex evaluation
are in `PRIOR_ART_EVALUATION.md`. The initial public release is available at
`https://github.com/5000Stadia/agentpost`.

The local four-agent deployment now uses AgentPost as its sole actionable
development-agent channel. Claude projects K/PB/C run the project-scoped
`agentpost@agentpost-local` plugin at 0.0.2; Cx runs the Codex plugin. The prior
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
- Claude/Codex install, static doctor, and mailbox-preserving uninstall commands.
- Antigravity CLI 1.1.1 plugin, install/doctor/uninstall path, non-claiming
  PreInvocation catch-up, and Stop-boundary delivery with honest degraded
  already-idle wake reporting.
- Live adapter heartbeats/ownership, `agentpost armed`, and sender-side
  catch-up-only warnings after durable delivery.
- Durable `(CLI, project root)` bindings, automatic known-project reconnect,
  manual binding mode, and per-process mailbox overrides for shared projects.
- Derived `offline`/`idle`/`working` presence, active-only responsibility
  discovery, offline profile views, and durable exact-name offline delivery.
- Interactive first-run connection-policy selection plus `connect`,
  bare-root-resolving idempotent `join`, `disconnect`, `bindings`, `status`, and explicit
  Claude/Codex launchers.
- CLI-neutral `AgentRuntime` for Python agent systems: token-free watcher
  thread, single-owner heartbeat, working/idle boundaries, callback/queue
  delivery, and non-claiming restart catch-up.
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

The current suite contains 77 passing tests. Twenty consecutive pre-Antigravity
full-suite runs passed after the concurrency and UTF-8 fixes. A clean Python
virtual environment editable install and executable smoke test also passed.

A wheel was built and installed into a clean temporary home. Its bundled Codex
marketplace installed without the source checkout, static doctor stopped at the
expected explicit hook-trust gate, and uninstall retained unread mail.

Live acceptance passed on Claude Code 2.1.206 and Codex CLI 0.144.1. Claude
proved restart catch-up, already-idle wake, and busy-turn idle deferral. Codex
proved restart catch-up, active-turn immediate steering, a distinct post-turn
idle notification, bridge/fallback-hook exclusion, and child-state cleanup.
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
- Durable panel-completion notification and machine-readable adapter
  capability reporting.

See `ROADMAP.md` for priorities, optional candidates, and deliberate non-goals.

The legacy inboxes remain the recovery channel. Never place the same actionable
request in AgentPost and a legacy inbox; use legacy only for installation
control or a pointer after a proven notification failure.
