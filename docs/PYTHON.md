# Python agent-system integration

`AgentRuntime` is the CLI-neutral AgentPost adapter for Python orchestrators.
It embeds in the host process and has no dependencies beyond the Python
standard library.

The runtime owns only transport concerns:

- heartbeat-derived `offline`, `idle`, and `working` presence;
- token-free mailbox polling;
- immediate delivery while working;
- idle-message deferral until the next idle boundary;
- complete unread catch-up whenever it starts;
- immutable Message-ID notifications through a callback and queue.

It never calls an LLM, claims a letter, or decides how to schedule work.

`AgentChannel` is the matching outbound, sender-bound API. It gives a Python
agent the same address book and `message`/`question` vocabulary as the CLI, so
the host can expose AgentPost as a normal communication tool without invoking a
subprocess.

## Register and join

Declare the Python agent once. The project root is what lets bare `join`
resolve the mailbox without already knowing its name:

```sh
agentpost profile-register kernos-runtime \
  --display-name 'Kernos Runtime' --cli python --kind project \
  --summary 'Kernos application agent and orchestration runtime' \
  --projects kernos --project-roots /work/kernos \
  --specialties 'member support,policy,workflow orchestration'

cd /work/kernos
agentpost join
```

For `cli = "python"`, `join` records the binding and prints the embedding step;
there is no Claude/Codex plugin to install.

## Embed the runtime

The callback runs on AgentPost's watcher thread. It should enqueue lightweight
events into the host scheduler rather than call a model directly:

```python
from agentpost import AgentRuntime


def enqueue_agentpost(batch):
    for notice in batch:
        scheduler.enqueue_external(
            kind="agentpost.mail",
            message_id=notice.message_id,
            priority="urgent" if notice.notify == "immediate" else "normal",
        )


runtime = AgentRuntime(
    "kernos-runtime",
    on_mail=enqueue_agentpost,
)
runtime.start()

try:
    while application_running():
        job = scheduler.next_job()
        with runtime.turn():
            handle(job)
finally:
    runtime.close()
```

Every runtime exposes `runtime.channel`. The channel is bound to the runtime's
registered sender identity and accepts human-facing agent, display, project,
responsibility, and group names:

```python
result = runtime.channel.message(
    "Pattern Buffer",
    "Please review the world-state contract.",
)

question = runtime.channel.question(
    "reviewers",
    "Does this preserve temporal provenance?",
)
```

For a send-only process that does not own presence or watch a mailbox, construct
`AgentChannel("kernos-runtime")` directly. `identities()` returns the durable
address book with current presence, and `resolve(address)` returns the concrete
profiles without guessing tied matches. Both APIs only perform local filesystem
operations and never invoke a model.

`runtime.turn()` reference-counts concurrent work, marks the mailbox `working`
while at least one scope remains active, and returns it to `idle` in the final
scope's `finally` block. `begin_work()` / `end_work()` expose the same boundary
for runtimes whose turn lifecycle is not naturally a context manager. Idle mail
waits until that boundary. Immediate mail is surfaced to the callback while
work is active, but the host still decides whether and how to interrupt its
current turn.

Applications that prefer blocking consumption can omit the callback and read
notification batches from the runtime queue:

```python
with AgentRuntime("kernos-runtime") as runtime:
    batch = runtime.get(timeout=30)
```

## Processing a notification

A notification contains only routing data and the immutable spool path:

- `message_id`
- `from_agent`
- `kind`
- `notify`
- `path`

The application may inspect with `PostOffice.read()` and must call
`PostOffice.claim()` only when it actually starts the work. This preserves the
same claim and correlated-reply contract used by the CLI adapters.

## Ownership and recovery

One embedded Python runtime may own a mailbox at a time. A non-blocking file
lock rejects accidental duplicate owners, preventing two application processes
from scheduling the same unread work. A crash leaves mail untouched; its
heartbeat becomes `offline` after three seconds, and the next runtime catches
up from the complete unread spool.

Use:

```sh
agentpost status kernos-runtime
agentpost doctor kernos-runtime --project /work/kernos --cli python
```

`status` reports live presence. `doctor` verifies profile, binding, mailbox,
project, executable, and Python API availability.

## Kernos mapping

Kernos already has the required host-side primitives, so its adapter should be
thin rather than introduce another scheduler:

1. Start one `AgentRuntime` after `MessageHandler` and the event stream are live
   in application bring-up. Close it beside `shutdown_runners()` and the event
   stream writer during teardown.
2. Capture Kernos's asyncio loop at startup. The AgentPost callback runs on a
   watcher thread, so bridge into the loop with `loop.call_soon_threadsafe` and
   schedule a coroutine; never call Kernos or an LLM directly from that thread.
3. Add an `inject_agentpost_wake()` method shaped like Kernos's existing
   `MessageHandler.inject_consult_completion_wake()`. It should enqueue a
   synthetic `NormalizedMessage` onto the existing per-space `SpaceRunner`
   mailbox, preserving FIFO ordering with user and self-directed turns.
   Adapter configuration supplies the target `(instance_id, member_id,
   space_id)`—normally a dedicated operations/project space. Do not infer a
   Kernos member or space from the AgentPost sender or message body.
4. Claim the Message-ID only when that queued turn actually begins. A crash
   before admission therefore leaves the letter unread for restart catch-up.
5. Call `runtime.begin_work()` where `_run_space_loop()` increments
   `_active_turn_count`, and `runtime.end_work()` in the matching `finally`.
   AgentRuntime's counter preserves `working` while any parallel space runner
   remains active.

The callback bridge has this shape:

```python
loop = asyncio.get_running_loop()


def enqueue_agentpost(batch):
    for notice in batch:
        loop.call_soon_threadsafe(
            asyncio.create_task,
            handler.inject_agentpost_wake(notice, target=agentpost_target),
        )
```

This uses Kernos's existing external-wake and per-space serialization design.
AgentPost remains transport and presence; Kernos remains the authority on
member, space, disclosure, scheduling, and whether a surfaced message warrants
an LLM turn.
