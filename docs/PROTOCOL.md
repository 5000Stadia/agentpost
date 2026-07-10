# Mailbox protocol

The default runtime root is `~/.agentpost`:

```text
config.toml
bindings/HASH.toml
PROJECT/.agentpost.toml
agents/AGENT/profile.toml
agents/AGENT/tmp/
agents/AGENT/unread/
agents/AGENT/read/
agents/AGENT/sent/
agents/AGENT/adapter/consumer.lock
agents/AGENT/adapter/consumer.json
```

Profiles and mailbox contents are durable identity. Profiles are CLI-neutral;
an optional `cli_hint` is only a backward-compatible first-connection hint. A
binding connects one adapter at a project root to an existing profile:

```toml
version = 1
agent = "cx"
cli = "codex"
project = "/work/project"
```

Bindings are atomic and replaceable. Changing or removing one never removes a
profile or any unread, read, or sent mail.

`join` also creates machine-local workspace identity:

```toml
version = 1
default_agent = "cx"
known_agents = ["cx", "code-reviewer"]
```

`.agentpost.toml` is excluded through `.git/info/exclude` when possible. It
survives checkout moves and supplies one unqualified default. Known alternates
are available for explicit `--agent` selection, not additional defaults.
Identity resolution uses explicit `--agent`/`AGENTPOST_AGENT` first, then the
deepest matching marker, binding, or declared project root. At equal depth a
marker outranks a legacy binding, which outranks a declared root. Ties fail
instead of guessing.

Each letter is immutable UTF-8 Markdown with RFC-822-style headers:

```text
Message-ID: <uuid@agentpost.local>
Date: 2026-07-10T03:00:00Z
From: sender
To: recipient
Audience: recipient,other-agent
Subject: Example
In-Reply-To: <optional-parent@agentpost.local>
X-Agent-Kind: letter
X-Agent-Notify: idle

Markdown body.
```

`Message-ID`, `Date`, `From`, `To`, `Audience`, `X-Agent-Kind`, and
`X-Agent-Notify` are generated and validated by AgentPost. Header injection and
path-like agent names are rejected.

## Presence and routing

Presence is transient adapter data under `agents/AGENT/adapter/`, never part of
the profile or message protocol. A fresh live heartbeat yields `idle` or
`working`; no heartbeat yields `offline`. Presence probes aggregate live
adapter markers rather than dispatching from a profile's CLI type.

One mailbox-wide `flock` on `consumer.lock` owns inbound notification and
consumption across every adapter type. `consumer.json` identifies the runtime
instance UUID, adapter, PID, cwd, and acquisition time for diagnostics. Python
runtimes and Claude monitors may wait as standbys and take over after release;
launchers that cannot attach a bridge after startup reject a second owner.
Outbound channel use does not require the inbound consumer lease.
Lifecycle-only fallback hooks acquire the lease for one hook event because
their host exposes no session-lifetime attachment point; atomic message claim
remains the final exclusion boundary on that degraded path.

Directory search and role/project/specialty selectors exclude offline agents by
default. Exact mailbox names and explicit named groups may target offline
agents. Delivery still commits to `unread/`; only notification is unavailable.

Human-facing channel resolution is a separate operation from active-agent
discovery. `resolve` and the `message`/`question` commands match registered
canonical names, display names, project identities, and responsibility handles;
bare named groups also expand. They include offline profiles because addressing
a known coworker is durable delivery, not availability discovery. Tied matches
are rejected instead of guessed. The sender is inferred from explicit process
identity or the deepest current workspace identity source.

Python applications expose the same presence contract through
`AgentRuntime`. Its callback/queue receives Message-IDs only and does not alter
the `unread -> read` lifecycle. Synchronous callback failures are retried in
order with capped backoff while the affected mail remains unread; callback
consumers must use Message-ID as their idempotency key. A successful callback
acknowledges host-queue admission only, not completion or claim of the work.
After the bounded attempt count, adapter health reports the still-unread
exhausted IDs; hosts can reconcile them through `AgentRuntime.unread()` without
adding a mailbox acknowledgment state.

A second `AgentRuntime` for the same mailbox starts in standby without
surfacing mail. When the owner exits or crashes, exactly one standby acquires
the mailbox lease and catches up from the full unread spool.

Delivery writes and fsyncs a temporary file, atomically renames it into each
recipient's `unread/`, and writes the sender archive. Fanout uses one logical
Message-ID and one recipient copy per audience member. Per-recipient delivery
locks prevent duplicate `(recipient, Message-ID)` commits under races.

`list` and `read` have no state transition. `next` atomically renames exactly
one unread letter into `read/`. Competing claims therefore have one winner even
if notification ownership is misconfigured. The lease prevents duplicate
wake/model work before claim; atomic claim is the final defense. AgentPost does
not promise exactly-once execution if a consumer crashes after claim.

Replies carry `In-Reply-To`. Group panels are derived from immutable sent/read
mail rather than maintained as a mutable database row. The first terminal
answer or error from each expected responder counts; later responses remain
visible as duplicates.

Notification adapters receive only committed Message-IDs. Adapter failure does
not roll back delivery, and adapter state is never authoritative for unread
state. Adapter activation always catches up from the full current unread set.
