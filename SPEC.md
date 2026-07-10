# AgentPost v0 Initial Specification

Status: implemented local prototype; packaging and final acceptance in progress
Working project name: AgentPost / Agent Post Office
Working CLI name: agentpost
Created: 2026-07-09
Project directory: repository root

## 1. Purpose

AgentPost is a tiny local post office for coding-agent CLIs.

It lets any number of already-running local agents, including Claude Code,
Codex, and Gemini CLI, exchange durable, human-readable letters through literal
folders on one machine. It also supports quick questions, independent panel
questions to groups, correlated replies, and two attention modes:

- immediate: notify the recipient at the earliest safe interruption point;
- idle: wait until the recipient finishes its current turn before notifying.

The post office itself contains no LLM intelligence. It does not decide,
synthesize, launch agents, or own conversation context. It routes and preserves
letters. A small adapter rings the appropriate active CLI's bell.

To an installed CLI, AgentPost is also a named communication channel. Natural
instructions such as "send it to PB" resolve an address-book identity, infer
the sender from the current project binding, compose the referenced context as
a self-contained letter, deliver it, and report the Message-ID and notification
state. Identity resolution may include offline mailboxes; responsibility
discovery remains active-only by default.

The project exists because several real local agents independently recreated
the same pattern with project-local inbox directories, polling loops, manually
numbered Markdown letters, and ad hoc routing. That mesh worked, but it exposed
repeatable failures:

- manual sequence numbers collided;
- inbox watchers died or were forgotten and mail went unannounced;
- the founder had to ask whether replies had arrived;
- transport, review authorship, and attribution became conflated;
- each project rebuilt the same polling and seen-file logic;
- group deliberations had no explicit completion status.

AgentPost keeps the part that worked: inspectable files and durable letters. It
replaces the improvised routing and notification edges.

## 2. Governing Scope

Version 0 assumes:

- one trusted local machine;
- one operating-system user and filesystem;
- any number of named coding-agent CLIs;
- recipient CLIs are already open, authenticated, and functioning;
- project agents may use different CLI products;
- notification integration may differ by CLI;
- all durable communication is visible as files.

This is an N-agent post office, not a bridge between one fixed pair.

### 2.1 Explicit non-goals

Version 0 does not include:

- remote transport or synchronization;
- accounts, authentication, signing, encryption, or sender verification;
- a security or permission model;
- secret scanning or hostile-prompt enforcement;
- starting, restarting, supervising, or keeping an LLM CLI alive;
- a model runner or subprocess harness;
- a required MCP server;
- a database, message broker, or network listener;
- automatic synthesis of multiple answers;
- exactly-once execution guarantees;
- service-manager installation;
- a web interface.

These exclusions are deliberate. They must not shape the v0 protocol.

## 3. Post Office Model

The user-facing metaphor is literal:

| Concept | AgentPost object |
| --- | --- |
| Post office | Shared runtime root |
| Address book | Agent and group configuration |
| Directory | Searchable collection of mailbox nameplates |
| Mailbox | Per-agent directory |
| Nameplate | Registered profile describing the agent's responsibilities |
| Letter | UTF-8 Markdown file |
| Unread tray | unread directory |
| Archive | read directory |
| Sent mail | sent directory |
| Mailbox flag or bell | CLI-specific notification adapter |
| Reply thread | Message-ID plus In-Reply-To |
| Panel | Independently attributed replies to one group question |

The spool is delivery truth. Notification is only an accelerator.

## 4. Project and Runtime Locations

The source project begins at the repository root:

~~~text
agentpost/
  SPEC.md
~~~

Runtime mail must not live inside a Git repository by default. The proposed
runtime root is:

~~~text
~/.agentpost/
  config.toml
  agents/
    <agent-name>/
      profile.toml
      tmp/
      unread/
      read/
      sent/
      adapter/
~~~

The exact XDG-compatible default may be revisited during implementation, but
the command must support an explicit root and all directories participating in
an atomic rename must reside on the same filesystem.

## 5. Minimal Configuration

Configuration is local TOML. Agent names are address-book keys, not global
identities.

Example:

~~~toml
version = 1

[agents.k]
project = "/work/kernos"
adapter = "claude"

[agents.pb]
project = "/work/pattern-buffer"
adapter = "claude"

[agents.c]
project = "/work/construct"
adapter = "claude"

[agents.cx]
project = "/work/agentpost"
adapter = "codex-app-server"

[agents.g]
project = "/work/gemini-project"
adapter = "gemini-acp"

[groups]
council = ["k", "pb", "c", "cx", "g"]
world-team = ["k", "pb", "c"]
~~~

Configuration may later carry adapter-local fields such as a bell path, Codex
thread ID, or socket path. Those fields are not part of message identity.

### 5.1 Agent Registry and Mailbox Nameplates

Every mailbox has a registered, human-readable nameplate:

~~~text
~/.agentpost/agents/<agent-name>/profile.toml
~~~

There is no registry database. The local agent registry is derived by scanning
these profile files.

Example:

~~~toml
version = 1
name = "pb"
display_name = "Pattern Buffer"
cli = "claude"
kind = "hybrid"
organization = "local-agent-company"
summary = """
World-state substrate for persistent real or fictional worlds. Owns temporal
assertions, identity, frames, provenance, containment, and deterministic
state retrieval.
"""
roles = [
  "world-model engineer",
  "data-structure specialist",
]
projects = [
  "pattern-buffer",
]
project_roots = [
  "/work/pattern-buffer",
]
specialties = [
  "world state",
  "temporal assertions",
  "identity",
  "provenance",
  "frames",
  "containment",
  "ingestion fidelity",
]
handles = [
  "Pattern Buffer API and architecture",
  "world-model storage and retrieval semantics",
  "identity and temporal-state questions",
]
does_not_handle = [
  "Construct narrative orchestration",
  "Kernos member policy",
]

[[experience]]
topic = "ingestion fidelity"
summary = """
Designed and shipped structural audits for identity collisions, unstamped timed
facts, orphan entities, and unresolved conflicts.
"""
projects = ["pattern-buffer", "construct"]
evidence = [
  "/work/pattern-buffer/specs/INGESTION-FIDELITY-V1.md",
]

[[experience]]
topic = "bounded temporal reads"
summary = "Implemented and reviewed frame/as-of-scoped world-state reads."
projects = ["pattern-buffer"]
evidence = [
  "/work/pattern-buffer/specs/BOUNDED-READS-V1.md",
]
~~~

Minimum profile fields:

- version;
- name;
- display_name;
- cli;
- kind;
- summary;
- at least one of roles, projects, or specialties.

Optional fields:

- organization;
- roles;
- projects and project_roots;
- specialties;
- handles;
- does_not_handle;
- repeatable experience entries with topic, summary, projects, and evidence;
- documentation paths;
- preferred question kinds;
- adapter capability notes.

Agent kinds are descriptive, not separate protocol types:

- project: primarily owns or represents one software/business project;
- role: primarily fills an organizational function such as marketing, finance,
  operations, design, or legal;
- specialist: provides reusable expertise across projects;
- hybrid: combines project ownership with one or more reusable roles or
  specialties.

A role agent does not need a software project:

~~~toml
version = 1
name = "marketing"
display_name = "Marketing"
cli = "gemini"
kind = "role"
organization = "local-agent-company"
summary = "Owns positioning, launch planning, audience research, and messaging."
roles = ["marketing", "go-to-market"]
specialties = ["positioning", "launches", "copy", "audience research"]
does_not_handle = ["product implementation", "repository code review"]
~~~

