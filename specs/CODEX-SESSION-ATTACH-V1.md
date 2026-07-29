# CODEX-SESSION-ATTACH-V1

**Status:** Implemented
**Scope:** No-restart mailbox identity attachment for an active Codex thread
**Origin:** Pattern Buffer Evolution multi-seat identity failure, 2026-07-28

## Problem

An ordinary Codex thread may start from a workspace whose default mailbox is
`pbeo` even though the intended seat is the alternate `pbeocx`. The process
environment and already-loaded hook commands cannot be rewritten safely after
startup. Running `agentpost join pbeocx --cli codex` is the wrong recovery:
`join` owns durable adapter installation and may need global plugin replacement,
which remains forbidden inside a live Codex thread.

Three concerns must remain independent:

1. project and adapter binding, owned by `join` and `install`;
2. the mailbox selected for one active Codex thread;
3. global Codex plugin installation or replacement.

## Command

From the active Codex thread:

```sh
agentpost attach pbeocx
```

`attach` resolves the explicit mailbox, requires `CODEX_THREAD_ID`, verifies
that the mailbox is a known seat at the current project root, and finds a hook
observation for that exact thread ID. A recognized stable dispatcher ABI is
required. The operation then atomically records an owner-only, session-scoped
identity selection without changing:

- `AGENTPOST_AGENT` or any parent-process environment;
- the workspace default or adapter binding;
- Codex configuration, user hooks, marketplace state, plugin cache, or trust;
- mailbox presence or a consumer lease.

`attach` is the chosen verb. It describes adding session-local routing while
avoiding the durable/global implications of `join`, `connect`, or `install`.

## Identity precedence

Codex identity resolution is:

1. an explicit command identity, `--from`, `--agent`, or
   `AGENTPOST_AGENT`;
2. a valid attachment for the exact Codex thread;
3. the existing workspace-default, adapter-binding, and declared-root rules.

The hook uses the thread ID in its event payload. AgentPost CLI subprocesses
inside the thread use `CODEX_THREAD_ID`. Both therefore select the same
mailbox after attachment. An explicit environment identity that conflicts with
the requested mailbox is rejected because the attachment could not take
effect.

## Storage and lifecycle

The attachment is stored under:

```text
~/.agentpost/runtime/codex-sessions/<sha256(CODEX_THREAD_ID)>.json
```

The raw thread ID is not used as a filename or stored in the document. The
document records schema version, mailbox, project, attachment and expiry times,
and the lifecycle event and hook generation that proved compatibility.

- The directory is mode `0700`; documents are mode `0600`.
- Reads securely traverse owner-private runtime directories without following
  symlinks and reject non-regular files, wrong ownership, permissive directory
  or file modes, malformed JSON, schema mismatch, digest mismatch, unknown
  hook events, incompatible dispatcher generations, non-finite or incoherent
  timestamps, uninitialized mailboxes, and seats no longer reachable from the
  recorded project.
- Writes use a same-directory temporary file, `fsync`, and atomic replacement.
- Attachments expire after 30 days. The next lookup removes an expired entry
  and resumes normal workspace identity resolution.
- Repeating the same attachment is idempotent. Naming another reachable seat
  explicitly rebinds the thread.
- Ordinary Codex resume keeps the attachment until expiry because the thread
  ID is stable. Managed resume remains authoritative through its explicit
  `AGENTPOST_AGENT`.

## Hook and plugin compatibility

The attachment path depends only on the stable dispatcher command and event
thread ID, not on plugin cache equality. Hook generations from
`0.0.3+codex...` onward have the required dispatcher ABI. A thread observed on
`0.0.4` may therefore attach safely while `0.0.5` is installed. Unknown,
malformed, or older observed generations fail before writing session state.

`attach` never calls the installer. Separately, `join` preserves an installed
newer generation when its release line shares the stable dispatcher ABI; an
older AgentPost runtime must not replace that generation with its own older
artifact. Incompatible or ambiguous generation state retains the existing
terminal-only replacement contract:

1. close all Codex sessions;
2. run from a terminal;
3. acknowledge with `--confirm-codex-sessions-closed`;
4. replace under the exclusive plugin lock.

Global Codex plugin replacement or removal remains forbidden from inside a
live Codex thread.

## Delivery and presence

For an ordinary already-running thread, success reports:

```text
ATTACHED	pbeocx	codex-session	<digest-prefix>
DELIVERY	boundary-only	observed-hook=0.0.4+...	installed-plugin=0.0.5+...
PRESENCE	boundary-only; attach publishes no presence and cannot wake an already-idle thread
NEXT	for already-idle wake, relaunch with `agentpost codex --agent pbeocx resume THREAD_ID`
```

At the next `UserPromptSubmit` or `Stop` boundary, the compatible stable hook
selects the attachment and surfaces exact unread Message-IDs for that mailbox.
This is lifecycle-boundary catch-up, not continuous wake. The hook attempts the
existing ephemeral mailbox consumer lease and never claims mail.

True already-idle wake and active-turn steering remain the managed-launcher
contract:

```sh
agentpost codex --agent pbeocx resume THREAD_ID
```

That launcher creates the app-server/WebSocket bridge before the client starts.
`attach` does not claim it can manufacture such a bridge in an ordinary
already-running Codex process. It reports `live-bridge` only when the current
managed session already owns that bridge.

Because a boundary-only attachment has no heartbeat and holds no lease between
events, `status` remains `offline` and `armed` remains `QUEUED`. Those results
are honest and do not invalidate the session identity selection.

## Doctor diagnostics

When `doctor` runs inside a thread with a valid attachment, it reports a
separate `codex-session-attachment` check. That check names the exact thread
digest, selected mailbox, boundary-only capability, observed dispatcher
generation, and installed plugin generation.

The existing `codex-generation` check remains a separate aggregate recovery
signal for the mailbox's `SessionStart`, `UserPromptSubmit`, and `Stop`
observations. It may remain `FAIL` after a successful attachment when older
session boundaries have not re-executed. That failure means a reload is still
needed for complete aggregate generation parity; it does not negate a `PASS`
for the exact attached thread or upgrade boundary-only delivery into live wake.

## Safety and failure behavior

- The target must be a registered, initialized mailbox reachable as a seat
  from the selected project root.
- The current thread must have an exact hook observation with a compatible ABI.
- A conflicting `AGENTPOST_AGENT` fails before mutation.
- A live inbound consumer for the target mailbox fails before mutation, except
  for the current managed session's already-established bridge.
- A hook boundary that later loses the consumer-lease race emits no duplicate
  notification and leaves mail unread.
- Corrupt, insecure, expired, unreachable, or incompatible attachment state
  never silently selects another attached mailbox.
- No attachment operation changes or downgrades plugin artifacts.

## Acceptance tests

The required regression fixture is:

- workspace default `pbeo`;
- alternate seat `pbeocx`;
- ordinary active Codex thread;
- unset `AGENTPOST_AGENT`;
- active thread observed on hook generation `0.0.4`;
- installed plugin generation `0.0.5`.

It must attach `pbeocx` without plugin mutation, use `pbeocx` for subsequent
CLI sends, and inject `pbeocx` unread IDs at the next hook boundary without
claiming them.

Coverage also pins idempotent attach, explicit rebind, wrong or unreachable
mailbox, explicit-environment conflict, stale mapping expiry, insecure state,
unknown/old hook ABI, consumer-lease conflict, managed-resume continuity,
missing live thread identity, and preservation of a compatible newer plugin by
an older `join`. Doctor coverage requires an exact-thread attachment `PASS` to
remain visible beside a stale aggregate generation `FAIL`.

## Open decision

No host-supported API for attaching an app-server/WebSocket bridge to an
arbitrary already-running Codex process has been verified. If Codex exposes
one, a later spec may add an explicit capability negotiation that upgrades an
attachment from `boundary-only` to live wake. V1 must not infer or emulate that
capability.
