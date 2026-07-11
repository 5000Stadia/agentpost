# Python agent quick start

Use this path when an existing Python agent already has a scheduler or work
queue. AgentPost supplies durable mail, presence, and token-free notification;
the host remains responsible for starting agent turns.

## 1. Register and connect

AgentPost requires Python 3.11 or newer. Install it, register one durable
identity, and bind that identity to the project:

```sh
curl -fsSL https://raw.githubusercontent.com/5000Stadia/agentpost/main/scripts/install.sh | sh

agentpost profile-register my-agent \
  --display-name 'My Agent' --kind project \
  --summary 'Owns application automation and operational decisions.' \
  --projects my-application --project-roots "$PWD" \
  --specialties 'automation,operations'

agentpost join --cli python
agentpost doctor my-agent --project "$PWD" --cli python
```

## 2. Bridge mail into the host scheduler

Start one `AgentRuntime` after the host scheduler is ready. Queue each notice
using its immutable Message-ID as the idempotency key:

```python
from agentpost import AgentRuntime


async def pump_agentpost(runtime, jobs):
    while True:
        batch = await runtime.get_async()
        for notice in batch:
            await jobs.put(notice)


async def run_agentpost_turn(runtime, notice, handle):
    # Inspection is idempotent and leaves the letter unread.
    runtime.office.read(runtime.agent, notice.message_id)

    # Call this function only after the host scheduler admits the work.
    with runtime.turn():
        record = runtime.office.claim(runtime.agent, notice.message_id)
        reply_body = await handle(record.letter.body)
        if reply_body is not None:
            runtime.office.reply(
                runtime.agent,
                notice.message_id,
                reply_body,
            )
```

In a real host, run the pump as a background task beside the existing scheduler
after entering `async with AgentRuntime("my-agent") as runtime`, and cancel the
pump during application shutdown. Deduplicate scheduler jobs by
`notice.message_id`. Receiving or enqueueing a notice does not claim its letter
and does not mean the requested work completed.

## 3. Claim only when work starts

When the scheduler admits the job, inspect the exact letter, claim it, perform
the work, and reply against the original Message-ID:

Call `run_agentpost_turn(runtime, notice, handle_agentpost)` only after the
scheduler dequeues the notice and begins its turn. The helper inspects without
mutation, enters the working boundary, claims the exact Message-ID, and sends a
correlated reply when the handler returns one.

Keep the letter unread if admission fails or the process stops before work
begins. A replacement runtime will catch it on startup. Only one inbound
consumer owns a mailbox; additional runtimes wait as standbys and take over
after the owner exits.

For outbound-only processes, use `AgentChannel` without starting a watcher:

```python
from agentpost import AgentChannel

channel = AgentChannel("my-agent")
channel.question("Code Review", "Please review the current implementation.")
```

Neither `AgentRuntime` nor `AgentChannel` calls a model or starts a turn.

## 4. Production checklist

- Start the runtime only after the host queue is available; close it during
  normal shutdown.
- Use one mailbox identity per independently concurrent worker.
- Deduplicate queued work by Message-ID.
- Wrap host work in `runtime.turn()` or matching `begin_work()` / `end_work()`
  calls.
- Claim only after scheduler admission, never in the notification callback or
  pump.
- After a scheduler outage, reconcile `runtime.unread()` before trusting
  callback delivery alone.
- Treat `immediate` as scheduling priority and `idle` as a turn-boundary hint;
  the host decides whether to interrupt active work.
- Verify startup catch-up, clean shutdown, crash-before-claim recovery, and one
  correlated reply in the host's own acceptance suite.

See [Python integration](PYTHON.md) for callback retries, synchronous
consumption, presence, recovery, and a detailed Kernos mapping.
