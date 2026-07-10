# AgentPost Prior-Art Evaluation

Date: 2026-07-09
Decision: build the AgentPost semantic core independently; use agmsg as
adapter and installer prior art, not as the durable transport.

## Scope

This evaluation executed the build-versus-adopt gate in `SPEC.md` Section
26.3 against:

- agmsg version `1.1.6` at commit
  `89980f9c79d0de6475f82041286568e3887e6f85`;
- Codex CLI `0.144.1`;
- Claude Code `2.1.204`;
- the current Cx and K sessions on this machine.

Gemini was intentionally not invoked, updated, or authenticated.

## Upstream Test Results

The agmsg source contained 632 Bats tests across approximately 9,320 test
lines.

The first serial run passed its first 113 tests before it was stopped because
the suite contains deliberate timeout waits and GNU `parallel` was unavailable.
The suite was then run four test files at a time with separate logs:

- 625 tests passed immediately;
- five watcher tests failed because parallel/live-Codex process ancestry made
  their inferred agent PID differ from the fixture's assumption;
- all 17 watcher tests passed when rerun with the suite's supported
  `AGMSG_AGENT_PID=''` deterministic fallback;
- one `whoami` test expected Claude as the fallback, but the implementation
  correctly detected the real Codex ancestor process;
- one Node-resolution test assumed `/usr/bin:/bin` contained no Node, while
  this machine has `/usr/bin/node`.

No product defect was established by the two remaining host-assumption
failures. The exercise did establish that process-tree identity tests must be
run from both ordinary shells and live agent processes.

## Isolated Store Experiment

Two messages were sent in rapid succession to a temporary agmsg store.

Observed:

- the read-only JSON API returned both without changing `read_at`;
- `inbox.sh` displayed both and changed both rows to read;
- because both had the same one-second timestamp and inbox ordering used only
  `created_at`, the displayed order was reversed;
- the active schema was exactly:
  `id, team, from_agent, to_agent, body, created_at, read_at`.

This is a sound small chat transport but cannot directly express AgentPost's
Message-ID, In-Reply-To, audience, notification intent, sender archive,
per-recipient delivery identity, or structured panel state.

## Live Claude Result

An isolated installation named `agentpost-eval` registered two disposable
identities:

- one Codex project agent;
- one Claude Code project agent.

The legacy inbox carried setup control only. The actual test question traveled
only through agmsg.

Sequence:

1. K armed agmsg's Claude monitor in its existing live session.
2. K acknowledged through agmsg message 1.
3. Cx sent uniquely identified question `EVAL-Q-7F3A` as message 2.
4. K's monitor woke the idle Claude session.
5. K returned exact answer `EVAL-A-7F3A` as message 3.
6. No legacy reply was created.

The question was sent at `2026-07-10T03:01:05Z`; the answer was stored at
`2026-07-10T03:01:16Z`.

Result: agmsg's Claude monitor proves live, token-free external wait plus
semantic agent wake on this machine.

## Live Codex Result

A disposable `cx-live` Codex identity and TUI were created in the AgentPost
development checkout.

Setup exposed three required installer gates:

1. The first join inherited an already registered ancestor project and had to
   be repeated with project resolution disabled to preserve the exact binding.
2. The project hook file was ignored until the development checkout was added
   as a trusted Codex project.
3. Codex separately required interactive review and trust of the new hooks.

After those gates and one initial turn:

- agmsg started a localhost Codex app-server;
- the bridge discovered and resumed the loaded TUI thread;
- a shell-only `watch-once` process waited on `cx-live`;
- K sent `EVAL-CODEX-Q-91B2` as message 5 at
  `2026-07-10T03:04:14Z`;
- the bridge injected the unread message into the live Codex thread through
  app-server, without terminal keystrokes;
- Codex returned `EVAL-CODEX-A-91B2` as message 6 at
  `2026-07-10T03:04:24Z`;
- K received the reply through its Claude monitor.

Result: the Codex app-server strategy works end to end on the installed Codex
version. Project trust, hook trust, exact identity binding, first-turn arming,
and cleanup must all be explicit doctor checks.

