# Safe session re-entry and startup mail consent v1

**Status:** Implemented
**Scope:** Managed-consumer recovery, cross-seat Codex resume diagnostics, and
consent-gated unread catch-up for every interactive AgentPost adapter
**Origin:** A stopped managed Codex launcher retained the
`jobstratassistcx` consumer lease while its heartbeat was stale, followed by a
resume of the same Codex thread under the wrong `kreview` seat, 2026-08-04

## Problem

Two independent behaviors make correcting a wrongly selected mailbox harder
than it should be.

First, an AgentPost-managed CLI is a process tree. Suspending that foreground
tree with terminal job control stops its bridge heartbeat but does not close
the process or its file descriptors. The mailbox therefore has all three of
these properties at once:

- the exclusive `consumer.lock` is still held;
- the owner PID is alive but stopped;
- the heartbeat is stale, so `status` and `armed` currently describe the
  mailbox as offline with no live consumer.

A later named launch correctly fails to acquire the lock, but its generic
conflict diagnostic recommends a numbered mailbox. That advice is wrong for a
suspended owner the user intended to close: a numbered mailbox would split
future mail instead of recovering the existing seat.

Second, startup catch-up is non-destructive at the transport layer but eager at
the prompt layer. The adapters do not read or claim mail themselves. They
inject instructions telling the model to inspect the pending Message-IDs, and
the model naturally begins those workflows before the user can verify that the
right conversation, workspace, and AgentPost seat were loaded.

Correcting identity after that point is too late: message contents and their
workflows are already in the wrong conversational context.

## Goals

V1 must:

1. distinguish a healthy consumer from a suspended or unresponsive lease
   owner;
2. recover an exact AgentPost-managed consumer without deleting or splitting
   its mailbox;
3. prevent future terminal suspension from stranding a managed consumer lease;
4. detect an attempt to resume one Codex thread under two AgentPost seats;
5. turn every interactive adapter's startup catch-up into a user-consent gate;
6. leave startup mail unread and unclaimed across a reload;
7. preserve exact Message-ID scoping after the user authorizes inspection;
8. keep live post-startup notification semantics separate from startup policy.

V1 does not:

- move mail between mailbox identities;
- create numbered mailboxes as recovery for a stopped owner;
- make `attach` claim a live consumer lease or manufacture a live bridge;
- infer user consent from silence, a reload, message priority, or an agent's
  enthusiasm to continue;
- allow two live consumers to process the same mailbox;
- require a new durable message state beyond `unread` and `read`.

## Terminology

**Startup catch-up** is the complete unread snapshot surfaced when an adapter
or host conversation becomes available. It includes mail delivered while that
runtime was absent.

**Live delivery** is a notification first observed after startup catch-up has
completed in the current runtime.

**Consent gate** is an adapter instruction that announces pending mail and asks
the user whether to inspect it. It explicitly prohibits reading, listing,
claiming, replying to, or beginning work from that mail before the user's
choice.

**Managed consumer** is an AgentPost-owned process that holds the authoritative
inbound lease and for which AgentPost can prove the adapter, PID, instance ID,
and launch boundary.

## Startup consent contract

### Default behavior

The default startup policy for every interactive CLI is `ask`.

When unread mail exists at startup, the adapter starts at most one model turn
for the current catch-up batch. That turn receives an instruction shaped as:

```text
AgentPost startup notice: N unread messages exist for mailbox NAME. They are
still unread and unclaimed. Do not list, read, claim, reply to, or begin work
from them yet. Tell the user that mail is waiting and ask whether to inspect
this exact pending set in the current session, reload or rebind the intended
session first, or defer it. Do not make the choice for the user.
```

The adapter context retains the immutable Message-IDs in the catch-up batch,
but the conversational response should normally expose only the mailbox and
count. Sender, subject, body, attachments, and work instructions are not read
to construct the gate.

`immediate` priority may cause the gate to surface at the earliest supported
boundary. It does not authorize inspection and does not bypass the gate.