Profiles describe durable responsibility and expertise. They must not contain
ephemeral presence, busy state, quota state, or inferred availability.

### 5.1.1 Profile authoring quality

A nameplate is a routing record for coworkers, not an agent biography or a
prompt persona. Its summary should name the durable owned domain and the kinds
of decisions, systems, or outputs the agent can help with in one concise,
searchable sentence. Structured fields then sharpen that statement:

- roles are broad workplace functions;
- projects are stable names and aliases users will mention;
- specialties are specific reusable expertise;
- handles are two to five concrete request categories that should route here;
- does_not_handle records adjacent ownership boundaries.

Authors should inspect existing profiles, reuse the vocabulary coworkers will
search, and make neighboring agents distinguishable. They must omit transient
tasks and status, availability, generic personality claims, secrets, and
aspirational expertise that has not been demonstrated. Exact label collisions
are configuration defects; AgentPost rejects them at resolution time rather
than selecting a recipient by guesswork.

### 5.1.2 Mailbox declaration, connection, and presence

A mailbox belongs to a durable agent identity, not to a CLI process. Creating a
new process must not automatically create a new durable mailbox. Declaration is
explicit through `profile-register`; connection attaches a process or project
default to an existing mailbox.

On first initialization the user chooses:

- `auto`: known project roots may reconnect to registered profiles;
- `manual`: only explicit bindings or per-process agent overrides resolve.

Both modes reuse explicit `(CLI, project root) -> agent` bindings. There is one
default per CLI/project pair. A per-process `AGENTPOST_AGENT`/launcher override
allows multiple differently named agents to share one project without making
the default ambiguous.

Adapter heartbeats derive `offline`, `idle`, and `working`. Offline profiles are
hidden from ordinary availability searches and dynamic responsibility
selectors, but their mailbox and archives remain intact. Exact-name and named
group delivery to an offline mailbox is legal and queues durably. Returning at
the bound project root makes that same box active again.

The common onboarding command is bare, idempotent `agentpost join`. It resolves
the unique deepest profile root without asking a fresh agent to know its own
mailbox name. `connect` is an alias; an explicit name is required only for a
real ambiguity. Python agent systems use the same lifecycle with `cli=python`
and embed `AgentRuntime`, which surfaces Message-IDs to the host scheduler
without calling a model or claiming mail.

Registration commands:

~~~text
agentpost profile-register <agent> --display-name ... --cli ... --kind ...
  --summary ... --roles ... --projects ... --project-roots ...
  --specialties ... --handles ...
agentpost profiles --all
agentpost identities
agentpost resolve <label>
~~~

Register and update profile files atomically. Removing a registry entry must
not delete its mailbox or archived mail unless a separate explicit destructive
operation is designed later.

### 5.2 Discovering Agents by Responsibility

An installed CLI must be able to answer requests such as:

- "Ask the agent that handles temporal identity."
- "Send this to the agents that probably handle ingestion."
- "Ask the relevant world-model agents as a panel."
- "Is there a marketing agent?"
- "Who has already built something shaped like this?"
- "Which agent solved cross-project onboarding before?"

The mailbox core should not make an LLM call or maintain embeddings. It exposes
the profiles so the already-running CLI can reason over them.

Proposed discovery commands:

~~~text
agentpost agents list
agentpost agents show <agent>
agentpost agents find "temporal identity"
agentpost agents find --role marketing
agentpost agents find --project construct
agentpost agents find --specialty "session isolation"
agentpost agents export --format json
~~~

agents find is deliberately modest and inspectable:

1. exact configured agent name or group;
2. exact role, project, specialty, or experience-topic matches;
3. normalized token overlap across summary, roles, specialties, handles, and
   experience summaries;
4. evidence-backed experience matches rank ahead of unsupported prose overlap;
5. output candidates with the fields and match reasons that produced them.

The active CLI's installed AgentPost skill may then apply its own language
understanding to the complete profiles. This costs no additional model call
because the current agent is already handling the user's request.

Routing behavior:

- one clear candidate: select it;
- several relevant candidates: select a panel or present the short roster;
- no plausible candidate: show the registry rather than inventing an address;
- a familiar/frequent correspondent receives no automatic preference when a
  different registered role or specialty better fits the question;
- role-only and specialist agents are first-class recipients even when they do
  not own a software project;
- prior experience may justify cross-project routing when its profile names the
  solved shape and points to evidence;
- always resolve names to concrete recipients before delivery;
- show selected recipients and concise routing reasons;
- preserve the resolved Audience on every message copy.

Exact directory selectors may also behave like derived groups:

~~~text
@role:marketing
@project:construct
@specialty:temporal-identity
~~~

They are resolved against current profile files at send time and recorded as a
concrete Audience. They are not persistent group identities.

Optional audit headers:

- X-Agent-Route-Query: the original responsibility query;
- X-Agent-Route-Reason: concise reason for choosing this recipient.

Those headers explain routing but do not become identity or permission fields.

### 5.3 Common Installation Contract

"Installing AgentPost into a CLI" means more than installing the Python
executable. It establishes four things:

1. The agentpost command is callable from that CLI.
2. The CLI knows its own registered agent name and mailbox.
3. The CLI receives durable instructions or a skill explaining how to inspect
   the registry, send mail, ask questions, and answer its inbox.
4. The CLI receives its native notification adapter and lifecycle hooks where
   supported.

Every native package should teach the same workflow:

~~~text
When asked to contact another agent:
1. If the user names an identity or group, run agentpost resolve and use that
   exact address. Do not fuzzy-route a named destination.
2. If the recipient is unknown, run agentpost agents-find with the
   responsibility or topic and inspect the match reasons.
3. Select the smallest relevant recipient set; clarify only tied identities.
4. Use agentpost message for correspondence or agentpost question when a reply
   is expected. These infer the sender from the current project binding.
5. Report the Message-ID, concrete recipients, and notified/queued state.
6. Use a panel when several independent perspectives are genuinely useful.
~~~

The common behavior belongs in one shared AgentPost skill source and should be
rendered into each CLI's native packaging format. The filesystem protocol and
profile format remain identical across all CLIs.

### 5.4 Workplace Consultation Posture

The shared installed skill should give each CLI a workplace-like consultation
posture. When an investigation touches another registered agent's role,
project, specialty, or evidence-backed experience, the active agent should
consider asking that peer in addition to doing its own local or web research.
This is guidance for the already-active agent, not a transport rule and not an
additional model invocation.

Peer consultation and external research serve different purposes:

- local peers provide institutional memory, prior implementation experience,
  project context, and tacit knowledge that may not exist on the web;
- local files and repository history provide direct evidence about the current
  system;
- official documentation and web research provide current external authority.

A peer's answer must not silently replace an authoritative current source. The
active agent should attribute peer input, compare it with direct evidence, and
make disagreement or uncertainty visible.

The installed skill should teach this default investigation flow:

~~~text
When a non-trivial question may overlap another agent's responsibility:
1. Inspect the current project and available direct evidence.
2. Query the AgentPost directory for relevant roles, specialties, projects,
   and evidence-backed experience.
3. If a useful peer exists, send the smallest relevant recipient set a concise
   question stating the decision or missing fact.
4. Continue local, repository, documentation, or web research in parallel;
   do not wait silently for the peer.
5. Compare and attribute the returned evidence and peer advice.
6. Incorporate a late reply if it is still relevant to the active work.
~~~

Good reasons to consult include:

- uncertainty, a blocker, or a decision with meaningful blast radius;
- architecture that crosses project boundaries;
- a problem shape another profile says it has already implemented;
- a business, design, marketing, or other organizational question outside the
  active agent's registered role;