The disposable Codex TUI, bridge, app-server, and K evaluation monitor were
stopped after the test. The `agentpost-eval` installation and its six-message
test evidence remain available locally for audit; no evaluation watcher is
active.

## Acceptance Comparison

| AgentPost requirement | agmsg result | Classification |
| --- | --- | --- |
| Cross-vendor local messaging | Claude and Codex live path passed | Reuse as prior art |
| Token-free waiting | `watch.sh` and `watch-once.sh` passed | Reuse pattern |
| Claude idle wake | Live monitor passed | Reuse pattern |
| Codex app-server wake | Live bridge passed after trust gates | Reuse pattern |
| Literal Markdown mailbox | SQLite rows | Conflict |
| Side-effect-free list/read | JSON API yes; inbox no | Partial |
| Explicit atomic claim | Bulk `read_at` update | Conflict |
| Unread is delivery truth | Claude watermark and Codex read behavior differ | Conflict |
| Restart catches every unread | Fresh Claude watchers start from now | Conflict |
| Stable message order | Same-second inbox order reversed | Conflict |
| Immutable Message-ID | Current schema uses integer row ID | Conflict |
| Per-recipient delivery identity | Not represented | Missing |
| Reply threading | Prompt convention only | Missing |
| Named/ad hoc group fan-out | Team exists; send is one recipient | Partial |
| Panel quorum and late replies | Not represented | Missing |
| Per-message immediate/idle | Delivery mode is runtime/project scoped | Conflict |
| Responsibility directory | Names, types, and projects only | Missing |
| Specialty/evidence routing | Not represented | Missing |
| Single-channel migration | Can be followed operationally | Compatible |
| Install/uninstall experience | Broad and well tested | Reuse pattern |

## Option Assessment

### Contribute all AgentPost behavior upstream

Rejected as the primary path. The change would replace or deeply alter agmsg's
message schema, read semantics, catch-up model, delivery-mode scope, identity
model, and product vocabulary. That is not a focused upstream contribution.
Small adapter fixes or documentation improvements may still be contributed.

### Companion layer over agmsg transport

Rejected as the durable architecture. Maintaining Markdown truth plus an agmsg
SQLite pointer copy would create two stores, two read cursors, and ambiguous
recovery. It would also leave immediate/idle intent mismatched with agmsg's
project-scoped delivery modes.

### Narrow fork

Rejected. The MIT license permits it, but a fork would inherit process spawning,
role lifecycle, multiple storage directions, and compatibility surfaces beyond
AgentPost's scope while still requiring invasive protocol changes.

### Independent core with informed adapters

Selected.

Build the small standard-library AgentPost filesystem core defined in
`SPEC.md`. Implement its adapters against native CLI surfaces, using agmsg's
tests and failure cases as prior art. If source code is copied rather than
independently implemented, preserve the MIT notice and identify the derived
files explicitly.

## Consequences

- AgentPost keeps one durable truth: literal immutable Markdown letters.
- The core remains independent of SQLite, Bash, MCP, and a running daemon.
- Claude and Codex adapters must reproduce the proven live behaviors without
  importing agmsg's read cursor or watcher watermark semantics.
- Static doctor must verify exact project identity, project trust, hook trust,
  and adapter ownership before a live test.
- Notification must never mark mail read.
- Catch-up always starts from the unread directory, never from a seeded
  "current maximum" watermark.
- Same-second sends remain ordered by immutable filename/Message-ID rules, not
  timestamp alone.
- The then-planned Gemini adapter was deferred. Google subsequently moved
  consumer CLI users to Antigravity CLI; `ROADMAP.md` now controls that work.

## Next Slice

Implement and test only the standalone semantic core first:

1. runtime-root initialization;
2. profile registration and registry scanning;
3. atomic direct delivery with immutable Markdown files;
4. side-effect-free list/read;
5. explicit atomic claim;
6. duplicate `(Message-ID, recipient)` rejection;
7. sent archive and reply threading.

Do not install native AgentPost adapters into K, PB, C, or Cx until this core
passes its deterministic acceptance tests.
