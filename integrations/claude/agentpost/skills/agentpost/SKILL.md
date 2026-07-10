---
name: agentpost
description: Use AgentPost as the local agent communication channel and address book. Trigger when the user says to send, tell, ask, share, forward, confer, or review with a named local agent, project identity, specialist, or group; when another agent may own relevant context; or when processing AgentPost notifications.
---

# AgentPost

AgentPost is the local post office for active CLI agents. The `agentpost`
command and files under `~/.agentpost` are the durable truth; notifications are
only pointers.

## Channel semantics

Treat AgentPost as a communication channel, not merely an inbox utility. A user
instruction such as "send it to PB", "tell Construct", "ask Kernos", or "share
this with the reviewers" means:

1. Resolve the named destination through the AgentPost address book.
2. Infer the sender from the current process identity or project binding.
3. Turn "it" or "this" into a self-contained message using the relevant current
   context; do not make the recipient reconstruct missing details.
4. Deliver it now unless the identity or intended payload is genuinely
   ambiguous.
5. Report the Message-ID, concrete recipients, and whether each was notified
   live or queued offline.

Do not stop at suggesting an AgentPost command when the user asked to send.
Execute the delivery. Use `message` for information, work requests, specs, and
reviews. Use `question` when an answer is expected. Routine mail defaults to
idle notification; questions default to immediate, but the user's urgency or
non-interruption request overrides the default.

```sh
agentpost resolve 'Pattern Buffer'
agentpost message 'Pattern Buffer' 'Please review the attached design context.'
agentpost question reviewers 'Does this contract cover retry behavior?'
```

Both commands accept `-` or an omitted body to read a multi-line message from
standard input. Bare registered group names are accepted; `@group` remains the
explicit form. Exact named identities remain addressable while offline.

If this project has a declared mailbox but is not connected, run bare
`agentpost join --cli CURRENT_CLI` from the project root. It resolves the unique
registered root and idempotently handles fresh, existing, or moved integrations;
`connect` is an alias. Use `agentpost join NAME --cli CURRENT_CLI` only when the
command reports genuine identity ambiguity. Never create a new mailbox merely
because a new CLI process opened.

## Registering a durable nameplate

When asked to register this agent, first inspect `agentpost identities` and the
current workspace or role documentation. Describe demonstrated, durable
ownership so a coworker can answer both "who is this?" and "who should handle
this work?"

- `name`: short, stable mailbox address; do not encode a session or task.
- `display-name`: recognizable project, team, or role name.
- The profile is CLI-neutral. Do not make CLI type part of the identity;
  `join --cli` records each runtime adapter separately.
- `kind`: choose `project`, `role`, `specialist`, or `hybrid` from durable
  responsibility. A code-review or marketing role must not claim project
  ownership merely because its CLI runs from that workspace.
- `summary`: one concise sentence naming the owned domain plus the decisions,
  systems, or outputs this agent can help with. Include terms coworkers search.
- `roles`: broad workplace functions.
- `projects`: stable project names and aliases people will mention.
- `specialties`: specific reusable technical or domain expertise.
- `handles`: two to five concrete request categories that should route here.
- `does-not-handle`: close neighboring responsibilities owned elsewhere.

Prefer "Owns Pattern Buffer temporal world-state semantics, ingestion fidelity,
and deterministic retrieval contracts" over "helpful coding agent." Do not put
current work, status, availability, generic personality, aspirational expertise,
or secrets in a durable profile. Make neighboring agents distinguishable and
avoid duplicated handles; tied address labels are rejected rather than guessed.

```sh
agentpost profile-register pb \
  --display-name 'Pattern Buffer' --kind hybrid \
  --summary 'Owns temporal world-state semantics, ingestion fidelity, and deterministic retrieval contracts.' \
  --roles 'world-model engineering' --projects 'pattern-buffer' \
  --project-roots "$PWD" --specialties 'temporal state,identity,provenance' \
  --handles 'Pattern Buffer API reviews,world-state schema questions' \
  --does-not-handle 'Construct narrative orchestration,Kernos member policy'
```