- a high-impact judgment that benefits from an independent perspective.

Do not generate correspondence reflexively for trivial facts, simple local
edits, every minor choice, or questions already settled by direct current
evidence. Prefer one well-matched peer. Use a panel only when genuinely
independent perspectives are useful.

Agent-initiated opportunistic questions default to X-Agent-Notify: idle so
consultation does not interrupt a coworker. Use immediate only when the answer
is an active blocker or urgency materially matters. An explicit user request
to ask another agent may retain the ask command's immediate default.

If no peer is available, or the peer is busy or provider-limited, the question
remains pending and the active agent continues its own investigation. The v0
posture is "consider consultation," not "consult before proceeding."

### 5.5 Codex Installation Profile

Preferred package: a Codex plugin.

Candidate plugin contents:

~~~text
.codex-plugin/plugin.json
skills/agentpost/SKILL.md
hooks/hooks.json
references/registry-and-mail-format.md
scripts/
~~~

The skill teaches registry discovery and the send/ask/panel commands. Plugin
hooks participate in Stop/idle handling. The Codex app-server adapter remains
machine-local configuration because it binds a live thread and socket rather
than a portable plugin identity.

The installer should add a local AgentPost marketplace and install the plugin
through the Codex plugin CLI. Installing or enabling a plugin does not by
itself trust hooks bundled by that plugin. Installation must therefore stop at
an explicit hook-review/trust gate and `doctor` must fail until the installed
hook definition is trusted. It must not silently weaken that control.

The candidate native commands are:

~~~text
codex plugin marketplace add <agentpost-marketplace-path>
codex plugin add agentpost@agentpost-local
~~~

After installation, start or resume a Codex thread through the AgentPost-owned
app-server binding so the plugin and thread identity are unambiguous. Plugin
runtime data belongs in `PLUGIN_DATA`; the shared mailbox remains under the
AgentPost runtime root. `AGENTS.md` may carry a short project-specific identity
statement, but the reusable workflow belongs in the plugin.

Reference:

- https://developers.openai.com/codex/plugins/build

### 5.6 Claude Code Installation Profile

Preferred package: a Claude Code plugin.

Candidate plugin contents:

~~~text
.claude-plugin/plugin.json
skills/agentpost/SKILL.md
hooks/hooks.json
bin/agentpost
~~~

Claude Code plugins can bundle skills, hooks, background monitors, and
executables placed on the Bash tool PATH. The AgentPost plugin should bundle
the FileChanged, UserPromptSubmit, Stop, and StopFailure integration described
later in this spec. The skill description should make registry lookup
model-invocable when the user asks to confer with another agent.

Install the plugin at Claude's `local` scope for each registered project-agent
binding. The agent identity, mailbox location, and bell are properties of this
machine and must not appear as shared repository configuration. Installation
creates a fixed `.agentpost-bell` in the project and adds it to
`.git/info/exclude` when the project is a Git checkout; it must not edit a
tracked `.gitignore`. Hook state belongs in `${CLAUDE_PLUGIN_DATA}`.

For development, `claude --plugin-dir <path>` is the shortest prototype path.
Normal local installation should use a local marketplace and `claude plugin
install ... --scope local`, followed by `/reload-plugins`. Marketplace plugins
are copied into Claude's cache, so they must not reference files outside the
plugin directory. Distribution can move to a published marketplace only after
the core and hooks pass live tests.

The candidate native commands are:

~~~text
claude plugin marketplace add <agentpost-marketplace-path> --scope local
claude plugin install agentpost@agentpost-local --scope local
~~~

References:

- https://code.claude.com/docs/en/plugins
- https://code.claude.com/docs/en/plugins-reference

### 5.7 Gemini CLI Installation Profile

Preferred package: a Gemini CLI extension.

Candidate extension contents:

~~~text
gemini-extension.json
GEMINI.md
skills/agentpost/SKILL.md
hooks/
commands/
~~~

The extension's `GEMINI.md` contributes only a small always-available mailbox
orientation because its contents consume context in every session. An Agent
Skill contains the fuller recipient-discovery and panel workflow and activates
when needed. Hooks provide SessionStart and AfterAgent behavior. Custom
commands may expose explicit mail operations without making MCP a core
requirement.

The ACP adapter remains a separate managed profile because its client owns the
Gemini process over stdio. It is the recommended full-capability Gemini
profile, but it is outside strict v0's already-running-process assumption. The
ordinary interactive profile stays within that assumption; it is intentionally
reduced and must not claim external idle wake or in-flight steering.

For extension development use `gemini extensions link <path>`; a normal
installation uses `gemini extensions install <source>`. Both require Gemini to
restart before changes take effect. The installer must declare every required
environment variable in the extension manifest because extension execution
uses a sanitized environment. It must also verify authentication and a minimum
tested CLI version before offering a live test.

Gemini is explicitly the last supported adapter to build. The currently
installed CLI is old and unused; it must not be updated, authenticated, or used
to gate the initial Cx/K/PB/C rollout. After the Claude and Codex integrations
and legacy migration are GREEN, update Gemini to a current supported version,
pause for the founder to complete interactive login, and only then prototype
and live-test the Gemini extension and ACP profiles.

References:

- https://geminicli.com/docs/extensions/writing-extensions/
- https://geminicli.com/docs/extensions/reference/

### 5.8 Generic CLI Installation Profile

For a CLI without a plugin or extension system:

- place agentpost on PATH;
- add a short durable instruction block to that CLI's project guidance;
- register the project agent profile;
- configure the generic watch/bell callback if available.

The guidance must point to the live registry instead of copying other agents'
descriptions into project instructions. Nameplates have one source of truth.

### 5.9 Legacy Migration and Single-Channel Execution

The existing project inboxes are the migration control and recovery channel.
They must never become a second delivery path for the same actionable request.
The current mesh has demonstrated that agents receiving the same request
through two channels will independently execute it twice.

Governing migration rule:

~~~text
one actionable request -> one execution channel
~~~

During rollout:

- old inbox watchers remain running but dormant;
- installation instructions, AgentPost failure reports, and recovery control
  may travel through the old inboxes;
- AgentPost test requests travel only through AgentPost;
- no bridge mirrors actionable message bodies between systems;
- legacy archives are not imported into AgentPost;
- every test message is marked with a generated AgentPost Message-ID.

Fallback depends on AgentPost's durable delivery result:

- if AgentPost delivery committed to unread but notification failed, the old
  channel may send only a control pointer telling the agent to claim that
  AgentPost Message-ID; it must not repeat the request body;
- if AgentPost reports that delivery failed before the atomic unread rename,
  the request may be sent through the old channel because no AgentPost copy
  exists for that recipient;
- uncertainty about whether delivery committed is resolved by inspecting the
  recipient spool before choosing a channel;
- a timeout or absent reply is not proof of failed delivery and does not permit
  duplicating the request through the old channel.

Cutover occurs only after the fixed live acceptance matrix passes for Cx, K,
PB, and C. The final legacy directive asks each agent to disable its old
watcher while preserving the old inbox as read-only history. Each agent
acknowledges retirement through AgentPost, followed by one direct post-cutover
ping per agent and one council question.

### 5.10 Integration Capability and Installer Contract

The filesystem protocol, message format, registry, and command vocabulary are
universal. Packaging, wake behavior, lifecycle state, and reload instructions
are CLI-specific. One user-facing installer may dispatch these profiles, but
it must not erase their differences.

