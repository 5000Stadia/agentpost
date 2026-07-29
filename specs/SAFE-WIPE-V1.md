# Safe wipe workflow v1

## Scope

`agentpost wipe` provides an intentional clean start for AgentPost identity
state. It never deletes a source repository, an AgentBridge repository, or
files outside AgentPost-owned mailbox metadata and workspace markers.

The scopes are:

```sh
agentpost wipe agent [NAME]
agentpost wipe project PROJECT
agentpost wipe all
```

An agent wipe removes the complete mailbox directory, including its profile,
unread/read/sent mail, adapter state, notification pointers, and consumer
ownership. It also removes the mailbox's adapter bindings, updates or removes
affected `.agentpost.toml` workspace markers, removes it from named groups, and
deletes a group if no members remain.

A project wipe applies that operation to every profile whose `projects` field
exactly matches the named project or alias. A profile that lists the project is
an affected mailbox even if it also lists other project entries.

An all-agent wipe removes every registered mailbox while retaining the
post-office root and its connection-mode configuration for a clean
re-registration.

Copies stored in an unaffected mailbox remain that mailbox's durable history.
For example, wiping a sender does not erase the recipient's received copy.

## Confirmation contract

An agent may wipe its currently resolved mailbox without an additional
confirmation flag:

```sh
agentpost wipe agent
```

This is intended as the final action of that seat. The running session must not
continue using the deleted identity.

Wiping another mailbox, a project, or all mailboxes is broader authority. The
first invocation performs no deletion and returns a deterministic line such as:

```text
confirmation required before wiping project pbe. Affected mailboxes: pbe-i,pbe-n,pbe-r. Ask the user to confirm this exact list, then rerun with `--confirm 'pbe-i,pbe-n,pbe-r'`.
```

The agent must show that list to the user and receive explicit confirmation
before rerunning the exact command. The comma-separated confirmation value must
match the current sorted mailbox set byte-for-byte. If a mailbox is added or
removed between preview and execution, the stale confirmation fails and a new
list must be confirmed.

Any held mailbox consumer lease must be stopped before its mailbox can be
wiped, including a live adapter for a nominal self-wipe. Self-wipe is exempt
from the affected-box confirmation only; after closing the adapter it can be
run from a terminal with `AGENTPOST_AGENT=NAME`. The command acquires the
authoritative consumer leases for every target and holds those fences through
mailbox detachment, so consumer startup cannot race a confirmed wipe.

Codex attachment cleanup securely opens each owner-private runtime directory
without following symlinks, validates selected files, and unlinks relative to
the held directory descriptor. A symlinked, non-owned, or permissive
attachment path fails before any mailbox mutation.

## Recovery

Successful wipe is irreversible within AgentPost. The command reports the
removed mailbox list and states that there is no AgentPost recovery. Recovery
requires an independent filesystem backup. Hidden staging is used only to keep
metadata cleanup coherent if a pre-commit filesystem operation fails.
