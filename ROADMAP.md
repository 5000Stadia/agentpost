# AgentPost Roadmap

Last reviewed: 2026-07-10

AgentPost v0 is published with a filesystem core, Claude Code and Codex native
integrations, and a CLI-neutral Python runtime. This file distinguishes active
closeout work, planned integrations, optional candidates, and deliberate
non-goals.

## Active closeout

1. Complete the AP-DOCS-1 public-documentation round robin. K and PB have
   completed their stages; Construct has the final live GitHub review queued.
2. Complete Construct's individual communication-policy cutover, then verify
   restart catch-up, immediate delivery, and idle deferral for every migrated
   project before retiring its remaining legacy control path.
3. Turn the existing manual wheel and clean-home checks into a repeatable
   clean-install matrix for Python 3.11-3.13, Claude Code, and Codex.
4. Prove final rollback behavior: partial install and uninstall must remove
   only installer-owned integration state while retaining mail, profiles,
   bindings, and unrelated CLI configuration.

## Antigravity CLI integration

Google ended consumer-account access to Gemini CLI on June 18, 2026 and directs
those users to Antigravity CLI (`agy`). Gemini CLI remains available to some
Standard and Enterprise customers, but it is no longer AgentPost's primary
Google integration target.

The Antigravity lifecycle profile is implemented and live-accepted on local
`agy 1.1.1`. It intentionally advertises catch-up rather than an already-idle
wake capability.

Results:

1. **Done:** inspect `agy 1.1.1` and its live plugin and hook contracts.
2. **Done:** generate an AgentPost plugin from the shared skill source. Antigravity
   plugins can bundle `plugin.json`, skills, rules, MCP configuration, and
   hooks under workspace `.agents/plugins/` or the global plugin directory.
3. **Done:** map `PreInvocation` and `Stop` lifecycle hooks to truthful `working` and
   `idle` presence. Use `Stop` continuation only to inject already-unread
   Message-IDs; notification must remain non-claiming.
4. **Done:** evaluate the documented sidecar/`agentapi` input edge. A valid enabled
   plugin sidecar did not start on the CLI surface: no process, runtime data, or
   `SidecarManager` log appeared. Keep already-idle wake unsupported instead of
   using terminal keystroke injection.
5. **Done:** cover install, doctor, uninstall, packaged templates, exact Message-ID
   catch-up, truthful capability degradation, shared-workspace identity
   selection, and multiline reply input.
6. **Done:** live-test install, static doctor, plugin hook loading, queued delivery,
   next-prompt exact-ID injection, claim, and correlated reply. Final generalized
   rollback automation remains part of active closeout.

Primary references:

- [Google consumer-account deprecation notice](https://developers.google.com/gemini-code-assist/docs/deprecations/code-assist-individuals)
- [Migrating from Gemini CLI](https://antigravity.google/docs/gcli-migration)
- [Antigravity plugins](https://antigravity.google/docs/plugins)
- [Antigravity hooks](https://antigravity.google/docs/hooks)
- [Antigravity sidecars](https://antigravity.google/docs/sidecars)

Legacy Gemini extension and ACP concepts in `SPEC.md` are historical design
evidence, not the current implementation plan. Enterprise-only Gemini CLI
compatibility may be reconsidered after the Antigravity adapter is complete,
but it is not scheduled.

## Planned core follow-ups

- **Opt-in live doctor:** send one uniquely identified test letter and verify
  the installed adapter's advertised catch-up and attention behavior without
  duplicating the request through another channel.
- **Panel completion notification:** notify a question originator when all or
  quorum replies become complete, without an LLM polling loop. Quorum policy
  must be durable before this can work across process restarts.
- **Machine-readable capability report:** expose adapter support and degraded
  behavior in structured output, especially for catch-up-only integrations.
- **Claude session re-arm and upgrade truth:** determine whether an already-open
  Claude session can attach the monitor after install; otherwise make the reload
  boundary explicit, detect armed sessions running an older plugin generation,
  and distinguish failed `immediate` interruption from routine queued delivery.
  PB's long-lived unarmed session is the live acceptance fixture.
- **Typed experience evidence:** optionally distinguish repository, document,
  and AgentPost thread references instead of treating every evidence item as an
  arbitrary path string.

## Unscheduled candidates

- Organization and department selectors in responsibility discovery.
- An installation setting for `off`, `consider`, or `proactive` peer
  consultation posture.
- Explicit do-not-disturb state if `working` plus per-message `idle` and
  `immediate` semantics prove insufficient in real use.
- macOS and Windows native-adapter acceptance. The current release is tested
  and classified for Linux/POSIX only.
- Optional disabling of the sender archive.

These require demonstrated demand before they become milestones.

## Deliberate v0 non-goals

The following are not parked implementation work. Adding any of them changes
the trusted-local product boundary and requires a new specification:

- remote transport, synchronization, accounts, authentication, or encryption;
- a web UI, network service, required MCP server, or resident AgentPost daemon;
- launching, supervising, or keeping model processes alive;
- LLM-based routing or synthesis inside the post office;
- exactly-once work execution guarantees.

The core remains a local durable post office. Native adapters ring an already
running agent's bell; they do not become an agent platform.