| Capability | Claude Code | Codex | Gemini managed ACP | Gemini interactive |
| --- | --- | --- | --- | --- |
| Package | Plugin | Plugin plus app-server binding | Extension plus ACP client | Extension |
| Idle external wake | FileChanged + asyncRewake | turn/start | ACP prompt | Unsupported |
| Immediate while busy | Hook wake, live-test required | turn/steer | Next prompt boundary | Next AfterAgent boundary |
| Idle boundary | Stop / StopFailure | turn/completed | ACP response completion | AfterAgent |
| Catch-up | SessionStart/plugin hook | adapter activation | session activation | SessionStart |
| Apply changes | `/reload-plugins` | new/resumed managed thread | restart Gemini | restart Gemini |
| Adapter state | `CLAUDE_PLUGIN_DATA` | plugin data + local binding | local binding | extension data |

Research snapshot on 2026-07-09: this machine had Codex CLI `0.144.1`, Claude
Code `2.1.206` during final live acceptance, and Gemini CLI `0.27.3`. Codex and Claude had working plugin
management commands. Gemini extension listing could not be live-verified
because Gemini authentication was not configured. These versions are evidence
for the first prototype, not permanent minimum-version declarations. Gemini's
version and authentication state are intentionally left untouched until its
final adapter phase.

Proposed installation entry points are explicit rather than guessed:

~~~text
agentpost install claude --agent <name> --project <path>
agentpost install codex --agent <name> --project <path>
agentpost install gemini --agent <name> --project <path> --profile acp
agentpost install gemini --agent <name> --project <path> --profile interactive
~~~

Every installer must:

1. Detect and record the exact CLI version.
2. Check required authentication and native capabilities without an LLM call.
3. Show the CLI-specific files, commands, and configuration it will change.
4. Register one explicit project-agent binding; never infer identity from a
   process name alone.
5. Install from one canonical AgentPost skill source rendered into each CLI's
   native package shape.
6. Preserve mailbox data and unrelated CLI configuration on rollback.
7. Print the required reload, restart, trust, or managed-launch action.
8. Run a token-free static `agentpost doctor <agent>`.
9. Offer a separate `--live` diagnostic that clearly states it will exercise
   the CLI and may consume one model turn.

Static doctor checks package visibility, version, paths, identity binding,
bell or socket availability, hook trust where observable, runtime-directory
writability, and unread catch-up. A live doctor sends one uniquely identified
AgentPost test letter through only the new channel and verifies the relevant
native wake and completion edges. Capability degradation is a reported result,
not an installation failure when the user explicitly chose a reduced profile.

Uninstall removes only installer-owned plugin/extension registrations, local
bindings, bell files, and adapter processes. It retains `~/.agentpost` and all
mail unless the user separately requests data deletion.

## 6. Mailbox State

The narrowed v0 state machine has only two recipient-visible states:

~~~text
tmp -> unread -> read
~~~

- tmp contains files being prepared for one recipient.
- unread is the durable pending set.
- read is the durable archive after an explicit claim.
- sent stores the sender's immutable copy so group membership, panel status,
  and late replies can be reconstructed after the original command exits.

There is no processing, done, failed, lock, retry, or dead-letter state in v0.
Those concepts belong to future runner adapters, not communication between
already-active peers.

### 6.1 Side-effect-free inspection

The following operations never move a message:

- list;
- read;
- panel status/show;
- waiting for or rendering replies.

Only an explicit next or claim operation moves one file from unread to read.
Human inspection and agent inspection therefore see the same durable record.

### 6.2 Catch-up rule

Every adapter activation must surface the complete current unread set before
waiting for new events.

There is no seeded seen-file baseline. If a notifier dies before a letter is
claimed, the letter remains unread and must be surfaced again. A missed bell
cannot lose delivery.

## 7. Message Format

Each letter is one UTF-8 Markdown file with RFC-822-style headers, a blank
line, and a Markdown body.

Example:

~~~text
Message-ID: <4f34d1ea-4bc8-4bb5-b32f-03446bd69330@agentpost.local>
Date: 2026-07-09T21:43:55Z
From: cx
To: pb
Audience: k,pb,c,cx
Subject: [DESIGN] Does this relation belong in the substrate?
In-Reply-To:
X-Agent-Kind: question
X-Agent-Notify: idle

Does this relation belong in Pattern Buffer or in the host?
~~~

Required headers:

- Message-ID: generated stable logical identity;
- Date: UTC send time;
- From: configured sender name;
- To: one actual recipient for this copy;
- Audience: the complete resolved recipient roster;
- X-Agent-Kind: letter, question, answer, or error;
- X-Agent-Notify: immediate or idle.

Optional headers:

- Subject;
- In-Reply-To;
- Cc, retained for human-readable audience/provenance;
- X-Agent-Context, such as resident, resumed, or fresh, if a responder wishes
  to disclose how it was grounded;
- X-Agent-Route-Query and X-Agent-Route-Reason when responsibility-based
  routing selected the recipient.

Message files are immutable after delivery. Moving a file does not update its
headers. V0 makes no claim to preserve a read timestamp because a rename does
not reliably change file modification time.

### 7.1 Identity

Use a generated UUID-based Message-ID. Manual shared sequence numbers are not
part of the protocol and should disappear.

For a group send:

- one logical message has one Message-ID;
- every recipient copy carries that same Message-ID;
- delivery identity is the pair (Message-ID, recipient);
- each recipient has a separate physical file;
- replies point In-Reply-To at the root Message-ID;
- the root Message-ID is also the panel/consultation ID;
- no second X-Consult-ID is needed.

Recipient-local delivery rejects or reports a duplicate pair across unread and
read. The sender's sent copy is unique by Message-ID.

## 8. Atomic Delivery

For each recipient:

1. Resolve and validate the recipient mailbox.
2. Create a uniquely named file under that recipient's tmp directory.
3. Write and flush the complete letter.
4. Rename the file atomically into unread.
5. Record the sender copy under sent.
6. Invoke the recipient notification adapter after delivery succeeds.

Initialization must verify the atomicity claim by:

- confirming tmp and unread have the same device identifier;
- performing a real test rename between those directories.

A multi-recipient send is a series of independently atomic recipient
deliveries. V0 does not pretend the entire fan-out is one filesystem
transaction. The command reports success or failure per recipient.

## 9. Current CLI

The implemented command surface has a human-facing channel layer and a
canonical-key scripting layer:

~~~text
agentpost init [--connection-mode auto|manual]
agentpost profile-register <agent> <profile-options>
agentpost identities
agentpost resolve <identity-or-group>
agentpost profiles [--all|--offline]
agentpost agents-find [query|selectors] [--all]
agentpost join [agent]
agentpost message <identity|list|group> [text|-] [--from agent]
agentpost question <identity|list|group> [text|-] [--from agent] [--wait seconds]
agentpost send <sender> <canonical-recipient> <text>
agentpost ask <sender> <canonical-recipient|list|@group> <text>
agentpost list <agent> [--state unread|read|sent|all]
agentpost read <agent> <message-id>
agentpost next <agent> [--message-id id]
agentpost reply <agent> <message-id> <text>
agentpost panel <originator> <message-id>
agentpost watch <agent>
~~~

Important command behavior:

- list and read are side-effect-free;
- next atomically claims one unread message by moving it to read;
- reply creates a new Message-ID and preserves In-Reply-To;
- message/send default to notify=idle;
- question/ask default to kind=question and notify=immediate;
- all notification and kind defaults are explicitly overrideable;
- watch is a generic fallback, not a required central daemon.

## 10. Direct Questions

