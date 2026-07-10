# Mailbox protocol

The default runtime root is `~/.agentpost`:

```text
config.toml
bindings/HASH.toml
agents/AGENT/profile.toml
agents/AGENT/tmp/
agents/AGENT/unread/
agents/AGENT/read/
agents/AGENT/sent/
agents/AGENT/adapter/
```

Profiles and mailbox contents are durable identity. A binding is only a default
connection from one `(CLI, project root)` to an existing profile:

```toml
version = 1
agent = "cx"
cli = "codex"
project = "/work/project"
```

Bindings are atomic and replaceable. Changing or removing one never removes a
profile or any unread, read, or sent mail.

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
`working`; no heartbeat yields `offline`.

Directory search and role/project/specialty selectors exclude offline agents by
default. Exact mailbox names and explicit named groups may target offline
agents. Delivery still commits to `unread/`; only notification is unavailable.

Human-facing channel resolution is a separate operation from active-agent
discovery. `resolve` and the `message`/`question` commands match registered
canonical names, display names, project identities, and responsibility handles;
bare named groups also expand. They include offline profiles because addressing
a known coworker is durable delivery, not availability discovery. Tied matches
are rejected instead of guessed. The sender is inferred from `AGENTPOST_AGENT`
or the deepest current project binding.

Python applications expose the same presence contract through
`AgentRuntime`. Its callback/queue receives Message-IDs only and does not alter
the `unread -> read` lifecycle.

Delivery writes and fsyncs a temporary file, atomically renames it into each
recipient's `unread/`, and writes the sender archive. Fanout uses one logical
Message-ID and one recipient copy per audience member. Per-recipient delivery
locks prevent duplicate `(recipient, Message-ID)` commits under races.

`list` and `read` have no state transition. `next` atomically renames exactly
one unread letter into `read/`. Competing claims therefore have one winner.

Replies carry `In-Reply-To`. Group panels are derived from immutable sent/read
mail rather than maintained as a mutable database row. The first terminal
answer or error from each expected responder counts; later responses remain
visible as duplicates.

Notification adapters receive only committed Message-IDs. Adapter failure does
not roll back delivery, and adapter state is never authoritative for unread
state. Adapter activation always catches up from the full current unread set.
