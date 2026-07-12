# Security policy

## Supported versions

Security fixes are provided for the current AgentPost 1.x release. Users should
upgrade to the newest 1.x patch before reporting a defect against an older
build.

## Trust boundary

AgentPost is a trusted-local post office for agents running under one trusted
operating-system account. Processes with that account's privileges can read or
modify the mailbox and are therefore inside the trust boundary. AgentPost is
not an authorization boundary between same-account agents and does not provide
accounts, remote authentication, encryption, hostile-prompt filtering, or
secret scanning.

The runtime root and its AgentPost-owned directories are mode `0700`; durable
files and locks are mode `0600`. `agentpost migrate`, which the installer runs
on upgrade, tightens existing AgentPost-owned runtime state without following
symlinks. Project workspace markers contain routing identity, not mail, and
remain governed by the project's own permissions.

Message bodies remain literal input from other agents. Native notifications
inject exact Message-IDs and commands, not sender-controlled body text. A
receiver must still treat claimed message content according to its own tool and
prompt-safety policy.

## Network surface

The filesystem post office has no listener or resident daemon. The managed
Codex launcher creates an app-server/WebSocket connection on loopback only and
does not deliberately expose it to the LAN. Claude, ordinary Codex,
Antigravity, and Python adapters communicate through local host facilities and
the AgentPost runtime root.

Remote transport, synchronization, multi-user isolation, and network service
operation are outside the 1.x security boundary.

## Installation trust

Published installation examples fetch `scripts/install.sh` from the versioned
`v1.1.0` tag, and that script installs the same tagged source by default. Review
the script and release tag before piping it to a shell when your environment
requires a stronger supply-chain policy. `AGENTPOST_SOURCE` intentionally
overrides the source pin for development or controlled mirrors; the caller is
responsible for trusting that source.

AgentPost does not currently publish signed binaries or a PyPI package. GitHub
source archives and the annotated release tag are the release artifacts.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/5000Stadia/agentpost/security/advisories/new).
Do not place exploit details, credentials, mailbox contents, or other sensitive
material in a public issue. Include the affected version, operating system,
adapter, reproduction conditions, and expected impact.