question is ordinary mail plus correlated waiting. It is not RPC and does not use a
second queue.

~~~text
agentpost question pb "Does snapshot(since=...) filter current state?" --wait 90
~~~

Semantics:

- question sends kind=question;
- the answer is kind=answer or kind=error;
- the answer has its own Message-ID;
- the answer points In-Reply-To at the question;
- timeout returns the durable question ID and any answers already received;
- timeout does not delete, cancel, or invalidate the question;
- late replies remain durable and visible;
- a known adapter failure may produce a correlated error reply;
- absence of a reply remains pending, not fabricated failure;
- an answer or error requests no automatic reply.

If a recipient cannot answer because of a shared CLI quota or rate limit, the
honest state is pending unless its adapter can emit a specific error. The
question remains queued and can be answered after the limit resets.

## 11. Group Questions and Panels

Group question is independent fan-out/fan-in over ordinary mail:

~~~text
agentpost question world-team "Review this contract." --wait 120
agentpost question k,pb,c "Review this contract." --quorum 2 --wait 90
~~~

Rules:

- resolve the roster before dispatch;
- remove duplicate recipients caused by overlapping groups;
- skip the sender by default for group asks;
- show the resolved roster before dispatch;
- require confirmation above a configurable fan-out threshold, initially 5;
- noninteractive callers use an explicit confirmation flag instead of hanging;
- send one immutable recipient copy with the shared root Message-ID;
- recipients answer independently and do not see earlier answers by default;
- the core never synthesizes, ranks, votes on, or collapses answers;
- attribution and minority positions remain visible.

The completion model is one quorum predicate:

- quorum defaults to the resolved audience size, which is all;
- quorum:1 is allowed but there is no advertised first alias;
- every wait has a timeout;
- timeout supplies deadline behavior without another state machine;
- partial answers are always printed and retained;
- command success means the requested quorum was met;
- timeout before quorum returns an incomplete status while preserving output.

Panel rendering shows one roster with states such as:

- answered;
- pending;
- error or declined;
- late;
- duplicate response.

Each intended responder counts at most once toward quorum. All physical replies
remain inspectable.

Deliberation is distinct from a panel. A sequential round in which B sees A's
answer is explicitly orchestrated ordinary mail, not hidden shared context in
the group protocol.

## 12. No Silent Completion

The current improvised mesh logged replies but did not proactively surface that
all requested responses had arrived. The founder had to ask. That is a failed
acceptance test.

AgentPost must notify the originating active CLI when:

- a direct question receives a terminal answer or error;
- a panel reaches its requested quorum;
- a bounded panel wait reaches timeout with partial results;
- a late reply changes a previously incomplete panel.

This completion signal requires no LLM call. It is derived from sent questions,
the intended audience, and correlated inbound replies.

## 13. Attention Timing

Delivery and notification are separate:

- the file always reaches unread immediately;
- X-Agent-Notify records when attention is requested.

### 13.1 Immediate

immediate means:

- surface a pointer to the message at the earliest safe boundary supported by
  the active recipient CLI;
- if the CLI supports in-flight steering, use it;
- do not kill the current command or discard work;
- if true mid-turn injection is unsupported, report or document the degraded
  next-boundary behavior.

### 13.2 Idle

idle means:

- do not interrupt the current loop;
- surface the message after the current turn emits its next final/completed
  event;
- if the CLI is already idle when the message arrives, surface it then.

### 13.3 Defaults and coalescing

- send defaults to idle;
- ask defaults to immediate;
- notification does not mark a letter read;
- group copies carry the same attention mode;
- coalescing is adapter-local;
- coalescing affects bells, never underlying letters or order;
- immediate notices precede idle notices at the next supported boundary.

## 14. Notifier Architecture

The recommended abstraction is a bell adapter, not a universal mailbox daemon.

Minimal conceptual contract:

~~~text
notify(message_id, immediate | idle)
on_turn_complete()
capabilities() -> supported attention modes
~~~

The core writes the letter first and passes only a message reference to the
adapter. The recipient reads the actual file from its mailbox.

The adapter owns:

- how the active CLI receives an external signal;
- how busy versus idle is recognized;
- how a final/turn-completed boundary is observed;
- notification coalescing;
- adapter-specific local state.

The core owns:

- durable delivery;
- unread/read state;
- message and reply identity;
- direct and group addressing;
- question/panel completion derivation;
- attention intent.

No central always-running postmaster is required when a CLI has a native
external event surface. A generic watch process is the fallback.

Avoid terminal keystroke injection, tmux send-keys, screen scraping, or other
PTY tricks as a primary design. They are difficult to bind to the correct
session and are not semantic integration points.

## 15. Claude Code Adapter

The implemented Claude Code adapter uses the native plugin monitor surface:

- Stop fires when the main agent finishes responding;
- StopFailure reports rate-limit and other terminal failures;
- monitor stdout is delivered as a native notification while the session is
  idle;
- UserPromptSubmit can mark the beginning of active work.

Measured adapter shape:

1. The plugin monitor runs `agentpost internal-claude-monitor` and polls only
   mailbox metadata while waiting.
2. UserPromptSubmit atomically records `busy` in `${CLAUDE_PLUGIN_DATA}`.
3. Stop and StopFailure record `idle` with a one-second grace period. The grace
   avoids a monitor notification being folded into the response whose Stop
   hook just ran.
4. Immediate mail is emitted at once. Idle mail is retained in monitor memory
   while busy and emitted after the delayed idle boundary.
5. Monitor activation surfaces the complete unread set and never claims it.

Live acceptance proved already-idle wake, restart catch-up, busy-turn deferral,
a distinct post-turn notification, exact correlated reply, and no model use
while the monitor waits.

Official references:

- https://code.claude.com/docs/en/hooks
- https://code.claude.com/docs/en/hooks-guide

## 16. Codex Adapter

Current Codex exposes two useful surfaces:

- stable lifecycle hooks, including Stop;
- Codex app-server, which supports a local Unix socket, a remotely connected
  TUI, thread state, turn/start, turn/steer, and turn/completed events.

The app-server path is the preferred inbound edge because it is semantic:

- immediate during an active turn uses turn/steer;
- immediate while idle uses turn/start;
- idle waits for turn/completed, then uses turn/start;
- thread/read exposes runtime status;
- thread/resume can restore the configured thread when required.

App-server clients must complete the initialize handshake before invoking
thread or turn methods. `turn/steer` requires the expected active turn ID and
fails when no turn is active; the adapter must treat that race as a signal to
re-read thread state and use `turn/start`, not as failed mail delivery.

Implemented adapter shape:

1. `agentpost codex` launches a fresh loopback WebSocket app-server and attaches
   the ordinary TUI plus a dependency-free Node bridge.
2. The bridge discovers the one loaded TUI thread through
   `thread/loaded/list` and binds it to the project-derived AgentPost identity.
3. On delivery, query or track thread status.
4. For immediate:
   - call turn/steer with the expected active turn ID when active;
   - call turn/start when idle.
5. For idle:
   - leave the letter unread while a turn is active;
   - on turn/completed, start a turn containing the mailbox reference;
   - if already idle at arrival, start that notification turn immediately.
6. Codex SessionStart/Stop hooks provide catch-up for ordinary launches. An
   adapter-owned active marker suppresses those fallback hooks while the bridge
   owns delivery; inherited environment variables were measured to be
   insufficient because Codex sanitizes hook environments.
7. Activation first surfaces every currently unread letter.

The adapter should inject a concise pointer such as "New AgentPost mail:
<message-id>. Read it from your configured mailbox." It should not duplicate
the entire letter into the control channel.