### User choices

The gate asks one concise question and accepts these outcomes:

1. **Read now.** The agent may inspect only the Message-IDs captured by that
   gate. Inspection still does not claim them. Each message is claimed only
   when its work actually begins, using the existing atomic claim contract.
2. **Reload or rebind first.** The agent performs no mailbox read, list, claim,
   reply, or work action. It reports the currently selected seat and the exact
   launcher or attachment command that applies. The unread set is surfaced as
   a fresh consent gate when the replacement runtime starts.
3. **Defer.** The adapter suppresses the same startup batch for the remainder
   of that runtime unless the sender explicitly re-notifies it. The messages
   remain unread and are gated again on a later runtime start.

Consent applies only to the exact Message-IDs announced by one gate. Mail that
arrives afterward is not silently added to an already authorized batch.

### Durable and ephemeral state

The mailbox remains the durable truth. A gate does not add a mailbox state and
does not move files from `unread`.

Adapter-local state may record that a Message-ID was announced during the
current runtime so lifecycle hooks do not ask repeatedly. That record is an
ephemeral attention ledger, not proof of inspection, claim, completion, or
user consent.

The ledger is scoped to a runtime epoch, not merely to a durable conversation
ID. Resuming the same conversation in a new CLI process must gate the still
unread set again. A notification-request record may be acknowledged once the
gate was successfully surfaced because restart catch-up comes from the unread
spool, not from that request record.

If the adapter cannot prove whether an announcement belongs to the current
runtime epoch, it fails safe by presenting another gate. Duplicate questions
are preferable to processing mail in the wrong context.

## Adapter requirements

| Adapter | Startup boundary | Required V1 behavior |
| --- | --- | --- |
| Managed Codex bridge | `initialCatchup()` after the loaded thread is known | Replace the current imperative `deliver()` call with one batched consent-gate turn. Populate the in-memory known set without reading mail. |
| Ordinary Codex hooks | `SessionStart`; first compatible boundary if `SessionStart` was unavailable | Inject a gate and write a thread-and-runtime-scoped announcement ledger. `UserPromptSubmit` and `Stop` must not replace that gate with an imperative read instruction for the same IDs. |
| Claude monitor | First successful lease acquisition and watcher snapshot | Batch the full initial snapshot into one gate instead of printing one imperative pointer per message. Later live notifications retain immediate/idle scheduling. |
| Antigravity hooks | First invocation for a conversation in the current host-process epoch | Inject one gate and scope its announcement ledger to both conversation and runtime epoch. If no reliable runtime epoch is available, gate again rather than auto-process. |
| Embedded Python `AgentRuntime` | First callback or queue batch after lease acquisition | Transport remains model-neutral. The batch must identify its origin as startup catch-up so an interactive host can apply the same gate. AgentPost itself still never calls a model. |

For all adapters, successful gate delivery may update attention bookkeeping but
must not call `read`, `next`, `reply`, or application work handlers.

## Live delivery after startup

V1 changes startup catch-up, not the established live-delivery contract.

After the startup gate has been surfaced, mail first delivered during that
runtime continues to use `immediate` and `idle` scheduling. A future policy may
offer `ask` for every live message, but that is a separate choice and must not
delay this safety correction.

If live mail arrives while the startup gate's question is still outstanding,
it is surfaced as a separate exact notification batch. The user's later
authorization for the startup batch does not authorize the new batch.

## Skill and prompt contract

The shared AgentPost skill must recognize a native startup notice as distinct
from an ordinary Message-ID notification.

For a startup notice, the agent must not run `agentpost list`, `read`, `next`,
or `reply`. It must:

1. state the pending count and selected mailbox;
2. ask whether to read now, reload or rebind first, or defer;
3. wait for the user's answer;
4. on `read now`, inspect exactly the gate's Message-IDs;
5. on `reload`, give the exact recovery launcher and stop mailbox work;
6. on `defer`, leave the batch untouched.

