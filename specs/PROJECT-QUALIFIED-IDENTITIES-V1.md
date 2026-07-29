# Project-qualified identities v1

## Purpose

AgentPost profiles already record `projects`, but human-facing delivery used to
search every registered profile. A globally unique bare handle such as `nav`
could therefore resolve to a seat in an unrelated project. This contract makes
the existing project metadata an addressing namespace and reserves
`PROJECT.SEAT` for deliberate cross-project communication.

## Address grammar

- A qualified human address has exactly one dot: `PROJECT.SEAT`.
- `PROJECT` and `SEAT` use letters, digits, hyphens, or underscores.
- Canonical mailbox keys and registered project names or aliases cannot contain
  a dot. A dot in a human address is always interpreted as the qualifier
  boundary.
- The project segment matches one exact normalized entry in the profile's
  `projects` field.
- Within that project, the seat segment may exactly match a canonical mailbox
  key, display name, handle, or role. Ties fail rather than being guessed.

`agentpost identities` derives a convenient qualified address from each
addressable project alias and the profile's first simple handle, falling back to
the canonical mailbox key. For example:

```text
mailbox: projecto-n
projects: projecto
handles: nav,roadmap questions
qualified: projecto.nav
```

## Resolution rules

Human channel operations (`message`, `question`, `review`, `notify`, and
sender-bound `AgentChannel`) resolve an unqualified seat only among profiles
that share at least one project entry with the sender. Failure in that scope is
terminal: AgentPost never retries the label against the global directory.

Cross-project operations qualify the destination:

```sh
agentpost message nav 'Same-project request.'
agentpost question project-two.codereview 'Cross-project review request.'
```

The same rule applies even when the bare canonical mailbox key is globally
unique. This prevents a typo or missing local seat from silently becoming a
delivery to another project.

A projectless role or specialist has no implicit human-address scope. Add the
projects in which it is an addressable seat, place it in an explicit global
group, or use the low-level canonical-key API.

Named groups remain global deliberate fan-out objects. `@GROUP` is always the
explicit group form. A bare group name remains accepted when it does not
collide with a same-project identity.

Low-level `send` and `ask` continue to accept canonical mailbox keys for scripts
that already resolved both endpoints. The exported unscoped
`resolve_identity()` lookup also remains available for compatible programmatic
directory use; sender-bound and CLI human-address surfaces supply the
fail-closed scope.

## Directory and mailbox inspection

Project filters include offline seats:

```sh
agentpost identities --project project-two
agentpost profiles --project project-two --all
agentpost status --project project-two
```

`resolve`, `status`, `list`, `read`, and `next` accept either
`PROJECT.SEAT` or `--project PROJECT`. This makes another project's complete
seat roster inspectable without making its bare names locally addressable.

## Registration and migration

Each seat should register:

1. a stable dot-free canonical mailbox key;
2. a stable dot-free project name plus any short dot-free project aliases;
3. a short simple seat handle first, such as `nav`, `build`, or `codereview`;
4. any longer discovery handles after the address handle.

Existing dot-free profiles require no migration. A previously accepted project
entry containing a dot must be renamed before the profile can be updated.
Previously accepted cross-project bare human delivery is intentionally rejected
as a routing-safety correction; qualify the address instead.

Rollout automation must verify that the installed command exposes
`agentpost identities --project PROJECT` before registering or messaging
project seats. If it does not, upgrade AgentPost and do not fall back to global
bare-handle routing.