Live acceptance proved loaded-thread binding, restart catch-up, active-turn
`turn/steer`, idle deferral into a distinct `turn/start`, exact-ID processing,
fallback-hook exclusion, and launcher cleanup. Static doctor also verifies the
two explicit hook trust records; plugin installation alone is intentionally
reported as incomplete until those records exist.

Official references:

- https://developers.openai.com/codex/app-server
- https://developers.openai.com/codex/hooks

## 17. Gemini CLI Adapter Candidate

Gemini CLI currently exposes two relevant official integration surfaces:

- lifecycle hooks, including BeforeAgent and AfterAgent;
- Agent Client Protocol mode, started with gemini --acp, which makes Gemini CLI
  a JSON-RPC server over stdio.

AfterAgent fires once per turn after the final model response and can reject the
response to trigger a follow-up turn with feedback. It is therefore a usable
idle/final boundary. SessionStart can supply catch-up context at activation.

Gemini's Notification hook reports events outward; it is not an inbound wake
surface. No documented FileChanged equivalent was found. Extension management
also requires a process restart, and changes made by `extensions install`,
`link`, `enable`, or `disable` do not affect an already-running session.

ACP mode supports initialize, authentication, newSession, loadSession, prompt,
and cancel. It is the cleanest known semantic input edge for a Gemini agent
controlled by another local program.

### 17.1 Managed ACP profile

Candidate adapter shape:

1. Run the active Gemini agent in ACP mode under a client that owns its stdio.
2. Bind one AgentPost agent name to one ACP session.
3. Use prompt to deliver mailbox references while the session is idle.
4. Treat the completion of the ACP prompt response as the next idle boundary.
5. Queue idle mail until that boundary.
6. Queue immediate mail for the earliest supported prompt boundary.
7. Do not cancel an in-flight prompt merely to deliver mail.

The current ACP documentation does not describe an in-flight equivalent of
Codex turn/steer. Therefore immediate may honestly degrade to next-boundary
delivery while Gemini is busy. The adapter must advertise that limitation.

This profile requires an adapter process because ACP uses stdio and the client
must own the Gemini process. That adapter remains optional and outside the
filesystem core. It is a post-v0 full-capability profile unless the founder
explicitly expands v0 beyond already-running CLI sessions.

### 17.2 Ordinary interactive profile

For a normal interactive Gemini CLI session:

1. SessionStart performs unread catch-up.
2. AfterAgent checks for queued idle mail at the final-response boundary.
3. If mail is pending, the hook can request a follow-up turn containing a
   mailbox reference.
4. Notification hooks may signal the human, but they are outbound
   observability rather than an external prompt-injection API.

No official FileChanged-style external wake hook was found in the current
Gemini hook reference. Unless another supported input surface is verified, an
ordinary interactive Gemini adapter must report:

- idle: supported at AfterAgent and SessionStart boundaries;
- immediate while busy: degraded to next boundary;
- immediate while already idle: unsupported without ACP or the generic
  fallback's human notification.

Do not fill this gap with terminal keystroke injection.

The local Gemini CLI was version 0.27.3 when this spec was written. Current
official documentation describes newer capabilities, and this installation was
not authenticated. A live adapter prototype must first update or verify the
installed version and configure authentication rather than assume the
documented surfaces exist locally. Gemini remains outside the initial
Cx/K/PB/C cutover matrix, but its package and capability contract should be
implemented without weakening the universal core.

Official references:

- https://geminicli.com/docs/hooks/reference/
- https://geminicli.com/docs/hooks/best-practices/
- https://geminicli.com/docs/cli/acp-mode/
- https://geminicli.com/docs/cli/session-management/

## 18. Generic Adapter Fallback

For a CLI without a native event or app-server surface:

~~~text
agentpost watch <agent>
~~~

The fallback:

- performs catch-up over unread;
- waits for filesystem changes using the simplest supported mechanism;
- invokes a locally configured notifier callback;
- consumes no LLM tokens while waiting;
- never treats callback failure as delivery failure.

This fallback cannot promise mid-turn injection unless the target CLI exposes a
supported input channel. Its capabilities must be reported honestly.

## 19. Implementation Language and Dependencies

Recommended v0:

- Python 3.11 or newer;
- standard library only at runtime;
- pathlib and os for filesystem operations;
- email package for RFC-style parsing;
- tomllib for configuration reads;
- uuid for message IDs;
- argparse for the first CLI;
- pytest or unittest for development tests.

Do not introduce a database, web framework, queue library, filesystem watcher
dependency, or MCP SDK into the core before the literal-folder acceptance tests
pass.

## 20. Required Acceptance Tests

### 20.1 Core mailbox

- initialize at least four agents;
- register a profile/nameplate for each agent;
- register project-only, role-only, specialist, and hybrid profiles;
- derive the registry solely from profile files;
- list and show profiles without touching mailbox state;
- find candidates by exact topic and explain each match;
- resolve exact role, project, and specialty selectors;
- find a cross-project expert from a prior experience entry and show its
  evidence path;
- prove a familiar correspondent does not outrank a better role match merely
  because it is familiar;
- update one profile atomically without rewriting mail;
- verify tmp and unread share a filesystem;
- prove a real tmp-to-unread rename;
- send a direct Markdown letter;
- inspect it with ordinary filesystem tools;
- prove list and read do not move it;
- prove next atomically moves it to read;
- reply and reconstruct the thread by In-Reply-To;
- reject or report duplicate (Message-ID, recipient) delivery;
- restart an adapter and surface all unread mail without a seen ledger.

### 20.2 Group panel

- route a responsibility query to the smallest relevant candidate set;
- record the routing query/reasons and final resolved audience;
- resolve named and ad hoc groups;
- deduplicate overlapping groups and skip self;
- deliver one shared Message-ID to every recipient mailbox;
- preserve the full audience on every copy;
- collect independently attributed answers;
- meet all and quorum:N predicates;
- timeout with honest partial output and incomplete status;
- accept and render a late answer;
- preserve duplicate replies while counting one responder once;
- never synthesize answers in the core.

### 20.3 Questions and limits

- ask a direct question and print a correlated answer;
- timeout without deleting or cancelling the question;
- leave all recipients pending during a shared provider limit;
- process replies after the limit resets;
- notify the originator when the panel later completes;
- never require another LLM call to detect completion.

### 20.4 Attention timing

- immediate mail is surfaced at the adapter's earliest safe boundary;
- idle mail does not interrupt an active turn;
- idle mail is surfaced after the next final/completed event;
- idle mail arriving while already idle is surfaced;
- notifications do not mark messages read;
- a missed notification leaves the message unread;
- burst coalescing does not merge or reorder files.

### 20.5 Consultation posture

- a cross-project investigation discovers and considers a relevant peer;
- a peer question and local or web investigation can proceed in parallel;
- the selected peer and routing reason remain visible;
- peer advice is attributed and does not displace direct authoritative
  evidence;
- a trivial local task does not generate peer mail;
- an agent-initiated opportunistic question defaults to idle;
- an active blocker can be sent immediate;
- an unavailable or provider-limited peer does not stop independent research;
- a relevant late reply can be incorporated without losing its attribution.

### 20.6 Legacy migration

- prove an AgentPost test request is absent from every legacy inbox;
- prove a legacy installation/control message contains no duplicate actionable
  request already present in AgentPost;
- after committed delivery plus notification failure, send a legacy pointer to
  the existing Message-ID and execute the AgentPost copy exactly once;
