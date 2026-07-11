# Compatibility policy

AgentPost 1.x uses Semantic Versioning. A 1.x update may add capabilities and
diagnostics, but it must preserve the stable surfaces below or provide a
documented migration and deprecation path.

## Stable in 1.x

- The documented CLI commands and option meanings in the README and installation
  guide.
- Public Python names exported through `agentpost.__all__`, including
  `PostOffice`, `AgentChannel`, and `AgentRuntime`.
- Mailbox protocol version 1, profile version 2, binding/workspace metadata,
  and forward migration of durable unread, read, sent, profile, group, and
  binding state.
- Durable-delivery semantics: notification follows commit; inspection does not
  claim; claim targets one exact Message-ID; adapter failure does not remove
  mail; replies preserve `In-Reply-To`.
- Plugin-invoked CLI entry points and their argument shapes:
  `internal-claude-boundary`, `internal-claude-monitor`,
  `internal-codex-hook`, `internal-antigravity-hook`, `internal-snapshot`, and
  `internal-notification-ack`. Installed plugin generations depend on these
  command contracts.

Security corrections may reject input that an earlier build accepted when
retaining that behavior would violate the documented trusted-local boundary or
durable mailbox integrity.

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