An ordinary live notification retains the existing exact-ID workflow. The two
instruction forms must be mechanically distinguishable so generic mail rules
cannot override the startup gate.

## Consumer-state model

Presence and lease ownership are separate evidence and must be reported
together.

| State | Heartbeat | Lease | Owner process | Meaning |
| --- | --- | --- | --- | --- |
| `idle` / `working` | fresh | held | running | Healthy live consumer |
| `offline` | absent or stale | free | absent or irrelevant | No consumer owns the mailbox |
| `suspended` | stale | held | stopped (`T`/`t`) | Terminal job control stopped a managed owner without releasing its lock |
| `unresponsive` | stale | held | running | Owner still holds the lock but its adapter heartbeat failed |
| `incoherent` | any | held | missing or unverifiable | Fail-closed ownership requiring manual diagnosis |

`status` prints the specific state and exact owner evidence. `armed` remains
nonzero for `suspended`, `unresponsive`, and `incoherent`; its detail must name
the held lease rather than saying `no live mailbox consumer`.

The generic numbered-mailbox suggestion is allowed only for a healthy,
unrelated live owner when the user genuinely requested parallel work. It is
never offered for a suspended, unresponsive, same-thread, or otherwise
recoverable owner.

## Guarded consumer recovery

V1 adds an explicit administrative command:

```sh
agentpost consumer-stop NAME --instance FULL_INSTANCE_ID
```

The exact instance ID is required to prevent a stale terminal instruction from
stopping a replacement consumer that won a later lease. The command:

1. loads the named mailbox and current owner record;
2. verifies the instance ID byte-for-byte;
3. proves that the mailbox lock is still held;
4. proves that the PID belongs to an AgentPost-managed consumer for that
   mailbox;
5. requests the adapter's normal shutdown path;
6. resumes only a stopped launcher when needed for that shutdown handler to
   run;
7. waits for child cleanup, marker removal, and lease release;
8. reports `STOPPED` only after a nonblocking lease probe succeeds.

It never deletes mail, profile data, bindings, attachments, or notification
requests. It does not send `SIGKILL` by default. A mismatched instance, PID
reuse, unverifiable command line, non-AgentPost process, or failed graceful
shutdown fails without pretending the mailbox is free.

Example suspended-owner diagnostic:

```text
mailbox jobstratassistcx has a suspended AgentPost consumer: codex pid 14971
instance 296d3e...; it is offline but still holds the inbound lease. If the
session was intentionally closed, run `agentpost consumer-stop
jobstratassistcx --instance 296d3e508bf5431faf25b3ab572cc651` and then retry
the original launcher. Do not create jobstratassistcx2 for this condition.
```

## Managed terminal signals

A managed consumer cannot safely remain suspended: its heartbeat and native
wake path are stopped while its exclusive lease remains live.

The Codex and Antigravity launchers therefore intercept terminal suspension
while they own a mailbox. `SIGTSTP` is converted into a clean managed shutdown:
the remote client, bridge, app server, marker, consumer lease, and plugin lock
are released before the launcher exits with a signal-derived status. The
terminal explains that managed sessions are stopped rather than suspended and
prints the resume command when it can be reconstructed.

Normal `SIGINT`, terminal hangup, child exit, startup failure, and bridge
failure use the same cleanup invariant. No exit path may leave the parent
alive and stopped while it owns `consumer.lock`.

Existing already-suspended launchers cannot execute new signal handling until
resumed, which is why `consumer-stop` remains necessary for recovery.

## Cross-seat Codex resume protection

For managed Codex resumes, the owner metadata records a digest of the Codex
thread ID and the selected AgentPost seat. The raw thread ID need not be stored
in AgentPost runtime metadata.

Before launching:

```sh
agentpost codex --agent TARGET resume THREAD_ID
```

AgentPost scans verified live managed Codex owners. If the same thread digest
is already active under another seat, startup fails before acquiring the target
mailbox and reports:

