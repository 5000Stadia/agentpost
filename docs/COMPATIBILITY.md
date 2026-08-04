# Compatibility policy

AgentPost 1.x uses Semantic Versioning. A 1.x update may add capabilities and
diagnostics, but it must preserve the stable surfaces below or provide a
documented migration and deprecation path.

## Stable in 1.x

- The documented CLI commands and option meanings in the README and installation
  guide.
- `attach` remains a session-local Codex identity operation. It must not mutate
  durable workspace defaults or global plugin artifacts, and boundary-only
  success must not be reported as live wake or presence.
- Public Python names exported through `agentpost.__all__`, including
  `PostOffice`, `AgentChannel`, and `AgentRuntime`.
- `Notification.origin` is additive routing metadata. Existing positional
  construction remains valid because it defaults to `live`.
- `PROJECT.SEAT` remains the explicit cross-project human address. Sender-bound
  bare identity resolution must stay inside shared registered project entries
  and must never fall back to another project's globally unique seat. Dot
  remains reserved as the single qualification boundary.
- Mailbox protocol version 1, profile version 2, binding/workspace metadata,
  and forward migration of durable unread, read, sent, profile, group, and
  binding state.
- Durable-delivery semantics: notification follows commit; inspection does not
  claim; claim targets one exact Message-ID; adapter failure does not remove
  mail; reply atomically claims an exact unread original while already-read
  originals remain replyable; replies preserve `In-Reply-To`.
- The documented `review` command and `AgentChannel.review()` fail-closed
  repository-artifact contract, including canonical commit headers, direct
  parent verification, commit-tree path assertions, and file-qualified tests.
- Plugin-invoked CLI entry points and their argument shapes:
  `internal-claude-boundary`, `internal-claude-monitor`,
  `internal-codex-hook`, `internal-antigravity-hook`, `internal-snapshot`, and
  `internal-notification-ack`. Installed plugin generations depend on these
  command contracts.

Security corrections may reject input that an earlier build accepted when
retaining that behavior would violate the documented trusted-local boundary or
durable mailbox integrity. Rejecting formerly global cross-project bare
delivery is such a routing-safety correction; canonical mailbox-key behavior
remains available through the documented low-level `send` and `ask` forms.

`agentpost wipe` is intentionally destructive rather than a compatibility
migration. Broader-than-self scopes must enumerate the current target mailboxes
and require an exact confirmation list before mutation. Wipe never expands to
source or bridge repositories.

## Not stable

- Underscored Python functions, internal modules, implementation classes not
  exported through `agentpost.__all__`, and test helpers.
- Human-readable diagnostic wording, ordering not documented as physical mail
  order, log formats, and transient files under `agents/AGENT/adapter/`.
- Claude and Codex plugin generation identifiers. They version installed
  adapter artifacts independently from the Python package and may advance in a
  compatible 1.x release.
- Undocumented host APIs used by third-party CLIs. Adapter support may degrade
  honestly when a host removes an integration surface, while durable mail must
  continue to work.

## Deprecation

A planned breaking change to a stable 1.x surface is announced in the changelog
and documentation before removal. Where practical, the old form remains
accepted with a warning for at least one subsequent minor release. A change
that cannot preserve the stable contract requires AgentPost 2.0.

## Platform scope

AgentPost 1.x supports Python 3.11-3.13 on Linux/POSIX. macOS and Windows may
work in part but are not release-accepted. Adapter capability differences are
documented in the README; an unavailable already-idle wake path is not a
failure of durable delivery.