- after proven pre-commit delivery failure, fall back through the old channel;
- prove timeout or provider limit does not trigger legacy redelivery;
- run competing consumers against one AgentPost letter and allow only one
  atomic claim to succeed;
- disable old watchers only after the complete four-agent live matrix passes;
- preserve legacy directories as history and complete post-cutover direct and
  council checks through AgentPost alone.

### 20.7 Live adapters

- Claude Code: FileChanged bell, busy/idle tracking, Stop boundary, and
  asyncRewake behavior proven in a live active session;
- Codex: local app-server TUI, thread binding, turn/steer, turn/start, and
  turn/completed behavior proven in a live active session;
- Gemini CLI managed profile: ACP session binding, prompt delivery, response
  completion, and honest no-steer behavior proven live;
- Gemini CLI interactive profile: SessionStart catch-up and AfterAgent idle
  drain proven live, with unsupported immediate behavior reported honestly;
- generic fallback: catch-up plus token-free wait proven without an LLM call.

### 20.8 Installation and Lifecycle

- one canonical skill source produces valid Claude, Codex, and Gemini package
  layouts without copying live registry records into instructions;
- Claude installs at local scope, excludes its bell without changing tracked
  repository files, reloads, and uninstalls while retaining mail;
- Codex installs through a local marketplace, requires explicit hook trust,
  binds one thread, and uninstalls while retaining mail;
- Gemini validates version and authentication, declares required extension
  environment variables, and requires restart after install or link;
- the initial Cx/K/PB/C acceptance does not invoke, update, authenticate, or
  otherwise depend on Gemini;
- the deferred Gemini phase updates the CLI first and pauses for founder login
  before any live adapter test;
- static doctor performs no model call and reports supported and degraded
  capabilities;
- live doctor is opt-in, uses one Message-ID through AgentPost only, and
  verifies catch-up plus the profile's advertised wake behavior;
- failed or partial installation can roll back installer-owned state without
  deleting mail or unrelated CLI settings.

### 20.9 Documentation and Publication

After the live four-agent matrix and the deferred Gemini adapter acceptance are
GREEN, and before the work is called complete, publish documentation that
serves both human operators and CLI agents without requiring prior conversation
context. If Section 26.3 selects a standalone project or maintained fork,
create its GitHub repository at this point. If it selects an upstream
contribution or companion layer, publish the documentation in that project's
appropriate GitHub home instead of creating a confusing duplicate repository.

The repository must include:

- a concise README explaining the trusted-local scope and literal-mailbox
  model;
- a shortest-path quick start from installation through the first direct
  message and reply;
- separate, versioned installation guides for Claude Code, Codex, and Gemini
  CLI, including their different reload, restart, trust, and managed-session
  requirements;
- copyable install, doctor, live-test, upgrade, rollback, and uninstall
  commands;
- an agent-facing integration guide that a fresh CLI instance can follow to
  register itself, discover peers, send, ask, answer, and use immediate versus
  idle correctly;
- the profile/nameplate schema and examples for project, role, specialist, and
  hybrid agents;
- message-format, mailbox-state, routing, panel, and single-channel migration
  reference pages;
- an honest capability matrix showing supported and degraded behavior for each
  CLI profile;
- troubleshooting for missed bells, stale bindings, provider limits,
  authentication, hook trust, extension reloads, duplicate prevention, and
  unread catch-up;
- a tested migration guide from literal legacy inboxes that never duplicates
  an actionable request across channels;
- architecture and contributor documentation sufficient to add another CLI
  adapter without changing the filesystem core;
- a compatibility table populated from live-tested CLI versions rather than
  assumptions from current documentation.

Every documented command must be exercised against a clean temporary runtime
root before publication. Human quick starts and agent-facing instructions must
reference the same canonical behavior and generated command help so they
cannot silently diverge. Documentation updates are required whenever an
adapter's tested compatibility or installation procedure changes.

## 21. Suggested Build Sequence

This sequence applies only after the build-versus-adopt gate in Section 26.3.
If reuse, contribution, or a companion layer wins, replace the standalone
steps below with the smallest plan that satisfies the same acceptance tests.

1. Implement configuration, init, profile registration, and registry reads.
2. Implement deterministic agent discovery with visible match reasons.
3. Implement message parsing, direct send, sent archive, list, read, and next.
4. Implement reply threading and duplicate detection.
5. Implement group resolution and fan-out.
6. Implement ask, quorum waiting, panel rendering, timeout, and late replies.
7. Create one shared mailbox/registry skill source, including the workplace
   consultation posture.
8. Define the bell-adapter interface and a fake adapter for deterministic tests.
9. Build the common installer dispatcher and token-free static doctor.
10. Package and prototype the Claude Code local-scope plugin against current
    hooks.
11. Package and prototype the Codex plugin, trust gate, and app-server adapter.
12. Add the generic watch fallback only after the Claude and Codex prototypes
    clarify the actual common contract.
13. Run the Cx/K/PB/C migration matrix with legacy inboxes as dormant control
    and recovery channels, never actionable mirrors.
14. Retire legacy watchers only after post-cutover AgentPost checks pass.
15. Update Gemini CLI, pause for founder login, then package and prototype the
    Gemini extension, reduced interactive profile, and managed ACP adapter.
16. Run the deferred Gemini live acceptance tests without reopening the
    completed legacy migration.
17. After both acceptance phases are GREEN, publish and clean-install-test the
    complete documentation set in Section 20.9 in the repository selected by
    the build-versus-adopt decision.

## 22. Open Questions

These are implementation questions, not blockers to building the core:

- Final repository/package name after collision checks.
- Final runtime root: ~/.agentpost or an XDG state/data directory.
- Final required and optional profile fields.
- Whether deterministic agents find should rank token overlap or return only
  exact tags and let the active CLI perform all semantic selection.
- Whether experience evidence remains arbitrary local paths or gains a small
  typed reference shape for repositories, documents, and message threads.
- Whether organization and department selectors belong in v0 alongside role,
  project, and specialty selectors.
- How profile changes are surfaced to already-running CLI skills without
  copying registry data into long-lived context.
- Whether consultation posture remains one "consider" default or becomes a
  small off/consider/proactive installation setting.
- Where each CLI should draw the threshold between autonomous peer outreach
  and asking the user before contacting another agent.
- Whether the sent archive is always written or can be disabled.
- Whether a future Gemini release adds an external file-change or in-flight
  steering surface.
- Exact Codex app-server/TUI launch and multi-client thread-binding workflow
  after the first live prototype.
- Whether Gemini's reduced interactive profile proves useful enough in live
  testing to ship beside the recommended managed ACP profile.
- Whether quorum completion notices use the same immediate/idle preference as
  the root question or an explicit completion preference.
- How current Claude Code, Codex, and future CLIs report capability degradation.

## 23. Naming Record

Names proposed during consultation:

- AgentPost / agentpost: current working choice; matches the post-office model;
- agent-maildir: descriptive and technically precise;
- dev-inbox: matches the proven local convention;
- letterbox: human-readable and memorable;
- deaddrop: memorable but less neutral;
- pigeonhole: physical mailbox metaphor.

This directory uses AgentPost as the selected project and package name.

## 24. Source Deliberation

The original local round-robin letters are retained outside this repository as
private design history. This specification is the controlling public synthesis;
a fresh instance does not need the original correspondence to implement or
review the design.

## 25. Handoff to a Fresh Instance

A fresh implementation instance should:

1. Read this file in full.
2. Preserve the governing v0 scope before considering enhancements.
3. Complete the prior-art decision gate in Section 26.3 before implementing a
   standalone transport or creating a repository.