- the existing seat, PID, and instance ID;
- whether it is healthy, suspended, or unresponsive;
- the exact guarded stop command when AgentPost can safely provide one;
- that `attach` is boundary-only and cannot transfer the live bridge;
- that the supported full-wake rebind is stop, then relaunch under `TARGET`.

AgentPost never silently transfers unread mail or a live consumer lease between
seats. A thread and a mailbox are separate durable identities even when the
user intends to pair them differently on the next launch.

## Compatibility and rollout

- Mailbox layout and `unread`/`read` semantics do not change.
- Existing `message`, `question`, `read`, `next`, and `reply` commands retain
  their contracts.
- `armed` keeps its existing success and non-success exit codes. Diagnostic
  wording and `status` state become more precise.
- Interactive startup behavior intentionally changes from eager inspection to
  `ask`.
- Live post-startup delivery retains its current scheduling behavior.
- Python callbacks remain transport-only; startup-origin metadata is additive.
- Older consumer owner documents without a thread digest remain valid and may
  participate in same-thread cross-seat detection when AgentPost can recover
  the resume or fork thread from a verified managed launcher command line.
- Adapter-local announcement ledgers may be discarded at any time; the result
  is another consent gate, never lost mail or automatic processing.

The shared skill, generated Claude/Codex/Antigravity skill copies, packaged
integration data, CLI help, installation documentation, and compatibility
documentation must ship together so no adapter retains the old imperative
startup wording.

## Acceptance tests

### Consent gate

1. One unread startup message produces one question and zero calls to `read`,
   `next`, `reply`, or a work handler.
2. Multiple unread startup messages produce one batched gate.
3. `immediate` startup mail still produces a gate rather than inspection.
4. `read now` permits inspection of exactly the gated IDs; a concurrently
   delivered ID is excluded.
5. `reload first` leaves every gated message unread and causes the replacement
   runtime to gate the same set again.
6. `defer` suppresses the batch only for the current runtime.
7. Codex `UserPromptSubmit` and `Stop` do not replace an unresolved startup
   gate with an imperative read instruction.
8. Claude batches initial watcher output but retains later immediate/idle
   behavior.
9. Antigravity resumes with the same conversation ID in a new process and
   gates unread mail again.
10. Python startup callbacks are marked as catch-up and still do not call a
    model or claim mail.

### Consumer lifecycle

1. A stopped owner with a stale heartbeat and held lock reports `suspended`,
   not `offline`.
2. `armed` remains nonzero and names the suspended PID and instance.
3. Lease acquisition against a suspended owner does not suggest a numbered
   mailbox.
4. `consumer-stop` rejects a missing or mismatched instance ID without sending
   a signal.
5. `consumer-stop` cleanly releases an exact stopped managed owner and does not
   alter mailbox contents.
6. Suspending a new managed Codex or Antigravity launcher invokes cleanup and
   leaves no held mailbox or plugin lock.
7. The same Codex thread cannot be managed concurrently under two seats.
8. Distinct threads and distinct mailboxes remain concurrently supported.
9. A healthy unrelated owner still retains the fail-closed parallel-identity
   advice.

## Implementation boundaries

The primary implementation sites are:

- `src/agentpost/ownership.py` for verified owner state, lock probing, and
  guarded consumer shutdown;
- `src/agentpost/presence.py` and `src/agentpost/installer.py` for truthful
  suspended/unresponsive diagnostics;
- `src/agentpost/native.py` for CLI signal cleanup, Codex hook gates, Claude
  startup batching, and Antigravity runtime-epoch gates;
- `src/agentpost/data/codex_bridge.mjs` for managed Codex startup gating;
- `src/agentpost/runtime.py` for additive startup-origin metadata;
- `src/agentpost/cli.py` for `consumer-stop` and exact recovery output;
- `integrations/shared/agentpost/SKILL.md` and rendered integration artifacts
  for the user-consent policy.

The startup gate and consumer lifecycle fixes are one release unit: truthful
re-entry without a consent gate still lets the wrong context process mail, and
a consent gate without truthful lease recovery can leave the user unable to
start the correct context.