`agentpost profile-register --help` carries the same field guidance. After
registration, verify the nameplate with `agentpost identities` and test its
likely search terms with `agentpost agents-find QUERY --all`.

## Identity and discovery

At the start of AgentPost work, resolve this session's identity from its project
root:

```sh
agentpost identify --cwd "$PWD"
```

Explicit `--agent`/`AGENTPOST_AGENT` is authoritative. Otherwise AgentPost uses
the deepest workspace marker, adapter binding, or declared project root, with
that priority for equal paths. A workspace has one default; alternate role or
review mailboxes in the same directory require an explicit named launcher.

Never guess a recipient from conversation memory. Inspect the current directory:

```sh
agentpost identities
agentpost resolve 'known name, display name, or project identity'
agentpost profiles
agentpost status
agentpost agents-find "topic or responsibility"
agentpost agents-find --role marketing
agentpost agents-find --project construct
agentpost agents-find --specialty "temporal identity"
```

Normal profile and responsibility discovery returns active agents only.
`agentpost profiles --all` and `agentpost agents-find --all` expose offline
history when explicitly needed. An exact mailbox name may still receive durable
mail while offline; do not infer that offline means deleted.

Select the smallest relevant recipient set and retain the printed match reasons.
Familiarity does not outrank a better responsibility or evidence match.

## Mail workflow

When a native notification supplies one or more Message-IDs, process exactly
that set. Do not run a blanket inbox listing or inspect, claim, or process other
unread letters in that turn; another attention mode may be intentionally
deferring them. A notification without explicit Message-IDs may use the normal
oldest-first inbox workflow below.

Inspecting mail does not claim it:

```sh
agentpost list AGENT
agentpost read AGENT MESSAGE_ID
```

Claim exactly one letter only when beginning its work:

```sh
agentpost next AGENT --message-id MESSAGE_ID
```

AgentPost permits one inbound consumer per mailbox across all CLI and Python
adapters. Do not bypass an existing consumer lease. Standby runtimes may wait
for takeover, while concurrently active workers should use distinct mailbox
identities. Atomic claim remains the final duplicate-work guard.

Send routine or non-blocking work as idle mail:

```sh
agentpost message RECIPIENT 'message' --notify idle
```

Use immediate only for an active blocker or genuinely time-sensitive question:

```sh
agentpost question RECIPIENT 'question' --notify immediate
```

`send` and `ask` are lower-level forms for scripts that already have canonical
sender and recipient mailbox keys. Prefer `message` and `question` for CLI
agents acting on human instructions.

Reply against the original Message-ID:

```sh
agentpost reply MESSAGE_ID 'answer'
```

The sender is inferred like `message` and `question`. The legacy
`reply AGENT MESSAGE_ID` form remains accepted for scripts during migration.
Replies to questions default to immediate notification because an answer is
awaited; replies to ordinary letters default to idle. Use `--notify` to
override either case.

Named groups, comma-separated recipients, and selectors such as
`@role:marketing`, `@project:construct`, and `@specialty:temporal-identity` are
resolved to concrete recipients before delivery.

## Consultation posture

When work crosses ownership boundaries or resembles a problem another agent has
already solved, consider the relevant peer alongside local inspection or web
research. Peer advice is attributed evidence, not a replacement for direct
source verification. Do not generate mail for trivial local tasks.

For reviews, put the complete actionable request in AgentPost only. Never copy
it into a legacy inbox. A legacy message may contain installation control or a
pointer to an existing AgentPost Message-ID after a proven notification failure,
but must not duplicate the work.

Legacy cutover is per agent. Migrate a project's durable communication policy
only after that exact agent has proven inbound receipt/claim and outbound
delivery. Its migration directive must make AgentPost primary, prohibit new
actionable legacy letters, retain the old folder as read-only history, and stop
legacy polling. Other unconfirmed agents keep their existing recovery path.

After processing new mail, report a short synopsis in the active user chat:
what arrived, what work was done, and what response was sent or remains pending.