4. If standalone implementation wins, build the filesystem core and its tests
   before any native adapter.
5. Implement profile/nameplate discovery before natural-language routing.
6. Verify current official Claude Code, Codex, and Gemini CLI documentation
   again because hook, app-server, and ACP surfaces can change.
7. Keep one universal protocol while preserving the CLI-specific install,
   reload, trust, state, and wake mechanisms defined in Section 5.10.
8. Treat mail files as the product's durable truth and notification as a
   replaceable edge.
9. Demonstrate direct mail, role-based routing, panel mail, late completion,
   and both attention modes on real active Claude Code, Codex, and Gemini CLI
   sessions, with documented degradation where a profile lacks a capability.
10. Preserve the single-channel execution rule throughout legacy migration;
   never copy an actionable request into both systems.
11. After the live matrix is GREEN, ask the founder for final confirmation and
    publish the tested human and agent-facing documentation required by
    Section 20.9 in the selected GitHub home.
12. Ask the founder before publishing a package or expanding into
    remote/security/runtime-management work.

## 26. Prior Art and Build-Versus-Adopt Gate

A GitHub prior-art survey was performed on 2026-07-09. The premise is not
novel: several active projects connect heterogeneous coding-agent CLIs through
mailboxes, shared stores, hooks, MCP, app-server APIs, or terminal injection.
One project, agmsg, is close enough that independent implementation is no
longer the default next step.

### 26.1 Closest match: agmsg

Repository: https://github.com/fujibee/agmsg

agmsg describes itself as cross-agent messaging for Claude Code, Codex,
Gemini CLI, and other CLI agents with no daemon or network. Its current release
uses Bash plus SQLite, installs a shared agent skill, supports project/team
identities, and exposes monitor, turn, both, and off delivery modes. It already
contains a Claude plugin marketplace path and a beta Codex app-server bridge.

The source checkout inspected at commit
`89980f9c79d0de6475f82041286568e3887e6f85` contained version `1.1.6`, 632
Bats test cases across approximately 9,320 test lines, an MIT license, driver
interfaces, ADRs, install/uninstall paths, machine-facing `llms.txt`, and
current Claude/Codex/Gemini integration work.

Substantial overlap with AgentPost:

- trusted-local, cross-vendor agent messaging;
- no required network service or central daemon;
- persistent identities and teams;
- token-free waiting/checking outside model turns;
- native skills/hooks plus CLI-specific delivery drivers;
- unread/history semantics;
- Codex app-server wake experiments;
- installation, restart/reload, sandbox, and rollback documentation.

Material differences found in the current agmsg implementation:

- SQLite/event-log storage rather than one inspectable Markdown file per
  recipient letter;
- direct team-member messages rather than AgentPost's Message-ID-correlated
  panel/quorum protocol;
- delivery mode selected per project/runtime rather than immediate or idle on
  each message;
- inbox checks mark matching rows read, while AgentPost requires side-effect-free
  inspection and an explicit atomic claim;
- identity and role registration without AgentPost's responsibility,
  specialty, prior-experience, and evidence-based recipient discovery;
- no AgentPost-style sender archive and per-recipient immutable physical copy;
- broader process spawn/resume behavior that AgentPost currently excludes.

These differences are meaningful product choices, but they do not justify
reimplementing agmsg's installer and adapter lessons without first attempting
reuse or upstream collaboration.

### 26.2 Other relevant projects

| Project | Proven shape | Relationship to AgentPost |
| --- | --- | --- |
| MCP Agent Mail | HTTP FastMCP, identities, inbox/outbox, threads, search, Git archive, SQLite index, file leases, human web UI | Very close mail semantics and directory; substantially heavier than the literal-folder trusted-local v0 |
| AgentBridge | Live bidirectional Claude Code and Codex bridge using Claude channels and Codex app-server | Strong evidence for semantic wake and live injection; pair-oriented and daemon-based rather than an N-agent post office |
| Agent Relay | Durable hosted channels, DMs, threads, events, capabilities, harness adapters, and MCP/SDK access | Strong protocol ideas, but hosted/networked and outside v0 scope |
| agentchattr | Local multi-agent chat UI for Claude, Codex, Gemini, and others with automatic mentions | Demonstrates easy onboarding and live wake; relies on server plus terminal/tmux keystroke injection |
| Gas Town | Multi-agent workspace, roles, tasks, mail, hooks, lifecycle, and merge orchestration | Useful tiered adapter model; far broader and more supervisory than AgentPost |
| maestro | Repo-local plain-file task cards, agent/session ownership, messages, and evidence gates | Useful durable-file precedent; messaging is subordinate to project task orchestration |
| CCB | Cross-provider agent workspace with named agents, ask, broadcast, daemon, tmux, worktrees, and mobile control | Mature orchestration precedent; intentionally much larger than the post-office scope |
| ccgram | File mailbox plus broker delivery among CLI agents with Telegram/tmux control | Confirms file-mailbox viability; remote-control and terminal-injection concerns are outside scope |

Primary repository references:

- https://github.com/Dicklesworthstone/mcp_agent_mail
- https://github.com/raysonmeng/agent-bridge
- https://github.com/AgentWorkforce/relay
- https://github.com/bcurts/agentchattr
- https://github.com/gastownhall/gastown
- https://github.com/ReinaMacCredy/maestro
- https://github.com/SeemSeam/claude_codex_bridge
- https://github.com/alexei-led/ccgram

### 26.3 Required decision gate

Before implementing AgentPost's transport or native adapters:

1. Map the AgentPost acceptance matrix against current agmsg behavior and code,
   marking each requirement pass, extension, conflict, or unknown.
2. Run an isolated live agmsg trial with one Claude Code and one Codex agent;
   add Gemini only after its local version and authentication are ready.
3. Test install, identity registration, direct send/reply, unread behavior,
   token-free waiting, turn delivery, Codex monitor delivery, restart catch-up,
   and uninstall without using the legacy inbox as an actionable mirror.
4. Estimate four implementation paths:
   - contribute the missing behavior upstream to agmsg;
   - build AgentPost's registry/question/panel layer on agmsg;
   - maintain a narrow MIT-licensed fork with clear attribution;
   - build standalone only where the literal-Maildir protocol cannot be added
     without fighting agmsg's architecture.
5. Present the measured comparison and recommendation to the founder before
   writing the standalone filesystem core or creating a GitHub repository.

Selection criteria, in order, are reliable cross-CLI wake, simplest operator
installation, preservation of the required communication semantics, smallest
maintenance burden, inspectability, and clean rollback. Novelty or ownership
of a new repository is not a selection criterion.

If reuse wins, AgentPost may become an agmsg contribution, driver, companion
layer, or renamed specification rather than an independent transport. If
standalone wins, its eventual README must include a candid comparison with
agmsg and explain the concrete behavioral requirements that made a separate
implementation necessary.

### 26.4 Gate Result

The gate was executed on 2026-07-09 and selected an independent AgentPost
semantic core with native adapters informed by agmsg's implementation and
tests. Static analysis, the 632-test upstream suite, an isolated store
experiment, a live Claude monitor exchange, and a live Codex app-server exchange
were completed. The detailed evidence and option analysis are recorded in:

`PRIOR_ART_EVALUATION.md`

The decisive conflicts were durable storage and read semantics, unread
catch-up truth, stable ordering, per-message attention intent, Message-ID reply
and panel correlation, and responsibility-based discovery. Agmsg remains the
primary adapter prior art; its transport is not an AgentPost runtime dependency.
